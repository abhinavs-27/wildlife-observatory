# Wildlife Observatory — Design

Date: 2026-11-21
Status: draft v4 (your extra requirements + two external reviews), awaiting approval
Repo: `github.com/abhinavs-27/wildlife-observatory` (public, to be created)

## 1. Intent

A hobby backyard wildlife observatory at the owner's parents' house in **New Jersey**.
A battery-powered Reolink Argus Solar Wi-Fi camera captures motion photos and clips. A
Raspberry Pi 400 indoors acts as a **low-power, always-on edge server**: it ingests
media, stores it, runs light detection, sends phone alerts, and serves a dashboard and
an "ask the observatory" search. Heavier AI runs on the Pi only if benchmarks say it
can; otherwise it runs on another machine (the owner's Mac) with no code changes.

The owner visits about **once a month**, so the system must run unattended for about
30 days and be managed remotely over Tailscale.

The hardware has not arrived. Everything is built and tested on the owner's Mac (Apple
Silicon, arm64, Docker available) against **real public camera-trap images**, then
deployed to Raspberry Pi OS ARM64.

It's for fun: simplicity and "it actually works" beat scale and polish.

## 2. Goals

- Working end-to-end software, not mockups: import → detect → classify → track →
  group into encounters → store → dashboard → search → alert.
- Real detection results on public images **before** dashboard work.
- **Benchmarks before Pi assumptions**: memory and time per image for each model,
  measured on the Mac and later on the Pi, and recorded in the repo.
- Phone alerts within about a minute of an animal capture, even if species
  classification happens later or elsewhere.
- Unattended operation for a month: survives reboots, network drops, full disks, and
  the AI worker being offline.
- An extensible event and device model, so future cameras and sensors fit without a
  redesign.

## 3. Non-goals (MVP)

- Live streaming, continuous recording, or continuous frame analysis.
- Automatic recognition of individual animals across encounters. Only the schema and
  manual tagging are built; any automation is experimental and off by default.
- Implementing sensors (bird calls, temperature/humidity, pond level/temperature,
  rainfall) or environmental correlation. Only the data model accommodates them.
- Training or fine-tuning models.
- Multi-user accounts, public hosting, or any paid service by default.

## 4. Anti-goals (a failure even if it "works")

- **Inventing observations.** Every fact comes from the database, every answer links
  to source images or videos, and uncertain classifications are shown as uncertain.
  Unanswerable questions get "I don't understand that yet" or "No sightings found."
- **Counting frames as sightings.** One fox in 30 frames is one encounter.
- Overwriting model predictions with corrections, or losing old predictions when
  reprocessing with newer models.
- Duplicate media from re-imports or resumed uploads.
- A model crash or out-of-memory error taking down ingestion or the dashboard.
- **Core features depending on the AI worker being online.** Ingest, detection,
  encounters and alerts keep working when the Mac is away.
- Anything exposed to the public internet (dashboard, API, FTP).
- Silent failure: if the AI worker or a cloud AI is unavailable, the dashboard says so
  plainly.
- Architecture that only works on the Mac (x86-only images, CUDA assumptions).

## 5. Constraints and verified facts

### Hardware
- Pi 400: 4 GB RAM, ARM64, microSD (optional USB SSD later), indoors, home Wi-Fi.
- Camera: battery-powered, no outdoor power. **Do not assume** RTSP, ONVIF, an open
  API, or continuous recording.
  - Per the external review, the Argus Solar acts as an **FTP client that pushes**
    motion files (plain FTP/FTPS, not SFTP) to a server. It is not a server we can
    poll. This must be **verified on the real camera**.
  - Events may be **photos only**; video is optional.
  - Cameras may upload a JPG *and* an MP4 for the same trigger, and files can arrive
    out of order.
- **Timestamps:** photo EXIF time (`DateTimeOriginal`) is usually camera local time with
  no timezone. MP4 `creation_time` is UTC, and file modification time is a UTC epoch.
  A required `CAMERA_TIMEZONE` setting (`America/New_York`) interprets times that have
  no timezone. Everything is stored as UTC, and hour-of-day analytics are computed in
  `CAMERA_TIMEZONE`.
