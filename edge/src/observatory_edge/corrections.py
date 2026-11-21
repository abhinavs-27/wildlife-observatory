"""Manual corrections. Never modify predictions; store a correction and rebuild."""

from __future__ import annotations

import sqlite3

from .config import Settings
from .db import tx, utcnow
from .tracking import rebuild_window

TARGETS = {"detection", "classification", "encounter"}
ACTIONS = {"confirm", "reject", "relabel"}
STATUS_FOR = {"confirm": "confirmed", "reject": "rejected", "relabel": "corrected"}


class CorrectionError(ValueError):
    pass


def _locate(conn, target_type: str, target_id: int) -> tuple[int, str, str, str]:
    """Return (device_id, around_ts, window_start, window_end) for the target."""
    if target_type == "encounter":
        r = conn.execute("SELECT device_id, start_at, end_at FROM encounter WHERE id=?",
                         (target_id,)).fetchone()
        if not r:
            raise CorrectionError("encounter not found")
        return r["device_id"], r["start_at"], r["start_at"], r["end_at"]
    if target_type == "detection":
        sql = ("SELECT m.device_id, d.observed_at t FROM detection d JOIN media m "
               "ON m.id=d.media_id WHERE d.id=?")
    else:
        sql = ("SELECT m.device_id, d.observed_at t FROM classification c JOIN detection d "
               "ON d.id=c.detection_id JOIN media m ON m.id=d.media_id WHERE c.id=?")
    r = conn.execute(sql, (target_id,)).fetchone()
    if not r:
        raise CorrectionError(f"{target_type} not found")
    return r["device_id"], r["t"], r["t"], r["t"]


def add_correction(conn: sqlite3.Connection, settings: Settings, target_type: str,
                   target_id: int, action: str, label: str | None,
                   note: str | None = None) -> int:
    if target_type not in TARGETS:
        raise CorrectionError(f"target_type must be one of {sorted(TARGETS)}")
    if action not in ACTIONS:
        raise CorrectionError(f"action must be one of {sorted(ACTIONS)}")
    if action == "relabel" and not (label or "").strip():
        raise CorrectionError("relabel needs a label")
    label = label.strip().lower() if label else None
    with tx(conn):
        device_id, around, w0, w1 = _locate(conn, target_type, target_id)
        cid = conn.execute(
            "INSERT INTO correction(target_type, target_id, action, label, note, device_id, "
            "window_start, window_end, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (target_type, target_id, action, label, note, device_id, w0, w1, utcnow())).lastrowid
        if target_type in ("detection", "classification"):
            conn.execute(f"UPDATE {target_type} SET verification_status=? WHERE id=?",
                         (STATUS_FOR[action], target_id))
        rebuild_window(conn, settings, device_id, around)
    return cid
