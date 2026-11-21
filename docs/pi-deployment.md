# Raspberry Pi 400 deployment

The Pi is a low-power, always-on edge server at your parents' house. It runs the **edge**,
**dashboard**, **FTP receiver** and a **detection worker**. Species classification runs on
your Mac whenever it's online. The Pi can do it too if benchmarks say it fits; see
[benchmarks.md](benchmarks.md).

## 1. Prepare the Pi (once, while you're there)

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In the imager settings,
   set the hostname to `observatory`, enable SSH with your key, and add the Wi-Fi details.
2. Optional but recommended: put the data on a USB SSD and mount it at `/srv/observatory`.
   microSD cards wear out.
3. On the Pi:

```bash
sudo apt-get update && sudo apt-get -y upgrade
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER
sudo systemctl enable docker                # containers come back after reboot
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --ssh
sudo mkdir -p /srv/observatory && sudo chown $USER /srv/observatory
git clone https://github.com/abhinavs-27/wildlife-observatory ~/wildlife-observatory
```

4. Turn on unattended security updates (`sudo apt-get install unattended-upgrades`).

## 2. Build images on the Mac (never on the Pi)

```bash
docker buildx create --use --name obs 2>/dev/null || true
for svc in edge worker web; do
  docker buildx build --platform linux/arm64 -t observatory-$svc:latest --output type=docker,dest=/tmp/$svc.tar ./$svc
done
scp /tmp/{edge,worker,web}.tar observatory:/tmp/          # over Tailscale
ssh observatory 'for f in /tmp/{edge,worker,web}.tar; do docker load -i $f; done'
```

You could push to a registry instead and set `REGISTRY=` in `.env`.

## 3. Configure and start

```bash
cd ~/wildlife-observatory
cp .env.example .env
#   WORKER_TOKEN=$(openssl rand -hex 24)
#   NTFY_TOPIC=<something unguessable>; subscribe to it in the ntfy phone app
#   BIND_ADDR=0.0.0.0        (LAN + Tailscale; do NOT port-forward on the router)
#   DATA_PATH=/srv/observatory
openssl rand -base64 18 > secrets/ftp_password.txt
docker compose --profile pi up -d
docker compose ps                     # edge/web should become "healthy"
```

The dashboard is at `http://observatory:3000` from any device on your tailnet, including your
phone with the Tailscale app.

## 4. Point the camera at the FTP receiver (to verify on real hardware)

In the Reolink app: **Settings → FTP**.
- Server: the Pi's LAN IP. Port: `2121`. User: `camera`. Password: from `secrets/ftp_password.txt`.
- Passive mode **on**. Upload: photos and/or videos on motion.

Uploads land in `data/inbox/.incoming/`. They're moved to `inbox/ready/` only when complete, and
then ingested. If the camera hangs on upload, set `FTP_MASQUERADE_ADDRESS` to the Pi's LAN IP.
**The camera's actual FTP behavior is unverified.** See [hardware-untestable.md](hardware-untestable.md).

## 5. Run species classification on the Mac

```bash
cd worker
uv run observatory-worker --edge-url http://observatory:8000 --token "$WORKER_TOKEN" --kinds classify
```

Until the Mac connects, sightings show "Identifying…". To start the worker automatically, use a
launchd agent (example in [next-steps.md](next-steps.md)). To classify on the Pi instead, set
`WORKER_KINDS=detect,classify` and raise `WORKER_MEM_LIMIT`, but only after checking the Pi
benchmark.

## 6. Backups

- The edge makes a verified SQLite backup nightly at 03:00 into `$DATA_PATH/backups` and keeps 7.
  Set `BACKUP_DIR` to a USB stick to survive SD-card death.
- Copy backups off the Pi from the Mac (manually or on a schedule):

```bash
cd edge && uv run observatory backup-pull --edge-url http://observatory:8000 --token "$WORKER_TOKEN"
```

- Restore: `docker compose stop edge`, then
  `docker compose run --rm edge observatory restore /data/backups/<file>.sqlite`, then start it.

## 7. What keeps it alive for a month

- Docker starts at boot, and every container restarts on failure.
- Workers retry the edge with backoff, and ingest works offline.
- Alerts queue in an outbox and send when the network returns.
- At `DISK_FLOOR_PCT` (95%), ingest pauses and the FTP receiver refuses uploads with `452`, so the
  camera keeps its clips. A failure alert is sent.
- You get a daily "Observatory OK" push at 08:00, plus pushes when something breaks (worker
  offline with jobs waiting, disk, backups, quarantined files).
- Health: `curl http://observatory:8000/api/health/details`, or the dashboard's **System** page.
- Logs are JSON lines, capped at 3 × 10 MB per container: `docker compose logs -f edge`.

## CPU and memory budget (Pi 400, 4 GB)

| Service | Limit | Measured on Mac (proxy) |
|---|---|---|
| edge | 512 MB | ~25 MB RSS (idle, measured) |
| web | 384 MB | ~70 MB RSS (measured, `next start`) |
| worker, detect only | 1.8 GB | ~0.9 GB model + runtime (measured: detector load added 914 MB) |
| worker, detect + classify | needs ~2.5 GB | 2.4 GB peak on CPU |
| OS + Docker | — | ~0.5–0.7 GB (estimate) |

Detect-only fits comfortably. Running both models on the Pi is borderline and needs a Pi
benchmark first. The Mac measured 0.9 s/image for detection on 4 CPU threads. The Pi 400's
Cortex-A72 is roughly 5–8× slower, so expect about 5–8 s per photo. That's an estimate until
measured: run `scripts/benchmark.py` inside the worker container on the Pi.