- **RAM budget (estimates, to be benchmarked):**

  | Part | Estimate |
  |---|---|
  | OS + Docker | 0.5–0.7 GB |
  | Detector (torch + MDv5a) | 1.0–1.4 GB |
  | Classifier (torch + EfficientNetV2-M) | 1.2–1.6 GB |
  | Web | 0.2–0.35 GB |
  | Edge API | 0.15–0.25 GB |

  Two resident torch processes plus the web dashboard are unlikely to fit in 4 GB,
  which drives the Pi worker mode in §7.1.
- Wi-Fi at the camera: 15–30 Mbps down, 11–25 Mbps up.

### Models (checked against PyPI and the official README, 2026-11-21)
- **SpeciesNet** (`speciesnet` 5.0.6; Python `>=3.9,<3.15`; `torch>=2.0`; pins
  `yolov5>=7.0.8,<7.0.12`). It bundles **MegaDetector v5a** (`md_v5a.0.1.pt`) and the
  SpeciesNet classifier (default crop model **v4.0.3a**). Weights auto-download from
  Kaggle/GitHub on first run.
  - **Three stages** (verified in the 5.0.6 source): detector → classifier → ensemble.
    - The classifier alone emits only `raw_classifications` (top 5).
    - The **ensemble** stage (`SpeciesNetEnsemble.combine`, CLI `--ensemble_only`)
      applies the location filter (`country`/`admin1_region`), rolls labels up to
      broader groups, and applies fallbacks.
    - Its output is `processed_classification`, with `class`, `score` and `source`
      (for example `detector`, `classifier`, or a rollup or location-filter step).
  - **Use the in-process Python API, not the CLI per job.** `SpeciesNetDetector`,
    `SpeciesNetClassifier` and `SpeciesNetEnsemble` are loaded **once** when the worker
    starts and kept in memory. Calling the CLI per job would reload torch and the
    weights every time.
  - In the default `always_crop` mode, each detection (up to
    `max_classifications_per_image`) is classified individually.
  - Detection `category`: "1" animal, "2" human, "3" vehicle. Each detection also has
    `conf` and a normalized `bbox [x,y,w,h]`.
  - **Labels are 7-part strings**:
    `"<uuid>;<class>;<order>;<family>;<genus>;<species>;<common name>"`. They may be
    rolled up, for example `"…;mammalia;rodentia;sciuridae;;;squirrel family"`. Special
    values are `blank`, `animal`, `human`, `vehicle`, and `unknown`
    (`…;no cv result;…`) for low-confidence fallbacks.
  - Device selection order: CUDA → **Apple MPS** → CPU. MPS is only reachable when
    running natively on macOS, not inside Docker, so the Mac AI worker runs natively
    via `uv`.
  - Location filter: `country=USA`, `admin1_region=NJ` (configurable).
  - The weights cache (Kaggle/HF) lives in a persistent volume, so restarts don't
    re-download hundreds of MB.
  - `yolov5` pulls in OpenCV. On `python:3.12-slim`, install
    `libgl1 libglib2.0-0 ffmpeg`, or force `opencv-python-headless`.
- Don't also install the separate `megadetector` package. It pins
  `ultralytics-yolov5==0.1.1`, which is likely to conflict with SpeciesNet's `yolov5`
  pin. Video frame extraction is our own OpenCV/FFmpeg code.
- **Python 3.12** via `uv`. The Mac's default `python3` is 3.15.2, which SpeciesNet
  rejects. Images use `python:3.12-slim` (multi-architecture).
- Pi performance is unknown until measured. MegaDetector v5a is a large YOLOv5 model,
  so "lightweight inference" on the edge means **whatever the benchmark shows fits**.
  If MegaDetector is too slow or heavy on the Pi, detection moves to the AI worker
  too, and alerts say "new capture" until detection completes. This fallback is
  documented.

### Other
- No paid services by default. Node (Volta), ffmpeg, docker, gh and uv are available on
  the Mac.

## 6. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| **A** | Edge service owns SQLite and a jobs table; AI workers are separate processes that claim jobs and post results **over HTTP** | A small job-claiming protocol to build and test | **Chosen** |
| B | Celery + Redis | Standard retries, but an extra service on a 4 GB Pi, and the queue must be exposed for remote workers | Rejected |
| C | One process does everything | Fewest parts, but a model crash kills ingestion and the dashboard; remote AI needs building later anyway | Rejected |

