"""Capture-time extraction: EXIF (camera local time) -> container metadata (UTC) -> mtime."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from .db import to_iso

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003
_DATETIME = 0x0132
_OFFSET_ORIGINAL = 0x9011


def _exif_time(path: Path, tz: str) -> datetime | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except Exception:
        return None
    ifd = exif.get_ifd(_EXIF_IFD) if exif else {}
    raw = ifd.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME) if exif else None
    if not raw:
        return None
    try:
        dt = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    offset = ifd.get(_OFFSET_ORIGINAL)
    if offset:
        try:
            return datetime.fromisoformat(dt.isoformat() + str(offset).strip("\x00 "))
        except ValueError:
            pass
    return dt.replace(tzinfo=ZoneInfo(tz))


def _container_time(path: Path) -> datetime | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, timeout=20, check=False,
        ).stdout
        tags = json.loads(out or b"{}").get("format", {}).get("tags", {})
        raw = tags.get("creation_time")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:  # MP4 creation_time is UTC by spec
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.year < 2000:  # zeroed atoms
            return None
        return dt
    except Exception:
        return None


def extract_captured_at(path: Path, tz: str) -> tuple[str, str]:
    """Return (UTC ISO timestamp, source) where source is exif|container|mtime."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        dt = _exif_time(path, tz)
        if dt:
            return to_iso(dt), "exif"
    if ext in VIDEO_EXTS:
        dt = _container_time(path)
        if dt:
            return to_iso(dt), "container"
    return to_iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)), "mtime"
