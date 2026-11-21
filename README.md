# Wildlife Observatory

A backyard wildlife observatory for a **Reolink Argus Solar** camera and a **Raspberry Pi 400**.
Camera uploads are ingested on the Pi. **MegaDetector** finds animals, people and vehicles.
Detections are linked into tracks and grouped into encounters, and you get a phone alert.
**SpeciesNet** then identifies the species, on the Pi or on a Mac over Tailscale. A Next.js
dashboard shows sightings with bounding boxes, activity by hour and day, manual corrections,
and a search box that answers only from the database.

> Status: MVP built and tested on a Mac against real public camera-trap images (LILA NACTI).
> The Pi and camera hardware haven't arrived, so anything that depends on them is listed in
> [docs/hardware-untestable.md](docs/hardware-untestable.md).

## Quick start (macOS, Apple Silicon)

```bash
# 1. Edge service (Python 3.12 via uv; the system python3 may be too new for SpeciesNet)
cd edge && uv sync --extra dev && uv run pytest
DATA_DIR=../data uv run observatory serve            # http://localhost:8000

# 2. Real sample data (64 labelled NACTI images + 1 short clip, ~30 MB)
python3 -I ../scripts/fetch_samples.py --out ../samples
DATA_DIR=../data uv run observatory import ../samples/images
DATA_DIR=../data uv run observatory import ../samples/videos

# 3. Inference worker, run natively so it can use the Apple GPU (MPS)
cd ../worker && uv sync --extra dev
uv run observatory-worker --edge-url http://localhost:8000 --kinds detect,classify --once

# 4. Dashboard
cd ../web && npm install && EDGE_INTERNAL_URL=http://localhost:8000 npm run dev -- -p 3100
open http://localhost:3100
```

Ask questions from the terminal too: `DATA_DIR=../data uv run observatory ask "When are deer most active?"`

## Docs

| | |
|---|---|
| [Architecture](docs/architecture.md) | Components, data flow, job protocol, data model |
| [Running](docs/running.md) | macOS and ARM64 Linux, Docker Compose, tests |
| [Raspberry Pi deployment](docs/pi-deployment.md) | Build on the Mac, Tailscale, FTP, backups, alerts |
| [Example results](docs/example-results.md) | Inference on real NACTI images vs ground truth |
| [Benchmarks](docs/benchmarks.md) | Load time, per-image time, memory |
| [Limitations](docs/limitations.md) | What's known not to work or is approximate |
| [Untestable without hardware](docs/hardware-untestable.md) | What still needs the real camera and Pi |
| [Next steps](docs/next-steps.md) | Recommended next development tasks |
| [Design](docs/superpowers/specs/2026-11-21-wildlife-observatory-design.md) / [Plan](docs/superpowers/plans/2026-11-21-wildlife-observatory.md) | Source of truth |

## Repo layout

`edge/` FastAPI + SQLite (no torch) · `worker/` SpeciesNet inference worker · `web/` Next.js
dashboard · `scripts/` sample fetcher, benchmark, evaluation · `docs/` · `AGENTS.md` for AI agents.

Sample images come from [LILA NACTI](https://lila.science/datasets/nacti) (Community Data License
Agreement) and are downloaded on demand, not committed.