The owner picked **A**. Running AI on the Pi or another machine is one setting
(`EDGE_URL`), the dashboard survives model failures, and no message queue service is
needed. It also matches the owner's later requirement for "three independently
deployable components".

## 7. Architecture

```
 camera ─FTP push─▶ FTP receiver (inbox/ready) ─▶ CameraAdapter ─▶ originals/ (immutable)
                                                       │
                                                       ▼
 ┌──────────────────────── EDGE SERVICE (Pi) ───────────────────────────┐
 │ FastAPI · SQLite (WAL) · jobs · ingest loop                          │
 │ geometric tracking · encounter grouping · alert outbox               │
 │ retention · backups · /health · structured logs                      │
 └───────▲──────────────────────────────▲──────────────────────▲────────┘
         │ HTTP (claim/frames/result)    │ HTTP (proxied)        │ outbound HTTPS
   INFERENCE WORKERS                WEB DASHBOARD (Next.js)   ntfy (alerts)
   Pi: detect (+ classify if fits)  browser → :3000 only
   Mac (native, MPS): classify, optional LLM
```

### 7.1 Three deployable components

1. **Edge service** (`edge/`): ingestion, storage, event handling, REST API, job queue,
   geometric tracking, encounter grouping, alert outbox, retention, backups and health.
   It is the only process that connects to the database. It has no torch dependency.
2. **AI worker** (`worker/`): consumes `detect`, `classify`, and optional `analyze`
   (LLM/multimodal) jobs; which kinds it takes is configured.
   - It talks to the edge only over HTTP and shares no filesystem with it.
   - It runs on the Pi or on any machine on the tailnet, given `EDGE_URL` and a token.
3. **Web dashboard** (`web/`): the Next.js UI, search box and analytics.
   - The browser only ever talks to the dashboard's own origin. Next.js proxies
     `/api/*` and `/media/*` to the internal edge URL (`http://edge:8000`) via
     rewrites or route handlers.
   - So it works the same from localhost, the LAN and Tailscale (e.g. from your phone).

Each component has its own Dockerfile. Compose profiles:
- `dev`: everything on the Mac.
- `pi`: edge + web + FTP receiver + one inference worker.
- `worker`: the AI worker alone.

Every service has `restart: unless-stopped`, a health check, and capped container logs
(`max-size: 10m`, `max-file: 3`).

**Memory safety on the Pi:**
- Inference containers get explicit `mem_limit`s, so running out of memory only ever
  kills a worker, never the edge or web.
- **Pi worker mode = one combined, sequential inference worker.** A single process
  handles `detect` jobs first (they drive alerts) and then `classify` jobs, so only
  one copy of torch is in memory. The Phase 0/1 and Phase 4 benchmarks decide whether
  it keeps both models loaded or loads the classifier only when needed.
- When the Mac is available, the AI worker runs **natively on macOS via `uv`** (using
  MPS) pointing at `EDGE_URL`, and the Pi worker only does detection.
- Next.js uses `output: 'standalone'` to cut idle RAM.
- **Images are never built on the Pi.** `linux/arm64` images are built on the Mac
  (`docker buildx`) and pulled or loaded on the Pi.

### 7.2 Job interface (HTTP)

- Jobs are **media-scoped**: one job is one photo or one video, never one per frame.
- `POST /jobs/claim {kinds[], worker_id, capabilities}` returns a job, a media URL and
  a random **`claim_token`**, or 204 if there's nothing to do.
- `GET /media/{id}/original`: workers download the original file (used by `detect`).
- `POST /jobs/{id}/frames {claim_token}` (multipart): `detect` uploads the frames it
  kept (frames with detections, plus one poster frame) before posting its result. The
  edge returns frame IDs that the result then references.
- `GET /frames/{id}/file`: used by `classify` and the dashboard. A remote classifier
  downloads a few hundred KB of JPEGs instead of a large MP4 over the house's
  11–25 Mbps uplink, and boxes always line up with the exact frame that was detected.
- `POST /jobs/{id}/heartbeat {claim_token}` extends `lease_until` and updates worker
  liveness. Workers send it while processing long videos on a slow Pi.
