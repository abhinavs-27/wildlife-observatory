"""Disk retention for a microSD-only Pi (design §7.8).

Database rows are never deleted — only original files, so counts, charts and insights stay
intact. Order, cheapest loss first:
  1. Empty captures older than RETENTION_EMPTY_DAYS (always).
  2. Person-only captures older than RETENTION_PERSON_DAYS (always; privacy too).
  3. When disk ≥ DISK_HIGH_PCT: original *video* files older than VIDEO_KEEP_DAYS. The small JPEG
     frames that show the animal are kept, so the visit still replays.
  4. Still ≥ DISK_HIGH_PCT: oldest animal photos older than ANIMAL_MIN_DAYS, never touching
     protected media (corrected/confirmed visits, milestone and digest photos, species portraits).
Ingest pauses separately at DISK_FLOOR_PCT.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import Settings
from .db import to_iso, utcnow
from .queries import species_summary

log = logging.getLogger("observatory.retention")


def disk_used_pct(settings: Settings) -> float:
    u = shutil.disk_usage(settings.data_dir)
    return 100 * u.used / u.total


def _purge(conn: sqlite3.Connection, settings: Settings, media_id: int, path: str, reason: str) -> int:
    f = settings.data_dir / path
    size = f.stat().st_size if f.exists() else 0
    f.unlink(missing_ok=True)
    conn.execute("UPDATE media SET purged_at=?, purge_reason=? WHERE id=?", (utcnow(), reason, media_id))
    return size


def protected_media(conn: sqlite3.Connection) -> set[int]:
    ids: set[int] = set()
    q = [
        # visits the owner corrected or confirmed
        "SELECT em.media_id FROM correction c JOIN encounter_media em ON em.encounter_id = c.target_id "
        "WHERE c.target_type = 'encounter'",
        "SELECT d.media_id FROM correction c JOIN detection d ON d.id = c.target_id WHERE c.target_type='detection'",
        "SELECT d.media_id FROM detection d WHERE d.verification_status IN ('confirmed','corrected')",
        # milestone photos
        "SELECT em.media_id FROM milestone m JOIN encounter_media em ON em.encounter_id = m.encounter_id "
        "WHERE m.status != 'withdrawn'",
    ]
    for sql in q:
        ids.update(r[0] for r in conn.execute(sql))
    import json
    for r in conn.execute("SELECT payload_json FROM digest"):
        fid = json.loads(r[0]).get("best_frame_id")
        if fid:
            row = conn.execute("SELECT media_id FROM frame WHERE id=?", (fid,)).fetchone()
            if row:
                ids.add(row[0])
    for s in species_summary(conn):
        if s.get("best_frame_id"):
            row = conn.execute("SELECT media_id FROM frame WHERE id=?", (s["best_frame_id"],)).fetchone()
            if row:
                ids.add(row[0])
    return ids


def run_retention(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None,
                  disk_pct: Callable[[], float] | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    disk_pct = disk_pct or (lambda: disk_used_pct(settings))
    stats = {"empty": 0, "person": 0, "video": 0, "animal": 0, "bytes": 0}

    def older(days: int) -> str:
        return to_iso(now - timedelta(days=days))

    for r in conn.execute(
            "SELECT id, original_path FROM media WHERE purged_at IS NULL AND status='empty' AND has_person=0 "
            "AND created_at < ?", (older(settings.retention_empty_days),)).fetchall():
        stats["bytes"] += _purge(conn, settings, r["id"], r["original_path"], "empty")
        stats["empty"] += 1

    for r in conn.execute(
            """SELECT m.id, m.original_path FROM media m WHERE m.purged_at IS NULL AND m.has_person=1
               AND m.created_at < ? AND NOT EXISTS (
                 SELECT 1 FROM detection d WHERE d.media_id=m.id AND d.run_id=m.active_detection_run_id
                 AND d.category='animal' AND d.confidence >= ?)""",
            (older(settings.retention_person_days), settings.animal_threshold)).fetchall():
        stats["bytes"] += _purge(conn, settings, r["id"], r["original_path"], "person")
        stats["person"] += 1

    if disk_pct() < settings.disk_high_pct:
        return stats

    for r in conn.execute(
            "SELECT id, original_path FROM media WHERE purged_at IS NULL AND kind='video' "
            "AND created_at < ? ORDER BY created_at", (older(settings.video_keep_days),)).fetchall():
        if disk_pct() < settings.disk_high_pct:
            return stats
        stats["bytes"] += _purge(conn, settings, r["id"], r["original_path"], "video-original")
        stats["video"] += 1

    keep = protected_media(conn)
    for r in conn.execute(
            "SELECT id, original_path FROM media WHERE purged_at IS NULL AND kind='image' "
            "AND status='detected' AND created_at < ? ORDER BY captured_at",
            (older(settings.animal_min_days),)).fetchall():
        if disk_pct() < settings.disk_high_pct:
            break
        if r["id"] in keep:
            continue
        stats["bytes"] += _purge(conn, settings, r["id"], r["original_path"], "disk-space")
        stats["animal"] += 1
    if any(stats[k] for k in ("empty", "person", "video", "animal")):
        log.info("retention: %s", stats)
    return stats
