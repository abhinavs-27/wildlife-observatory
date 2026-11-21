# AGENTS.md

Guidance for AI coding agents (and humans) working in this repo.

## What this is

A backyard wildlife observatory: a battery Reolink Argus Solar camera pushes motion photos/clips
to a Raspberry Pi 400 (4 GB, ARM64) in New Jersey. The Pi ingests them, detects animals with
MegaDetector, groups detections into tracks and encounters, sends phone alerts (ntfy), and serves
a dashboard. SpeciesNet species classification runs on the Pi if it fits, or on a Mac over Tailscale.

- Design (source of truth): `docs/superpowers/specs/2026-11-21-wildlife-observatory-design.md`
- Implementation plan: `docs/superpowers/plans/2026-11-21-wildlife-observatory.md`

## Layout

| Path | What | Runtime |
|---|---|---|
| `edge/` | FastAPI + SQLite. Ingest, job queue, tracking, encounters, alerts, backups, search, dashboard API. **No torch.** | Pi (Docker) / Mac |
| `worker/` | Inference worker. SpeciesNet 5.0.6 in-process (detector, classifier, ensemble). Talks to edge over HTTP only. | Pi (Docker) or Mac (native, MPS) |
| `web/` | Next.js dashboard. Proxies `/api`, `/media`, `/frames` to the edge (same origin). | Pi (Docker) / Mac |
| `scripts/` | Sample-data fetcher, benchmark, FTP receiver. | |
| `docs/` | Running, deployment, benchmarks, limitations. | |

## Commands

```bash
# Edge
cd edge && uv sync --extra dev && uv run pytest
uv run observatory serve                 # API on :8000 (DATA_DIR=./data by default)
uv run observatory import ../samples     # bulk import (never alerts)

# Worker (Python 3.12 only — the Mac's default python3 is too new for speciesnet)
cd worker && uv sync --extra dev && uv run pytest
uv run observatory-worker --edge-url http://localhost:8000 --token dev-token --kinds detect,classify

# Web
cd web && npm install && npm run dev     # :3000, EDGE_INTERNAL_URL=http://localhost:8000

# Everything in Docker
docker compose --profile dev up --build
```

## Invariants (do not break)

- **Only the edge opens SQLite.** Workers use the HTTP job protocol (`/jobs/claim`, `/heartbeat`,
  `/frames`, `/result`, `/fail`) with a `claim_token`; stale tokens get 409.
- **Never overwrite predictions.** Corrections are separate rows; reprocessing adds new runs and
  flips per-media `active_*_run_id` only when that item finishes.
- **Never invent observations.** Search answers come from SQL and cite encounter/media IDs.
  Unknown questions → "I don't understand that yet".
- **Count encounters, not frames.**
- **Alerts don't wait on classification.** Tracking + encounter grouping + alert queueing happen in
  the edge right after `detect`. One alert per encounter. Bulk imports and old captures never alert.
- **Privacy:** media containing a person is never sent as an image to ntfy, never a best frame,
  hidden from the default gallery.
- **Time:** store UTC ISO-8601 (`Z`). Naive EXIF is interpreted in `CAMERA_TIMEZONE`
  (`America/New_York`). Hour-of-day stats use `CAMERA_TIMEZONE`.
- **SpeciesNet in-process only** (`SpeciesNetDetector`/`SpeciesNetClassifier`/`SpeciesNetEnsemble`,
  loaded once). Don't shell out per job. Don't install the separate `megadetector` package.
- Python `>=3.12,<3.13`; dependencies managed with `uv`.
- No paid services by default; nothing exposed to the public internet.
- Images for the Pi are built on the Mac (`docker buildx --platform linux/arm64`), never on the Pi.

## Workflow

- TDD: write the failing test first; keep tests fast (fake models in unit tests; real models only
  in the explicitly marked integration test).
- Small focused files; one responsibility each.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Update the design doc if you change architecture; update `docs/` when commands change.
- Hardware-dependent behavior (camera FTP, Pi timings) must be marked as unverified until tested
  on the real device — see `docs/hardware-untestable.md`.