- `POST /jobs/{id}/result {claim_token, …}` sends predictions, model name and version,
  timings and peak memory. A stale or mismatched token gets **409** and nothing is
  written, so an expired lease can't produce duplicate predictions.
- `POST /jobs/{id}/fail {claim_token, error, retryable}` retries with backoff up to N
  times. After that the job is `failed` and the error shows in the dashboard.
- Leases default to 10 minutes. Expired leases go back in the queue, which covers
  worker crashes.
- Workers send regular heartbeats. If a kind of worker goes quiet past a timeout, the
  edge marks it **offline**, and the dashboard shows something like "Species
  classification paused — AI worker offline since 14:02". Jobs simply wait; nothing is
  dropped.
- Each worker has a shared-secret bearer token, read from env or a secret file.
- Worker job kinds: `detect`, `classify`, and optional `analyze`. `reprocess` creates
  those jobs for a chosen model and scope. Geometric tracking and encounter grouping
  are **edge-internal steps**, not worker jobs (§7.3).

### 7.3 Data flow

1. **Ingest.** A CameraAdapter yields a candidate file.
   - The edge waits until the file is complete: an atomic move into `inbox/ready/` for
     FTP, or size and mtime stability for plain folder imports.
   - It copies the file **unchanged** to `originals/<yyyy>/<mm>/<sha256>.<ext>`.
   - It records full metadata: EXIF or container metadata as JSON, the original
     filename and path, the adapter and the device.
   - It dedupes by SHA-256, so resumed or repeated uploads change nothing.
   - A crash mid-copy leaves only a temp file, which is cleaned up and retried.
   - A file that fails ingest N times moves to a size-capped `quarantine/` folder,
     shown on the Status page, so the adapter never loops on it.
2. **Capture event.** Each media item becomes a `capture` event for its device.
   `captured_at` comes from EXIF (read in `CAMERA_TIMEZONE`), then container metadata
   (UTC), then file mtime. It's stored as UTC along with which source was used.
3. **Frames.** A photo is its own single frame. For videos, the detect worker samples
   frames **in memory** (default 1 per second, capped) and scores them all in one
   batch. It uploads only frames with detections, plus one poster frame, via
   `POST /jobs/{id}/frames`. Empty frames are discarded, which saves microSD space and
   inodes. Photo bursts are just sequential photos.
4. **Detect** (inference worker, Pi): MegaDetector runs over the whole media item and
   produces `detection` predictions.
   - Alerts are suppressed (`suppress_alerts`) for CLI and bulk imports, and for any
     capture whose `captured_at` is more than 15 minutes old (configurable).
   - **Privacy:** any media with a `person` detection above threshold is
     privacy-restricted (`has_person`). Its image is never sent to ntfy (the alert is
     text-only), and it is excluded from best-frame selection, the default gallery and
     the home page.
   - Empty media is marked empty.
5. **Track, group, alert: immediately after detect** (edge, no torch, no pixels). This
   must not depend on the AI worker, which may be offline for days.
   - **Geometric tracking** links detections across consecutive frames of a video and
     across consecutive photos on the same device, using only stored boxes and
     timestamps (IoU or centroid distance). It takes milliseconds on the Pi. It's
     still recorded as a `tracking` model and `inference_run`, so a visual
     re-identification tracker could replace it later.
   - **Encounter grouping** (rules in step 7) runs right after.
   - **The alert is queued per encounter** with species `pending`, for example
     "Animal detected (2 animals) at 6:42am", using the best animal frame. A 6-photo
     burst gives one alert, not six.
   - Alert snapshots are rendered in memory (Pillow → bytes → ntfy). Annotated images
     are never written to disk; the dashboard draws boxes in the browser.
6. **Classify** (AI worker, whenever it's online): the SpeciesNet classifier and
   ensemble run on each animal detection, using the frames from
   `GET /frames/{id}/file`, with the location filter set to `USA/NJ`. They produce
   `classification` predictions.
   - When results land (seconds later, or days later when the Mac wakes), the edge
     recomputes each track's species (a confidence-weighted vote of its detections'
     classifications) and updates the encounter's species and counts in place.
   - No second alert is sent.
