# Wildlife Observatory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working wildlife observatory: folder/FTP import → MegaDetector → geometric tracks →
encounters → alerts → SpeciesNet classification → SQLite → Next.js dashboard + structured search,
deployable to a Raspberry Pi 400 via Docker Compose.

**Architecture:** Three deployables. `edge/` (FastAPI + SQLite, no torch) owns the DB, ingest,
job queue, tracking, encounters, alerts, backups. `worker/` (SpeciesNet in-process) claims
`detect`/`classify` jobs over HTTP. `web/` (Next.js) proxies `/api` and `/media` to the edge.

**Tech Stack:** Python 3.12 + uv, FastAPI, sqlite3 (stdlib, raw SQL), Pillow, httpx,
speciesnet 5.0.6, OpenCV headless, Next.js (App Router, TypeScript), pyftpdlib, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-21-wildlife-observatory-design.md`

**Execution mode (owner's instruction):** owner is away and asked for fully autonomous work;
executed natively in-session, Phase 0 first, then as far as time allows. Owner reviews on return.

## Global Constraints

- Python `>=3.12,<3.13` (speciesnet requires `<3.15`; Mac default is 3.15.2). Use `uv`.
- `speciesnet==5.0.6`; never install the separate `megadetector` package.
- SpeciesNet used in-process: `SpeciesNetDetector`, `SpeciesNetClassifier`, `SpeciesNetEnsemble`, loaded once.
- Location filter defaults: `COUNTRY=USA`, `ADMIN1_REGION=NJ`. `CAMERA_TIMEZONE=America/New_York`.
- All timestamps stored as UTC ISO-8601 (`...Z`); hour-of-day computed in `CAMERA_TIMEZONE`.
- Only the edge opens the SQLite file (WAL mode). Workers use HTTP only.
- Predictions are never updated in place by corrections; corrections are separate rows.
- Counts are per encounter, never per frame.
- Person-containing media (`has_person=1`): never sent as an image to ntfy; excluded from best frame and default gallery.
- Bulk CLI imports set `suppress_alerts=1`; so do captures older than 15 minutes.
- Search answers come only from SQL results and always include source encounter/media IDs.
- No paid services. Nothing binds publicly beyond LAN/tailnet in deploy docs.
- CLI name: `observatory`. Repo: `abhinavs-27/wildlife-observatory`.

## Review Focus

1. Same file imported twice (or via two paths) → exactly one media row, no new job.
2. Corrupt/truncated JPEG or unsupported file → media `failed` with error, after N=3 failures moved to `quarantine/`, other files continue.
3. Image with zero detections → status `empty`, no encounter, no alert.
4. Classification arrives while/after encounter exists → species updates in place, no second alert.
5. Stale worker posts result after lease reassigned → 409, no duplicate predictions.

Each is pinned by a test in the owning task (Tasks 3, 3, 5, 6, 4).

---

## File Structure

```
AGENTS.md  README.md  .gitignore  .env.example  docker-compose.yml
docs/{architecture,running,pi-deployment,hardware-untestable,benchmarks,limitations}.md
edge/
  pyproject.toml  Dockerfile
  src/observatory_edge/
    config.py        # Settings from env
    db.py            # connect(), init_db(), schema.sql loader
    schema.sql       # full §7.4 schema
    timeparse.py     # captured_at extraction
    ingest.py        # hash, store original, create device/event/media/job, quarantine
    adapters.py      # CameraAdapter protocol, LocalFolderAdapter, FolderWatcher loop
    jobs.py          # claim/heartbeat/complete/fail with claim tokens + leases
    taxonomy.py      # parse 7-part labels, uncertainty
    results.py       # apply detect/classify results
    tracking.py      # geometric tracker + encounter grouping
    alerts.py        # outbox + ntfy sender
    search.py        # intent matcher → SQL
    queries.py       # read models for the dashboard
    backup.py        # online backup + verify + rotate + pull
    api.py           # FastAPI app (worker + dashboard routes)
    cli.py           # `observatory` CLI: import, serve, backup, pull
  tests/...
worker/
  pyproject.toml  Dockerfile
  src/observatory_worker/{config,client,frames,models,runner,main}.py
  tests/...
