"""Idempotent ingestion: hash, preserve original, create device/event/media/frame/job."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

from .config import Settings
from .db import parse_iso, tx, utcnow
from .timeparse import IMAGE_EXTS, VIDEO_EXTS, extract_captured_at

Status = Literal["created", "duplicate", "failed", "quarantined", "unsupported"]


@dataclass
class IngestResult:
    status: Status
    media_id: int | None = None
    error: str | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_or_create_device(conn: sqlite3.Connection, name: str, adapter: str = "folder") -> int:
    row = conn.execute("SELECT id FROM device WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO device(kind, name, adapter, created_at) VALUES ('camera', ?, ?, ?)",
        (name, adapter, utcnow()),
    )
    return cur.lastrowid


def _probe_image(path: Path) -> dict:
    with Image.open(path) as img:
        img.verify()  # detects truncation/corruption
    with Image.open(path) as img:
        img.load()
        return {"width": img.width, "height": img.height, "mime": Image.MIME.get(img.format),
                "metadata": {"format": img.format,
                             "exif": {str(k): str(v) for k, v in (img.getexif() or {}).items()}}}


def _probe_video(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        import cv2  # optional fallback
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError("unreadable video")
        w, h = int(cap.get(3)), int(cap.get(4))
        n, fps = cap.get(7), cap.get(5) or 0
        cap.release()
        return {"width": w, "height": h, "duration_s": (n / fps) if fps else None,
                "mime": "video/mp4", "metadata": {}}
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)], capture_output=True, timeout=30, check=False)
    info = json.loads(out.stdout or b"{}")
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if out.returncode != 0 or not streams:
        raise ValueError(f"unreadable video: {out.stderr.decode(errors='ignore')[:200]}")
    fmt = info.get("format", {})
    return {"width": streams[0].get("width"), "height": streams[0].get("height"),
            "duration_s": float(fmt["duration"]) if fmt.get("duration") else None,
            "mime": "video/" + (fmt.get("format_name", "mp4").split(",")[0]),
            "metadata": {"format": fmt.get("format_name"), "tags": fmt.get("tags", {})}}


def _record_failure(conn, settings: Settings, path: Path, error: str) -> IngestResult:
    key = str(path.resolve())
    row = conn.execute("SELECT attempts FROM ingest_failure WHERE path=?", (key,)).fetchone()
    attempts = (row["attempts"] if row else 0) + 1
    conn.execute(
        "INSERT INTO ingest_failure(path, attempts, last_error, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET attempts=excluded.attempts, "
        "last_error=excluded.last_error, updated_at=excluded.updated_at",
        (key, attempts, error, utcnow()))
    if attempts >= settings.max_attempts:
        settings.quarantine_dir.mkdir(parents=True, exist_ok=True)
        dest = settings.quarantine_dir / path.name
        if dest.exists():
            dest = settings.quarantine_dir / f"{path.stem}.{attempts}{path.suffix}"
        shutil.move(str(path), dest)
        return IngestResult("quarantined", error=error)
    return IngestResult("failed", error=error)


def ingest_file(conn: sqlite3.Connection, settings: Settings, path: Path,
                device_name: str = "default", suppress_alerts: bool = False,
                adapter: str = "folder") -> IngestResult:
    ext = path.suffix.lower()
    if ext not in IMAGE_EXTS | VIDEO_EXTS:
        return IngestResult("unsupported")
    try:
        digest = sha256_file(path)
    except OSError as e:
        return _record_failure(conn, settings, path, f"read error: {e}")

    existing = conn.execute("SELECT id FROM media WHERE sha256=?", (digest,)).fetchone()
    if existing:
        return IngestResult("duplicate", media_id=existing["id"])

    kind = "video" if ext in VIDEO_EXTS else "image"
    try:
        probe = _probe_video(path) if kind == "video" else _probe_image(path)
    except Exception as e:  # corrupt, truncated, unsupported codec
        return _record_failure(conn, settings, path, f"{type(e).__name__}: {e}")

    captured_at, ts_source = extract_captured_at(path, settings.camera_timezone)
    if not suppress_alerts:
        age = (parse_iso(utcnow()) - parse_iso(captured_at)).total_seconds()
        suppress_alerts = age > settings.alert_max_age_s

    dt = parse_iso(captured_at)
    rel = Path("originals") / f"{dt:%Y}" / f"{dt:%m}" / f"{digest}{ext}"
    dest = settings.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    shutil.copy2(path, tmp)
    os.replace(tmp, dest)

    now = utcnow()
    with tx(conn):
        device_id = get_or_create_device(conn, device_name, adapter)
        ev = conn.execute(
            "INSERT INTO event(device_id, kind, occurred_at, occurred_at_source, payload_json, "
            "created_at) VALUES (?, 'capture', ?, ?, ?, ?)",
            (device_id, captured_at, ts_source,
             json.dumps({"original_name": path.name, "source_path": str(path)}), now)).lastrowid
        media_id = conn.execute(
            "INSERT INTO media(event_id, device_id, sha256, kind, original_path, original_name, "
            "source_adapter, mime, size, width, height, duration_s, metadata_json, captured_at, "
            "captured_at_source, suppress_alerts, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ev, device_id, digest, kind, str(rel), path.name, adapter, probe.get("mime"),
             path.stat().st_size, probe.get("width"), probe.get("height"),
             probe.get("duration_s"), json.dumps(probe.get("metadata", {}), default=str),
             captured_at, ts_source, int(suppress_alerts), now)).lastrowid
        if kind == "image":
            conn.execute(
                "INSERT INTO frame(media_id, idx, time_offset_s, path, width, height) "
                "VALUES (?, 0, 0, ?, ?, ?)",
                (media_id, str(rel), probe.get("width"), probe.get("height")))
        conn.execute(
            "INSERT INTO job(kind, media_id, priority, created_at, updated_at) "
            "VALUES ('detect', ?, 10, ?, ?)", (media_id, now, now))
        conn.execute("DELETE FROM ingest_failure WHERE path=?", (str(path.resolve()),))
    return IngestResult("created", media_id=media_id)