7. **Encounter rules** (edge): captures with animal tracks within a configurable gap
   (default 2 minutes, same device) form one `encounter`.
   - An encounter's count per species is the most tracks of that species seen at the
     same time, never the frame count.
   - **Late or out-of-order files:** tracking and grouping are recomputed for the
     affected time window. If a new capture bridges two encounters, they merge into
     the **earliest encounter ID**. Alerts and corrections pointing at the later
     encounter are moved to the merged one, and the merge is logged.
8. **Optional analysis** (AI worker, off by default): an LLM or multimodal model writes
   a short behavior description for an encounter. It is stored as an `analysis`
   prediction with its model, version and the frames it saw.

### 7.4 Data model (SQLite, WAL)

**Generic core** (built for future sensors and cameras):
- `device`: id, kind (`camera` now; later `microphone`, `env_sensor`, `pond_sensor`,
  `rain_gauge`), name, adapter type, config JSON (secrets referenced, not stored),
  location, active.
- `event`: id, device_id, kind (`capture` now; later `audio_clip`, `reading`, …),
  occurred_at, occurred_at_source, payload JSON, created_at. Every capture is an event.
- *(Reserved, not built)* `sensor_reading`: device_id, metric, value, unit,
  occurred_at. Indexed on (device_id, metric, occurred_at) so readings can be joined
  with encounters by time.

**Media:**
- `media`: id, event_id, sha256 (unique), kind (image|video), original_path,
  original_name, mime, size, width/height/duration, metadata JSON, status, error,
  `has_person`, `suppress_alerts`, `active_detection_run_id`,
  `active_classification_run_id`.
- `frame`: id, media_id, index, time_offset, path. Frames are derived from videos; for
  an image, the frame is the photo itself.

**Predictions** (never overwritten; reprocessing adds rows):
- `model`: id, name, version, task (detection|classification|tracking|analysis),
  weights hash, params JSON.
- `inference_run`: id, model_id, started_at, finished_at, scope, status. Used for
  provenance and batch tracking only.
- **Active predictions are resolved per media item**, not by one global setting. A
  media item's `active_*_run_id` pointers are flipped atomically **only when that
  item's reprocessing cascade completes**. Partial or scoped reprocessing never hides
  untouched history or shows half-finished results. Live ingest uses the current
  default models.
- `detection`: id, run_id, frame_id, category (animal|person|vehicle), confidence, bbox
  (normalized x,y,w,h), verification_status.
- `classification`: id, run_id, detection_id, and the raw label string.
  - Parsed into indexed columns: `taxon_class`, `taxon_order`, `taxon_family`,
    `taxon_genus`, `taxon_species` and `common_name`.
  - Also: score, `source` (from the ensemble), rollup level, raw top-k JSON,
    is_uncertain, the location filter used, and verification_status.
  - Search and filters work at any taxonomic level: "squirrels" →
    `taxon_family='sciuridae'`, "birds" → `taxon_class='aves'`.
- `track`: id, run_id, device_id, start, end, species label (or `pending`),
  confidence, verification_status, plus a `track_detection` link table.
- `analysis`: id, run_id, encounter_id, text, frames used (JSON).

So every prediction carries:
- model name and version (via run → model)
- confidence
- a bbox where applicable
- its source frame and media
- a timestamp (the frame time)
- a **verification_status** of `unverified | confirmed | corrected | rejected`

**Higher-level:**
- `encounter`: id, device_id, start, end, effective species list with counts (species
  may be `pending`), best frame, status.
- `individual` (**experimental**): id, species, nickname, notes, plus an
  `individual_track` link set by manual tagging only.
- `correction`: id, target type (detection|classification|track|encounter), target id,
  action (confirm, reject or relabel) with the corrected label, note, created_at.
  - The displayed label is the latest correction, else the active prediction.
  - Encounter-level corrections override lower-level ones.
  - Encounter corrections also store `(device_id, window_start, window_end)`. If
    reprocessing or a full regrouping rebuilds encounter rows, the correction is
    re-attached to whichever encounter overlaps its window, never orphaned.
- `job`, `worker` (heartbeats), `alert` (outbox: status, attempts, error), `backup`
  (when, where, size, verified).