scripts/{fetch_samples.py,benchmark.py,ftp_receiver.py}
web/ (Next.js app)
```

---

### Task 1: Repo skeleton, AGENTS.md, GitHub

**Files:** Create `AGENTS.md`, `README.md`, `.gitignore`, `.env.example`, `edge/pyproject.toml`.

- [ ] Step 1: Write `.gitignore` (data/, media/, .venv, node_modules, .env, *.sqlite*, samples/).
- [ ] Step 2: Write `AGENTS.md` (layout, commands, invariants from Global Constraints, workflow).
- [ ] Step 3: `edge/pyproject.toml` (fastapi, uvicorn, pillow, httpx, python-multipart, pyftpdlib; dev: pytest) and `uv sync`.
- [ ] Step 4: `gh repo create abhinavs-27/wildlife-observatory --public --source . --push`.
- [ ] Step 5: Commit.

### Task 2: Edge DB schema and config

**Files:** `edge/src/observatory_edge/{config.py,db.py,schema.sql}`, `edge/tests/test_db.py`

**Interfaces — Produces:**
- `Settings` dataclass, `get_settings() -> Settings` reading env: `DATA_DIR` (default `./data`),
  `WORKER_TOKEN`, `CAMERA_TIMEZONE`, `COUNTRY`, `ADMIN1_REGION`, `ENCOUNTER_GAP_S=120`,
  `ALERT_THRESHOLD=0.5`, `PERSON_THRESHOLD=0.5`, `UNCERTAIN_SCORE=0.5`, `LEASE_S=600`,
  `MAX_ATTEMPTS=3`, `ALERT_MAX_AGE_S=900`, `NTFY_URL`, `NTFY_TOPIC`, `DISK_FLOOR_PCT=95`.
  Derived paths: `db_path`, `originals_dir`, `frames_dir`, `quarantine_dir`, `inbox_dir`, `backups_dir`.
- `connect(db_path) -> sqlite3.Connection` (WAL, foreign_keys, Row factory); `init_db(conn)`.

- [ ] Test `test_init_db_creates_all_tables`: tables include device, event, media, frame, model,
  inference_run, detection, classification, track, track_detection, encounter, encounter_track,
  individual, correction, job, worker, alert, backup.
- [ ] Test `test_persistence_across_connections`: insert device, close, reopen → row present.
- [ ] Implement; tests pass; commit.

### Task 3: Ingest + timestamps + folder adapter + CLI import

**Files:** `timeparse.py`, `ingest.py`, `adapters.py`, `cli.py`; tests `test_timeparse.py`, `test_ingest.py`.

**Interfaces — Produces:**
- `extract_captured_at(path: Path, tz: str) -> tuple[str, str]` → (UTC ISO, source in `exif|container|mtime`).
- `ingest_file(conn, settings, path: Path, device_name="default", suppress_alerts=False, adapter="folder") -> IngestResult`
  where `IngestResult(status: Literal["created","duplicate","failed","quarantined","unsupported"], media_id: int|None, error: str|None)`.
  Creates device (if missing), event(kind=capture), media, and a `detect` job. Copies original to
  `originals/YYYY/MM/<sha256>.<ext>` via temp file + `os.replace`.
- `LocalFolderAdapter(root, stable_seconds=2).discover() -> list[Path]` (supported, size/mtime stable).
- `import_folder(conn, settings, folder, device, suppress_alerts=True) -> Counter`.
- CLI `observatory import <folder> [--device NAME]`.

- [ ] Tests: naive EXIF `2024:06:01 06:42:00` with tz America/New_York → `2024-06-01T10:42:00Z`, source `exif`; no EXIF → `mtime`.
- [ ] Tests: duplicate import → second `duplicate`, 1 media row, 1 job; same bytes different filename → duplicate.
- [ ] Tests: corrupt JPEG → `failed`; third failure of same path → `quarantined`, file moved into `quarantine/`.
- [ ] Tests: `.txt` → `unsupported`, not quarantined. Partial (still growing) file not discovered.
- [ ] Implement; pass; commit.

### Task 4: Job queue + worker HTTP protocol

**Files:** `jobs.py`, `api.py` (worker routes); test `test_jobs_api.py` (FastAPI TestClient).

**Interfaces — Produces:**
- `claim_job(conn, kinds: list[str], worker_id: str, lease_s: int) -> dict|None` (atomic `UPDATE ... RETURNING`, sets random `claim_token`, requeues expired leases first).
- `heartbeat(conn, job_id, token) -> bool`; `verify_token(conn, job_id, token) -> bool`;
  `complete_job(conn, job_id)`; `fail_job(conn, job_id, token, error, retryable, max_attempts)`.
- Routes (Bearer `WORKER_TOKEN`): `POST /jobs/claim`, `POST /jobs/{id}/heartbeat`,
  `POST /jobs/{id}/frames` (multipart files + `claim_token`, form `indexes`, `time_offsets`),
  `POST /jobs/{id}/result`, `POST /jobs/{id}/fail`, `GET /media/{id}/original`, `GET /frames/{id}/file`,
  `POST /workers/heartbeat`.

- [ ] Tests: claim returns token; second claim returns 204; missing bearer → 401.
- [ ] Test (Review Focus 5): lease expires → job reclaimed with new token; result with old token → 409; no detection rows.
- [ ] Test: fail retryable under max → back to `queued`; at max → `failed` and media status `failed`.
- [ ] Implement; pass; commit.

### Task 5: Detect results → tracks → encounters → alerts

**Files:** `results.py`, `tracking.py`, `alerts.py`; tests `test_detect_flow.py`, `test_tracking.py`.

**Result payload (detect):** `{claim_token, model:{name,version}, timings:{}, peak_rss_mb, frames:[{frame_id, detections:[{category:"animal|person|vehicle", conf, bbox:[x,y,w,h]}]}]}`.
For images the edge pre-creates frame index 0 = the original; the worker may skip `/frames`.

**Interfaces — Produces:**
- `apply_detect_result(conn, settings, job, payload) -> None`: inserts model/run/detections,
  sets `has_person`, media status `detected|empty`, `active_detection_run_id`, queues `classify` if animals,
  then `rebuild_window(conn, settings, device_id, captured_at)`.
- `link_tracks(dets: list[DetRef], iou_min=0.3, max_gap_s=30) -> list[list[DetRef]]` (greedy IoU, then centroid < 0.15).
- `rebuild_window(conn, settings, device_id, around_ts) -> list[int]` (encounter ids): recompute tracks and encounters for
  captures within ±gap chain; merge into earliest encounter id; re-point alerts/corrections; queue alert for new encounters.
- `queue_alert(conn, settings, encounter_id)`; `send_pending_alerts(conn, settings, sender)`; `NtfySender`.

- [ ] Tests: one animal image → 1 track, 1 encounter (species `pending`), 1 alert queued (unless suppressed).
- [ ] Test: 6 photos 5 s apart with overlapping boxes → 1 encounter, 1 alert.
- [ ] Test: two animals in one image → encounter count 2.
- [ ] Test (Review Focus 3): zero detections → `empty`, no encounter, no alert.
- [ ] Test: person + animal → `has_person=1`, alert has no attachment, not best frame.
- [ ] Test: bridging capture merges two encounters into earliest id.
- [ ] Test: suppress_alerts → no alert row.
- [ ] Implement; pass; commit.

### Task 6: Classify results + taxonomy + corrections

**Files:** `taxonomy.py`, `results.py` (classify), `queries.py` (effective labels); tests `test_taxonomy.py`, `test_classify_flow.py`.

**Result payload (classify):** `{claim_token, model:{name,version}, ensemble:{name,version}, geofence:{country,admin1}, classifications:[{detection_id, label, score, source, raw:[{label,score}]}]}`.

**Interfaces — Produces:**
- `parse_label(s) -> Taxon(uuid, cls, order, family, genus, species, common_name, level)`; level in species|genus|family|order|class|none.
- `is_uncertain(taxon, score, threshold) -> bool` (level≠species, score<threshold, or common_name in animal/blank/unknown/no cv result).
- `apply_classify_result(...)`: insert classifications, set `active_classification_run_id`, recompute track species votes and encounter species (no new alert).
- `add_correction(conn, target_type, target_id, action, label, note)`; encounter corrections store window.

- [ ] Tests: parse raccoon label → species level, common name "northern raccoon"; rolled-up sciuridae → family level, uncertain; unknown label → uncertain.
- [ ] Test (Review Focus 4): classification after encounter → encounter species "northern raccoon", alert count stays 1.
- [ ] Test: correction relabel → effective label changes, classification row unchanged.
- [ ] Implement; pass; commit.

### Task 7: Worker (SpeciesNet in-process, frames, HTTP loop)

**Files:** `worker/src/observatory_worker/{config,client,frames,models,runner,main}.py`; tests `test_frames.py`, `test_runner.py` (fake models + respx).

**Interfaces — Produces:**
- `sample_video(path, fps=1.0, max_frames=30) -> list[(index, offset_s, PIL.Image)]`.
- `Models` protocol: `detect(img) -> list[Det]`, `classify(img, dets) -> list[RawCls]`, `combine(...) -> list[FinalCls]`; `SpeciesNetModels(country, admin1)` real impl.
- `Runner(client, models, kinds).run_once() -> bool`; handles detect (download original, sample, detect, upload kept frames, post result) and classify (download frames, classify crops, ensemble, post).
- CLI `observatory-worker --edge-url --token --kinds detect,classify [--once]`.

- [ ] Tests: sample_video on a generated 3 s mp4 → 3 frames; runner detect path posts expected payload with fake models; model exception → `/fail` called with retryable=false after 1.
- [ ] Implement real `SpeciesNetModels` per speciesnet 5.0.6 API (inspect signatures); pass; commit.

### Task 8: Sample data + Phase 0 gate + benchmark

**Files:** `scripts/fetch_samples.py`, `scripts/benchmark.py`, `docs/benchmarks.md`.

- [ ] fetch_samples: download a few dozen real public camera-trap images (LILA / SpeciesNet repo samples) into `samples/`, with a manifest + licence note.
- [ ] Run edge + native worker, import samples, verify at least one animal detection with species in SQLite.
- [ ] benchmark.py: per stage load time, per-image time, peak RSS → write `docs/benchmarks.md`.
- [ ] Commit.

### Task 9: Dashboard API + Next.js

**Files:** `edge/.../queries.py`, `api.py` (`/api/*`), `web/*`.

- Edge routes: `GET /api/encounters?species=&from=&to=&uncertain=&limit=`, `GET /api/encounters/{id}`,
  `GET /api/media?...`, `GET /api/species`, `GET /api/activity?species=`, `POST /api/corrections`,
  `GET /api/health`, `GET /api/health/details`, `POST /api/ask`.
- Web pages: `/` (recent encounters + stats + status badge), `/gallery`, `/encounters/[id]` (SVG bbox overlay, correction form),
  `/activity` (hour/day bars), `/ask`, `/status`. `next.config` rewrites `/api/:path*`, `/media/:path*`, `/frames/:path*` → `EDGE_INTERNAL_URL`. `output: 'standalone'`.
- [ ] Edge API tests for each route; `npm run build` passes; commit.

### Task 10: Structured NL search

**Files:** `search.py`; test `test_search.py`.
- `answer(conn, settings, question) -> Answer(text, intent, rows, sources:[encounter_id])`.
- Intents: list_species, sightings_of, activity_of, rarest, most_common, last_seen, count_of; date phrases today/yesterday/this week/last week/this month/last month.
- Species resolution: match common_name LIKE, genus/family/class synonyms (squirrel→sciuridae, bird→aves, deer→cervidae, fox→canidae+vulpes/urocyon...).
- [ ] Tests vs SQL ground truth; unknown question → "I don't understand that yet"; no matches → "No sightings found"; commit.

### Task 11: Deployment readiness

**Files:** `edge/Dockerfile`, `worker/Dockerfile`, `web/Dockerfile`, `docker-compose.yml`, `scripts/ftp_receiver.py`, `backup.py`, docs.
- Compose profiles dev/pi/worker; restart unless-stopped; healthchecks; mem_limit on worker; log caps; volumes data/weights.
- FTP receiver: pyftpdlib, `.incoming` → atomic rename to `inbox/ready`, `on_incomplete_file_received` cleanup, 452 below disk floor, masquerade address env.
- Edge background loops: folder watcher on `inbox/ready`, alert sender, nightly backup, lease reaper.
- Backup: `sqlite3.backup`, `PRAGMA integrity_check`, rotate 7; `observatory backup pull --from http://pi:8000`; `GET /api/backups/latest`.
- Docs: architecture, running (macOS + ARM64 Linux), Pi deployment (Tailscale, buildx), untestable-without-hardware, limitations.
- [ ] Tests: ftp receiver rename + incomplete cleanup; backup/restore round trip; `docker compose config` valid; commit + push.
