"""Video frame sampling (in memory) with OpenCV."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def sample_video(path: Path, fps: float = 1.0, max_frames: int = 30
                 ) -> list[tuple[int, float, Image.Image]]:
    """Return [(index, offset_seconds, PIL image)] sampled at ~`fps`, capped at `max_frames`."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 0
    if src_fps <= 0 or src_fps > 240:
        src_fps = 25.0
    step = max(1, round(src_fps / fps))
    out: list[tuple[int, float, Image.Image]] = []
    i = 0
    while len(out) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            out.append((len(out), i / src_fps, Image.fromarray(rgb)))
        i += 1
    cap.release()
    if not out:
        raise ValueError(f"no frames decoded from {path}")
    return out


def jpeg_bytes(img: Image.Image, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()
