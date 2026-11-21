#!/usr/bin/env python3
"""Download a small set of real, labelled camera-trap images from LILA's NACTI dataset.

NACTI (North American Camera Trap Images) is public: https://lila.science/datasets/nacti
Licence: Community Data License Agreement (permissive variant). Images are not committed.

Usage:
  python3 scripts/fetch_samples.py --out samples --per-species 4
Writes images to <out>/images/<species>/<file>.jpg, a manifest CSV with ground-truth labels,
and (if ffmpeg is installed) a short clip assembled from one real image burst.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

BASE = "https://storage.googleapis.com/public-datasets-lila"
META = f"{BASE}/nacti/nacti_metadata.csv.zip"
IMG = f"{BASE}/nacti-unzipped/"

# Species that also occur in New Jersey (plus empties/vehicles to exercise those paths).
TARGETS = [
    "raccoon", "eastern gray squirrel", "american black bear", "bobcat", "coyote",
    "striped skunk", "gray fox", "red fox", "wild turkey", "virginia opossum",
    "unidentified deer", "unidentified rabbit", "unidentified bird", "domestic dog",
    "empty", "vehicle",
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wildlife-observatory-samples"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def load_meta(cache: Path) -> list[dict]:
    csv_path = cache / "nacti_metadata.csv"
    if not csv_path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print("downloading NACTI metadata (~30 MB)...", file=sys.stderr)
        with zipfile.ZipFile(io.BytesIO(fetch(META))) as z:
            name = next(n for n in z.namelist() if n.endswith(".csv"))
            with z.open(name) as src, open(csv_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("samples"))
    ap.add_argument("--per-species", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rows = load_meta(args.out / "_meta")
    by_species: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["common_name"] in TARGETS:
            by_species[r["common_name"]][r["seq_no"]].append(r)

    rng = random.Random(args.seed)
    manifest = []
    img_dir = args.out / "images"
    for sp in TARGETS:
        seqs = list(by_species[sp].values())
        rng.shuffle(seqs)
        for seq in seqs[: args.per_species]:
            r = sorted(seq, key=lambda x: x["filename"])[0]
            dest = img_dir / sp.replace(" ", "_") / Path(r["filename"]).name
            if not dest.exists():
                try:
                    data = fetch(IMG + r["filename"])
                except Exception as e:
                    print(f"skip {r['filename']}: {e}", file=sys.stderr)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            manifest.append({"path": str(dest.relative_to(args.out)), "label": sp,
                             "study": r["study"], "source": IMG + r["filename"]})
            print(f"{sp:24s} {dest.name}")

    # NACTI images carry no capture time in EXIF, so ingestion would fall back to the download
    # time and lump every sample into one "visit". For demo/test data only, we stamp each file's
    # mtime with a SYNTHETIC time spread over the last 30 days (recorded in the manifest as
    # `synthetic_time`). Real camera uploads use their own EXIF/container timestamps.
    import os
    import time as _time
    now = _time.time()
    for row in manifest:
        p = args.out / row["path"]
        nocturnal = row["label"] in {"raccoon", "striped skunk", "virginia opossum", "red fox",
                                     "gray fox", "coyote", "bobcat"}
        day = rng.randint(1, 30)
        hour = rng.choice([21, 22, 23, 0, 1, 2, 3, 4, 5]) if nocturnal else rng.randint(6, 19)
        ts = now - day * 86400
        lt = _time.localtime(ts)
        ts = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, rng.randint(0, 59),
                           rng.randint(0, 59), 0, 0, -1))
        os.utime(p, (ts, ts))
        row["synthetic_time"] = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime(ts))

    with open(args.out / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["path", "label", "study", "source", "synthetic_time"])
        w.writeheader()
        w.writerows(manifest)

    # A short clip built from one real burst (3+ consecutive images of the same animal).
    if shutil.which("ffmpeg"):
        by_loc: dict[str, list[dict]] = defaultdict(list)
        for seq in by_species["raccoon"].values():
            for r in seq:
                by_loc[r["location"]].append(r)
        bursts = [s for s in by_loc.values() if len(s) >= 4]
        if bursts:
            burst = sorted(rng.choice(bursts), key=lambda x: x["filename"])[:4]
            tmp = args.out / "_burst"
            tmp.mkdir(parents=True, exist_ok=True)
            for i, r in enumerate(burst):
                (tmp / f"{i:03d}.jpg").write_bytes(fetch(IMG + r["filename"]))
            clip = args.out / "videos" / "raccoon_burst.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "1",
                            "-i", str(tmp / "%03d.jpg"),
                            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                                   "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "10", str(clip)],
                           check=True)
            shutil.rmtree(tmp)
            import os
            import time as _time
            lt = _time.localtime(_time.time() - 2 * 86400)
            ts = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 22, 15, 0, 0, 0, -1))
            os.utime(clip, (ts, ts))  # synthetic demo time (see note above)
            print(f"clip: {clip} (4 real raccoon images from NACTI location {burst[0]['location']})")
    print(f"{len(manifest)} images; manifest at {args.out / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
