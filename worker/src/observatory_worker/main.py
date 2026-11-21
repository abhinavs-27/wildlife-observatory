"""`observatory-worker` entry point."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="observatory-worker")
    ap.add_argument("--edge-url", default=os.environ.get("EDGE_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("WORKER_TOKEN", "dev-token"))
    ap.add_argument("--kinds", default=os.environ.get("WORKER_KINDS", "detect,classify"),
                    help="comma-separated: detect,classify")
    ap.add_argument("--worker-id", default=os.environ.get("WORKER_ID", f"{socket.gethostname()}"))
    ap.add_argument("--model", default=os.environ.get("SPECIESNET_MODEL"))
    ap.add_argument("--threads", type=int, default=int(os.environ.get("TORCH_THREADS", "0")),
                    help="cap torch CPU threads (0 = torch default)")
    ap.add_argument("--video-fps", type=float, default=float(os.environ.get("VIDEO_FPS", "1")))
    ap.add_argument("--video-max-frames", type=int,
                    default=int(os.environ.get("VIDEO_MAX_FRAMES", "30")))
    ap.add_argument("--once", action="store_true", help="drain the queue then exit")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    if args.threads:
        import torch
        torch.set_num_threads(args.threads)

    from .client import EdgeClient
    from .models import SpeciesNetModels
    from .runner import Runner

    models = SpeciesNetModels(args.model, load_detector="detect" in kinds,
                              load_classifier="classify" in kinds)
    logging.info("models loaded on %s: %s", getattr(models, "device", "?"), models.load_times)
    runner = Runner(EdgeClient(args.edge_url, args.token), models, kinds, args.worker_id,
                    args.video_fps, args.video_max_frames)
    if args.once:
        while runner.run_once():
            pass
        return 0
    runner.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
