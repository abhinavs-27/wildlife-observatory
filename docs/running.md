# Running

## Requirements

- Python **3.12** via [uv](https://docs.astral.sh/uv/). SpeciesNet 5.0.6 needs `<3.15`, so a
  newer system Python won't work. `uv` downloads 3.12 for you.
- Node 20+ for the dashboard.
- `ffmpeg`/`ffprobe` for video metadata (optional on the edge; OpenCV is used as a fallback).
- Docker (optional) for the Compose setup.

## macOS (development)

```bash
cd edge   && uv sync --extra dev && uv run pytest        # 49 tests
cd worker && uv sync --extra dev && uv run pytest        # 5 tests (fake models)

export DATA_DIR=$PWD/data
(cd edge && uv run observatory serve --port 8000)         # API + background loops
python3 -I scripts/fetch_samples.py --out samples         # real NACTI images
(cd edge && uv run observatory import ../samples/images)
(cd worker && uv run observatory-worker --kinds detect,classify)   # native = Apple GPU (MPS)
(cd web && npm install && EDGE_INTERNAL_URL=http://localhost:8000 npm run dev -- -p 3100)
```

The worker downloads model weights (~250 MB) from Kaggle on first start and caches them under
`~/.cache/kagglehub`.

Useful commands:

```bash
uv run observatory ask "What animals have visited?"
uv run observatory health          # same JSON as /api/health/details
uv run observatory backup          # verified SQLite backup into $DATA_DIR/backups
uv run observatory restore <file>  # stop the edge first
python3 -I scripts/evaluate.py --db data/observatory.sqlite --samples samples
(cd worker && uv run python ../scripts/benchmark.py --images ../samples/images --n 20 --device cpu --threads 4)
```

## ARM64 Linux (Raspberry Pi OS 64-bit, or any Linux box)

Natively:

```bash
sudo apt-get install -y ffmpeg libgl1 libglib2.0-0
curl -LsSf https://astral.sh/uv/install.sh | sh
cd edge && uv sync && DATA_DIR=/srv/observatory uv run observatory serve --host 0.0.0.0
cd worker && uv sync && uv run observatory-worker --edge-url http://localhost:8000 \
    --token "$WORKER_TOKEN" --kinds detect --device cpu --threads 3
```

On the Pi, Docker Compose is recommended instead (next section, and
[pi-deployment.md](pi-deployment.md)).

## Docker Compose

```bash
cp .env.example .env                  # set WORKER_TOKEN, NTFY_TOPIC
echo "a-long-random-password" > secrets/ftp_password.txt
docker compose --profile dev up --build   # edge :8000, web :3000, worker (CPU) on this machine
```

Profiles:
- **(none)**: edge + web.
- **dev**: adds a worker. On a Mac, the worker in Docker is CPU-only, so prefer the native worker.
- **pi**: adds the worker and the FTP receiver (host networking).

Every service has `restart: unless-stopped`, a health check (edge and web), capped logs and a
memory limit.
