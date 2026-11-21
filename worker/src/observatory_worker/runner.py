"""Job runner: claim → process → post result, with lease heartbeats."""

from __future__ import annotations

import io
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

import httpx
from PIL import Image

from .client import EdgeClient, StaleClaim
from .frames import jpeg_bytes, sample_video
from .models import Models

log = logging.getLogger("observatory.worker")


def peak_rss_mb() -> float:
    try:
        import psutil
        return round(psutil.Process(os.getpid()).memory_info().rss / 1e6, 1)
    except Exception:
        return 0.0


class _Heartbeat:
    def __init__(self, client: EdgeClient, job: dict, every: float):
        self.client, self.job, self.every = client, job, every
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.wait(self.every):
            try:
                self.client.heartbeat(self.job["job_id"], self.job["claim_token"])
            except Exception as e:
                log.warning("heartbeat failed: %s", e)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.stop.set()


class Runner:
    def __init__(self, client: EdgeClient, models: Models, kinds: list[str], worker_id: str,
                 video_fps: float = 1.0, video_max_frames: int = 30):
        self.client, self.models, self.kinds, self.worker_id = client, models, kinds, worker_id
        self.video_fps, self.video_max_frames = video_fps, video_max_frames

    def capabilities(self) -> dict:
        return {"detector": self.models.detector_info, "classifier": self.models.classifier_info,
                "device": getattr(self.models, "device", "cpu"), "rss_mb": peak_rss_mb()}

    def run_once(self) -> bool:
        job = self.client.claim(self.kinds, self.worker_id, self.capabilities())
        if not job:
            return False
        started = time.perf_counter()
        try:
            with _Heartbeat(self.client, job, max(15.0, job.get("lease_s", 600) / 4)):
                if job["kind"] == "detect":
                    payload = self.process_detect(job)
                elif job["kind"] == "classify":
                    payload = self.process_classify(job)
                else:
                    raise ValueError(f"unsupported job kind {job['kind']}")
            payload["claim_token"] = job["claim_token"]
            payload.setdefault("timings", {})["total_s"] = round(time.perf_counter() - started, 3)
            payload["peak_rss_mb"] = peak_rss_mb()
            self.client.result(job["job_id"], payload)
            log.info("job %s %s media %s done in %.2fs", job["job_id"], job["kind"],
                     job["media"]["id"], time.perf_counter() - started)
        except StaleClaim:
            log.warning("job %s: claim went stale, dropping result", job["job_id"])
        except Exception as e:
            retryable = isinstance(e, (httpx.TransportError, TimeoutError, OSError))
            log.exception("job %s failed", job["job_id"])
            try:
                self.client.fail(job["job_id"], job["claim_token"],
                                 f"{type(e).__name__}: {e}", retryable)
            except Exception:
                log.exception("could not report failure for job %s", job["job_id"])
        return True

    # ------------------------------------------------------------------ detect
    def process_detect(self, job: dict) -> dict:
        media = job["media"]
        data = self.client.download(media["url"])
        t0 = time.perf_counter()
        if media["kind"] == "image":
            img = Image.open(io.BytesIO(data))
            img.load()
            dets = self.models.detect(img)
            frames = [{"frame_id": job["frames"][0]["frame_id"], "detections": dets}]
            return {"model": self.models.detector_info, "frames": frames,
                    "timings": {"detect_s": round(time.perf_counter() - t0, 3)}}

        suffix = Path(media.get("original_name") or "clip.mp4").suffix or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(data)
            tmp.flush()
            sampled = sample_video(Path(tmp.name), self.video_fps, self.video_max_frames)
        scored = [(idx, off, img, self.models.detect(img)) for idx, off, img in sampled]
        kept = [s for s in scored if s[3]]
        if not kept:  # keep one poster frame for empty clips
            kept = [scored[len(scored) // 2]]
        id_map = self.client.upload_frames(job["job_id"], job["claim_token"],
                                           [(idx, off, jpeg_bytes(img)) for idx, off, img, _ in kept])
        frames = [{"frame_id": id_map[idx], "detections": dets} for idx, _, _, dets in kept]
        return {"model": self.models.detector_info, "frames": frames,
                "timings": {"detect_s": round(time.perf_counter() - t0, 3),
                            "frames_sampled": len(sampled), "frames_kept": len(kept)}}

    # ------------------------------------------------------------------ classify
    def process_classify(self, job: dict) -> dict:
        geo = job.get("geofence") or {}
        out = []
        t0 = time.perf_counter()
        for f in job.get("classify_inputs", []):
            img = Image.open(io.BytesIO(self.client.download(f["url"])))
            img.load()
            out.extend(self.models.classify(img, f["detections"], geo.get("country"),
                                            geo.get("admin1_region")))
        return {"model": self.models.classifier_info,
                "ensemble": {"name": "SpeciesNetEnsemble", "geofence": True},
                "geofence": geo, "classifications": out,
                "timings": {"classify_s": round(time.perf_counter() - t0, 3)}}

    def run_forever(self, idle_sleep: float = 2.0, max_idle_sleep: float = 15.0) -> None:
        sleep = idle_sleep
        last_beat = 0.0
        while True:
            try:
                if self.run_once():
                    sleep = idle_sleep
                    continue
                if time.time() - last_beat > 60:
                    self.client.worker_heartbeat(self.worker_id, self.kinds, self.capabilities())
                    last_beat = time.time()
            except httpx.TransportError as e:
                log.warning("edge unreachable (%s); retrying in %.0fs", e, sleep)
            time.sleep(sleep)
            sleep = min(max_idle_sleep, sleep * 1.5)
