# Architecture

The full design is in [the design doc](superpowers/specs/2026-11-21-wildlife-observatory-design.md).
This page is a summary of what's actually built.

```
 camera ─FTP push─▶ ftp receiver ─▶ data/inbox/ready ─▶ edge ingest ─▶ data/originals (immutable)
                                                            │
             ┌──────────────────────────── EDGE (FastAPI, SQLite WAL, no torch) ─────────────┐
             │ jobs + leases + claim tokens · geometric tracker · encounter grouping          │
             │ alert outbox → ntfy · backups · health · structured search · dashboard API     │
             └──────▲─────────────────────────────────▲───────────────────────────▲──────────┘
                    │ HTTP: claim/frames/result        │ HTTP (proxied by Next.js)  │ HTTPS
        worker (detect)  on Pi, CPU          web dashboard (Next.js)            ntfy.sh
        worker (classify) on Mac, MPS or Pi
```

## Components

| Component | Code | What it does |
|---|---|---|
| Edge | `edge/src/observatory_edge/` | The only process that opens SQLite. It handles ingest (`ingest.py`, `adapters.py`), the job queue (`jobs.py`), worker results (`results.py`), tracking and encounters (`tracking.py`), alerts (`alerts.py`), corrections (`corrections.py`), search (`search.py`), read models (`queries.py`), backups (`backup.py`), the FTP receiver (`ftp_receiver.py`), background loops (`background.py`) and the API (`api.py`). |
| Worker | `worker/src/observatory_worker/` | Loads `SpeciesNetDetector`, `SpeciesNetClassifier` and `SpeciesNetEnsemble` once (`models.py`), then claims jobs over HTTP (`client.py`, `runner.py`). For videos, it samples frames in memory (`frames.py`) and uploads only the frames it keeps. |
| Web | `web/` | Server components fetch the edge directly. The browser only talks to the dashboard's own origin; `/api`, `/media` and `/frames` are rewritten to the edge. |

## Pipeline

1. **Ingest.** A file arrives, either from a CLI import or from the inbox written by the FTP
   receiver. The edge hashes it with SHA-256, so the same bytes are only ever stored once. The
   original is copied unchanged to `originals/YYYY/MM/<sha>.<ext>`, and the edge records the
   device, a `capture` event, the media row, frame 0 for images, and a `detect` job. Capture time
   comes from EXIF (read in `CAMERA_TIMEZONE`), then the video container's time (UTC), then file
   mtime, and the source used is recorded. A corrupt file is retried and quarantined after 3
   failures.
2. **Detect** (worker). MegaDetector v5a runs on the image, or on video frames sampled at 1 fps.
   For videos, frames with detections plus one poster frame are uploaded via `/jobs/{id}/frames`.
3. **Track, group and alert** (edge, straight after detect, with no AI worker needed).
   - The greedy IoU/centroid tracker links detections across frames and consecutive photos.
   - Tracks within 2 minutes of each other on the same device form one encounter.
   - Late or out-of-order files trigger a rebuild of that time window. Merges keep the earliest
     encounter id, and alerts and corrections are moved to it.
   - One alert is queued per new live encounter. Bulk imports, captures older than 15 minutes,
     and detections below `ALERT_THRESHOLD` never alert. Media containing a person never sends
     its image.
4. **Classify** (worker, whenever one is online). The SpeciesNet classifier runs on each animal
   crop, then the ensemble applies the `USA`/`NJ` geofence and taxonomic rollup.
   - The edge parses the 7-part label into taxonomy columns and marks a result uncertain if it's
     rolled up above species, scores under 0.5, or is `animal`/`blank`/`unknown`.
   - It then re-votes the species of each track and updates the encounter in place. No second
     alert is sent.

## Job protocol

`POST /jobs/claim` → job + `claim_token` (or 204). `POST /jobs/{id}/heartbeat` extends the lease.
`POST /jobs/{id}/frames` uploads video frames. `POST /jobs/{id}/result` / `fail`. A stale token gets
**409** and writes nothing. Expired leases are requeued. Failures retry with backoff up to 3 times.
Workers authenticate with `Authorization: Bearer $WORKER_TOKEN`.

## Data model

See `edge/src/observatory_edge/schema.sql`. Highlights:
- **Generic core:** `device` and `event` tables are ready for future sensors (`sensor_reading` is
  reserved in the design).
- **Predictions are never overwritten.** Each one links to a `model` and an `inference_run`, and
  media rows carry `active_detection_run_id` / `active_classification_run_id`.
- **Corrections** are separate rows. Encounter corrections store their time window, so they
  survive regrouping.
- **Counts** are the most animals of one species visible at the same time in an encounter, never
  the number of frames.
