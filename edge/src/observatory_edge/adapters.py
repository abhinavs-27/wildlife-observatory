"""Camera adapters. Provider-independent: anything that can hand the edge complete files."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Protocol

from .config import Settings
from .ingest import ingest_file
from .timeparse import IMAGE_EXTS, VIDEO_EXTS

log = logging.getLogger("observatory.adapters")
SUPPORTED = IMAGE_EXTS | VIDEO_EXTS


class CameraAdapter(Protocol):
    name: str

    def discover(self) -> list[Path]: ...
    def ack(self, item: Path, status: str) -> None: ...
    def healthcheck(self) -> dict: ...


class LocalFolderAdapter:
    """Watches a directory tree. A file is complete when its size/mtime are stable.

    The FTP receiver (scripts/ftp_receiver.py) only renames files into its `ready/` folder
    once a transfer finishes, so for FTP the stability check is just a backstop.
    """

    name = "folder"

    def __init__(self, root: Path, stable_seconds: float = 2.0, delete_after: bool = False):
        self.root = Path(root)
        self.stable_seconds = stable_seconds
        self.delete_after = delete_after

    def discover(self) -> list[Path]:
        if not self.root.exists():
            return []
        now = time.time()
        out = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in SUPPORTED:
                continue
            if any(part.startswith(".") for part in p.relative_to(self.root).parts):
                continue  # e.g. .incoming/
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            if now - st.st_mtime >= self.stable_seconds:
                out.append(p)
        return out

    def ack(self, item: Path, status: str) -> None:
        if self.delete_after and status in ("created", "duplicate") and item.exists():
            item.unlink()

    def healthcheck(self) -> dict:
        return {"adapter": self.name, "root": str(self.root), "exists": self.root.exists()}


class RtspAdapter:  # pragma: no cover - placeholder for future mains-powered cameras
    name = "rtsp"

    def __init__(self, url: str):
        raise NotImplementedError("RTSP ingestion is not implemented in the MVP (see design §7.5)")


def import_folder(conn: sqlite3.Connection, settings: Settings, folder: Path,
                  device: str = "default", suppress_alerts: bool = True) -> Counter:
    counts: Counter = Counter()
    for p in LocalFolderAdapter(folder, stable_seconds=0).discover():
        r = ingest_file(conn, settings, p, device_name=device, suppress_alerts=suppress_alerts,
                        adapter="cli")
        counts[r.status] += 1
        if r.error:
            log.warning("ingest %s: %s (%s)", p, r.status, r.error)
    return counts


def poll_adapter_once(conn: sqlite3.Connection, settings: Settings, adapter: CameraAdapter,
                      device: str) -> Counter:
    counts: Counter = Counter()
    for p in adapter.discover():
        r = ingest_file(conn, settings, p, device_name=device, adapter=adapter.name)
        counts[r.status] += 1
        adapter.ack(p, r.status)
    return counts
