# What can't be tested without the real hardware

Everything else was tested on a Mac with real NACTI camera-trap images. These items need the
camera and the Pi:

| Item | What's built | What to verify when the hardware arrives |
|---|---|---|
| Argus Solar FTP upload | LAN FTP receiver (pyftpdlib) with atomic completion, `452` disk floor, passive ports, masquerade address. Tested with Python's `ftplib`. | Does this model/firmware support FTP upload standalone (no Home Hub)? FTP vs FTPS? Passive mode? Folder layout and file names? Does it send a JPG and an MP4 per trigger? How does it retry after a `452`? |
| Capture timestamps | EXIF (in `CAMERA_TIMEZONE`) → MP4 `creation_time` (UTC) → mtime | Does Reolink write EXIF `DateTimeOriginal`? Is MP4 `creation_time` UTC or local? Is the camera clock synced? |
| Burst and clip cadence | Encounter gap 120 s, track gap 30 s, video sampled at 1 fps / max 30 frames | Tune to real clip lengths and trigger frequency. |
| Pi 400 inference speed and memory | `scripts/benchmark.py`; `mem_limit`s; detect-only by default on the Pi | Run the benchmark in the worker container on the Pi. Decide whether classification can also run there. |
| Thermal throttling | `TORCH_THREADS=3`, `cpus: 3` | Watch `vcgencmd measure_temp` during a busy night. |
| microSD endurance | WAL, capped logs, no annotated images written | Prefer a USB SSD; check wear after a month. |
| Night/IR images | MegaDetector and SpeciesNet handle IR well on NACTI night shots | Check real IR photos from this camera and site. |
| Alert latency | Outbox loop runs every 10 s | Measure motion → upload → push time end to end. |
| Wi-Fi / Tailscale at the parents' house | Retry and backoff everywhere; Tailscale docs | Confirm the tailnet reaches the Pi through their router. |
| Unattended month | Restart policies, health checks, daily heartbeat push, failure pushes | Do a 72-hour soak test before leaving it. |