**Uncertain** means one of: the label was rolled up above species level, the score is
below a threshold (default 0.5), or the final label is `animal`, `blank` or `unknown`
even though an animal was detected. It's shown as "Uncertain (top guess: X, 41%)".
**Pending** (not yet classified) is shown separately from uncertain.

### 7.5 Camera adapters

The `CameraAdapter` interface has `discover()` (returns candidate items),
`is_complete(item)`, `fetch(item, dest)`, `ack(item)` and `healthcheck()`. It doesn't
depend on any camera brand.
- **LocalFolderAdapter** (v1): watches or polls a directory. Also the bulk CLI
  `observatory import <folder> [--device <name>]`; bulk imports never alert.
- **FTP receive mode** (Phase 4, **primary camera path**): a small LAN-only FTP/FTPS
  server sidecar (pyftpdlib) in Compose that the camera pushes into.
  - **Atomic completion:** uploads land in `inbox/.incoming/`. Only when the transfer
    completes (pyftpdlib's `on_file_received`) is the file `os.rename()`d into
    `inbox/ready/`, which is what LocalFolderAdapter watches. Partial files are
    deleted in `on_incomplete_file_received`. This replaces size/mtime guessing for
    FTP.
  - **Passive mode in Docker:** run the sidecar with `network_mode: host` on the Pi,
    or set its masquerade address to the Pi's LAN IP. Otherwise passive-mode replies
    advertise a container IP and the camera hangs.
  - **Disk floor:** below the hard floor the sidecar rejects uploads (`452 Insufficient
    storage`). The camera keeps clips on its own card and retries.
  - User, password, port and passive port range are configurable.
  - No assumptions about Reolink file naming or layout.
- **FtpPullAdapter** (optional, later): polls a remote FTP server such as a NAS or
  Home Hub. Interface and docs only unless it's needed.
- **RtspAdapter**: interface stub and docs only, for future mains-powered cameras.

### 7.6 Natural-language search

- **Facts → structured queries.** A fixed matcher maps questions to fixed,
  parameterized queries:
  - which species have been seen
  - sightings of X, with date ranges
  - activity by hour or day
  - rarest and most common species
  - when X was last seen
  - counts, by encounter, never by frame
- **Behavior and unusual questions → optional LLM**, off by default.
  - The LLM never sees the raw database. The edge retrieves candidate encounters and
    frames by structured query and passes only those, plus any stored `analysis` text.
  - The model must cite encounter or media IDs. Any answer without valid citations is
    discarded with "Couldn't answer that from the recorded data."
- `LLMProvider` interface. The first provider is **Ollama**: free and local on the
  Mac, so it runs through the AI worker.
  - A cloud provider can be added with an explicit API key.
  - When no LLM is configured or it can't be reached, the UI says "AI analysis
    unavailable" and factual search still works.
- Every answer shows links or thumbnails for the source images and videos.

### 7.7 Alerts

- Alerts go through ntfy (free, phone app, no account), using outbound HTTPS only.
- Alerts are queued by the edge as soon as an encounter forms after detection (§7.3
  step 5). They never wait for species classification.
- An alert **outbox** table means alerts queued during a network outage are sent when
  it recovers, and marked stale if very late.
- One alert per encounter, with optional quiet hours.
- A daily heartbeat alert ("Observatory OK: 12 captures, disk 41%").
- Failure alerts for disk over threshold, a worker offline for more than N hours,
  failing backups, ingest errors and quarantined files, so problems surface between
  visits.

### 7.8 Reliability and remote management

- **Startup:** Docker is enabled at boot, and Compose services use
  `restart: unless-stopped`. An install script sets this up on Raspberry Pi OS.
- **Network interruptions:** workers and ntfy sends retry with exponential backoff.
  Ingest, detection, tracking, encounters and alert queuing are all local to the Pi,
  so they keep working offline, and classify jobs wait.
- **Disk limits and retention:** a configurable quota on the media volume. Cleanup
  happens in this order:
  1. Delete derived frames and thumbnails, which can be regenerated.
  2. Delete empty and person-only originals older than N days.
  3. Delete the oldest unverified animal media beyond a high watermark.

  Media with corrections, confirmed predictions or tagged individuals is never deleted
  unless explicitly allowed. At a hard floor, ingest pauses and the FTP receiver
  rejects uploads (with an alert), rather than risk corrupting the database.
- **microSD care:** SQLite in WAL mode with sensible checkpointing, size-capped and
  rotated logs, and an optional USB SSD path for media and the database.
- **Structured logs:** JSON lines with component, event and ids, rotated.
- **Health:** `/health` (liveness) and `/health/details`, which reports:
  - database OK
  - disk %
  - queue depths
  - worker heartbeats
  - last ingest
  - last backup
  - alert outbox backlog
  - quarantine count

  Docker health checks use these endpoints, and the dashboard's Status page shows
  them.
- **Remote access:** **Tailscale** is installed on the Pi itself. The dashboard, API
  and FTP bind only to localhost, the LAN and the tailnet. Nothing is port-forwarded,
  and the docs explain this.
- **Config and secrets:** `.env` holds config. Secrets live in files with restricted
  permissions (Docker secrets in Compose). `.env.example` is committed; real values
  never are.
- **Backups:**
  - Nightly SQLite online backup (the `.backup` API) to a separate directory, or a
    USB thumb drive on the Pi if present.
  - Each backup is integrity-checked and rotated (for example 7 daily + 4 weekly).
  - The restore procedure is documented and tested in CI or locally.
  - **The off-device copy is built, not just documented**, because a dying microSD
    takes local backups with it. `observatory backup pull` runs on the Mac (manually or
    via launchd) and fetches the latest verified backup over Tailscale.
- **Failure states:** every degraded mode has an explicit status in the dashboard and,
  where useful, an alert. That covers:
  - AI worker offline (species pending)
  - cloud AI unavailable
  - disk near full
  - camera silent for N hours
  - backups failing
  - files quarantined

### 7.9 Dashboard (Next.js)

- **Home:** recent encounters, quick stats and a system status badge.
- **Gallery:** images and videos, filtered by species, date, device, category,
  uncertain-only, pending-only and verification status.
- **Encounter detail:** frames with box overlays, tracks, top classification guesses
  and model versions. Also correction, confirm and reject controls, an optional
  individual tag, and optional analysis text.
- **Activity:** sightings by hour of day and by day, per species, counted by encounter.
- **Ask:** the search box, with source links.
- **Status:** health details, queues, workers, benchmarks, backups, alerts and
  quarantine.
- **Models:** runs, per-media active runs, and a button to trigger reprocessing.

## 8. Phases and gates

**Vertical slice first** (owner's priority): import image → detect animal → identify
species → save event → display in dashboard. Build that thin path end to end before
broadening any feature. When it works, deliver:
- a brief architecture summary
- run instructions
- example inference results
- known limitations
- Raspberry Pi deployment instructions
- next recommended tasks

0. **Vertical slice.** A minimal edge (folder import, SQLite, jobs), one native worker
   running detect → classify → ensemble in-process, and a bare Next.js page listing
   encounters with boxes.
   - Behavior is minimal, but it uses the **real schema** from §7.4 from day one
     (`device`, `event`, `media`, `frame`, `model`, `inference_run`, `detection`,
     `classification`, `track`, `encounter`, `job`), so moving on to Phase 1 only adds
     and never rewrites.
   - **Gate:** a real public camera-trap image shows up in the dashboard with the
     correct box and a species label from SpeciesNet, plus Mac benchmark numbers (time
     and peak memory per stage).
1. **Dataset and inference hardening.**
   - Repo and project structure, and the uv environment.
   - A sample-data script that pulls a few hundred real images from LILA (preferring
     Northeast US species where available) plus 1–2 short public clips.
   - LocalFolderAdapter and CLI import, the edge database and jobs, and the detect and
     classify workers, including frame upload and download.
   - Edge geometric tracking and encounter grouping right after detect, with species
     `pending` until classified.
   - Predictions with full provenance, and handling of empty, person, uncertain and
     error cases.
   - A **benchmark script** (time and peak memory per model).
   - **Gate:** the test cases you required in §9 pass against real sample images.
2. **Dashboard.** The pages in §7.9 on real data, corrections, and the same-origin
   proxy.
3. **Tracking refinement and NL search.** Encounter counts and merge rules, and
   structured search with tests checked against direct SQL. Also the LLM provider
   interface and Ollama, off by default.
4. **Deployment readiness.**
   - Compose profiles and ARM64 images.
   - The FTP receiver (atomic completion, passive mode, disk floor), quarantine, and
     tests for duplicate imports and interrupted uploads.
   - Retention, backups, restore and `backup pull`.
   - Health endpoints and structured logs.
   - Alerts, outbox and the daily heartbeat.
   - Tailscale and secrets docs, and a CPU/RAM requirements doc.
   - The reprocessing UI with per-media active runs.
   - A "can't test without hardware" doc.

## 9. Testing

**Required by the owner**, using real images where possible:
- duplicate imports
- empty images
- incorrect classifications (the correction flow)
- interrupted transfers
- unknown species
- multiple animals in one image
- model failures
- database persistence (survives restart)

Also:
- **Docs:** how to run on **macOS** and on **ARM64 Linux**.
- **Unit tests:**
  - ingest duplicates, partial uploads and quarantine
  - timestamps and frame sampling
  - geometric tracking, and encounter grouping, counting and merging
  - alerts firing with the AI worker offline, one per encounter
  - species updating in place when classification arrives late
  - uncertainty rules
  - correction precedence, and corrections surviving reprocessing and regrouping
  - per-media active-run flipping during partial reprocessing
  - job leases, claim tokens (409 on stale results), retries and offline workers
  - the retention policy and disk floor
  - question matching
  - the citation check on LLM answers
- **Integration:** the real models on a few downloaded sample images (not committed).
- **Compose smoke test** on arm64 (Mac), including killing and restarting a worker,
  restarting the edge, and an FTP upload into the receiver.
- **Backup → restore** round-trip test, including `backup pull`.
- **Can't be tested without the hardware (to document):**
  - Argus FTP support and file behavior
  - real capture frequency and bursts
  - Wi-Fi reliability
  - Pi 400 timings, memory headroom and heat throttling
  - microSD endurance
  - night/IR quality
  - real alert latency
  - Tailscale behavior on your parents' network

## 10. Calls made during design (owner to check)

- **AI worker on the Pi has no schedule.** When it's on, it runs whenever there's work,
  with capped torch threads and low CPU priority, so detection and alerts stay
  responsive. If benchmarks show both models can't fit in 4 GB, the documented answer
  is "run the AI worker on the Mac."
- **Bulk and CLI imports never alert;** only live adapters do.
- **Video status** rolls up from its frames: if any frame has an animal, the video
  counts as an animal sighting.
- **Encounter-level corrections** override lower-level ones and survive reprocessing.
- **Model weights** download on first run into a persistent volume, not built into the
  images.
- **Location filter:** sample-data runs use each dataset's own location; production
  uses `USA` / `NJ`.
- **LLM features** are off by default. Ollama is the first provider; cloud providers
  only with an explicit key.
- **Individual-animal recognition:** schema and manual tagging only.
- **Naming:** repo `wildlife-observatory`, CLI command `observatory`.
- **From the first external review, adopted:**
  - the three-stage SpeciesNet API, in-process (verified against the 5.0.6 source)
  - the FTP receiver as the primary camera path
  - a single combined worker on the Pi, with `mem_limit`s
  - media-scoped jobs
  - `CAMERA_TIMEZONE`
  - `claim_token` and heartbeat
  - taxonomy columns
  - "contains person" privacy
- **From the first external review, not yet confirmed:** its RAM figures are estimates
  until benchmarked, and its claim that the Argus Solar pushes over FTP is unverified
  until the hardware arrives.
- **From the second external review, adopted:**
  - geometric tracking, encounter grouping and alerts run in the edge right after
    detection, so nothing waits on the AI worker
  - active predictions are resolved per media item
  - frame upload and download endpoints
  - atomic FTP completion, plus passive-mode and disk-floor handling, plus quarantine
  - the Next.js same-origin proxy
  - a built `backup pull` command
  - encounter corrections store their time window
  - the real schema from Phase 0
- **AGENTS.md** is written after the implementation plan is approved.

## 11. Builder's discretion

Library choices within the stack (SQLAlchemy or raw sqlite3, charting, Tailwind),
folder layout within each component, tracker algorithm details, default thresholds and
sampling rates, retention numbers, and the dashboard's visual design.
