"""Alert outbox + ntfy sender. Alerts never block the pipeline."""

from __future__ import annotations

import io
import json
import logging
import sqlite3
from datetime import timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw

from .config import Settings
from .db import parse_iso, utcnow

log = logging.getLogger("observatory.alerts")
STALE_AFTER = timedelta(hours=6)


class Sender(Protocol):
    def send(self, title: str, body: str, image: bytes | None, tags: str) -> None: ...


class NtfySender:
    def __init__(self, url: str, topic: str, timeout: float = 15):
        self.url, self.topic, self.timeout = url.rstrip("/"), topic, timeout

    def send(self, title: str, body: str, image: bytes | None, tags: str = "paw_prints") -> None:
        headers = {"Title": title, "Tags": tags}
        if image:
            headers.update({"Filename": "snapshot.jpg", "Message": body})
            r = httpx.put(f"{self.url}/{self.topic}", content=image, headers=headers,
                          timeout=self.timeout)
        else:
            r = httpx.post(f"{self.url}/{self.topic}", content=body.encode(), headers=headers,
                           timeout=self.timeout)
        r.raise_for_status()


def queue_encounter_alert(conn: sqlite3.Connection, settings: Settings, encounter_id: int) -> int | None:
    if conn.execute("SELECT 1 FROM alert WHERE encounter_id=? AND kind='encounter'",
                    (encounter_id,)).fetchone():
        return None
    enc = conn.execute("SELECT * FROM encounter WHERE id=?", (encounter_id,)).fetchone()
    best = conn.execute("SELECT confidence FROM detection WHERE id=?",
                        (enc["best_detection_id"],)).fetchone() if enc["best_detection_id"] else None
    top = conn.execute(
        "SELECT MAX(d.confidence) c FROM detection d JOIN track_detection td ON td.detection_id=d.id "
        "JOIN encounter_track et ON et.track_id=td.track_id WHERE et.encounter_id=?",
        (encounter_id,)).fetchone()["c"] or 0
    if top < settings.alert_threshold:
        return None
    species = json.loads(enc["species_json"])
    n = sum(s["count"] for s in species) or 1
    local = parse_iso(enc["start_at"]).astimezone(ZoneInfo(settings.camera_timezone))
    when = local.strftime("%-I:%M %p").lower()
    named = [s for s in species if s["species"] != "pending" and not s.get("uncertain")]
    what = ", ".join(s["species"] for s in named) if named else "Animal"
    body = f"{what} detected ({n} animal{'s' if n != 1 else ''}) at {when}"
    return conn.execute(
        "INSERT INTO alert(encounter_id, kind, title, body, attach_frame_id, attach_detection_id, "
        "created_at) VALUES (?, 'encounter', 'Wildlife Observatory', ?, ?, ?, ?)",
        (encounter_id, body, enc["best_frame_id"] if best else None,
         enc["best_detection_id"] if best else None, utcnow())).lastrowid


def queue_system_alert(conn: sqlite3.Connection, kind: str, title: str, body: str) -> int:
    return conn.execute(
        "INSERT INTO alert(kind, title, body, created_at) VALUES (?,?,?,?)",
        (kind, title, body, utcnow())).lastrowid


def render_snapshot(settings: Settings, conn: sqlite3.Connection, frame_id: int,
                    detection_id: int | None) -> bytes | None:
    """Draw the box in memory; never write annotated images to disk."""
    row = conn.execute(
        "SELECT f.path, m.has_person FROM frame f JOIN media m ON m.id=f.media_id WHERE f.id=?",
        (frame_id,)).fetchone()
    if not row or row["has_person"]:
        return None
    try:
        with Image.open(settings.data_dir / row["path"]) as img:
            img = img.convert("RGB")
            if detection_id:
                d = conn.execute("SELECT bbox_x,bbox_y,bbox_w,bbox_h FROM detection WHERE id=?",
                                 (detection_id,)).fetchone()
                if d:
                    W, H = img.size
                    x, y, w, h = d["bbox_x"] * W, d["bbox_y"] * H, d["bbox_w"] * W, d["bbox_h"] * H
                    ImageDraw.Draw(img).rectangle([x, y, x + w, y + h], outline=(255, 200, 0),
                                                  width=max(2, W // 300))
            img.thumbnail((1280, 1280))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
            return buf.getvalue()
    except Exception as e:  # snapshot is best-effort
        log.warning("snapshot failed for frame %s: %s", frame_id, e)
        return None


def send_pending_alerts(conn: sqlite3.Connection, settings: Settings,
                        sender: Sender | None) -> dict:
    stats = {"sent": 0, "failed": 0, "stale": 0, "skipped": 0}
    now = parse_iso(utcnow())
    for a in conn.execute("SELECT * FROM alert WHERE status='pending' ORDER BY id").fetchall():
        if now - parse_iso(a["created_at"]) > STALE_AFTER:
            conn.execute("UPDATE alert SET status='stale' WHERE id=?", (a["id"],))
            stats["stale"] += 1
            continue
        if sender is None:
            stats["skipped"] += 1
            continue
        image = None
        if a["attach_frame_id"]:
            image = render_snapshot(settings, conn, a["attach_frame_id"], a["attach_detection_id"])
        try:
            sender.send(a["title"], a["body"], image,
                        "paw_prints" if a["kind"] == "encounter" else "warning")
            conn.execute("UPDATE alert SET status='sent', sent_at=?, attempts=attempts+1 WHERE id=?",
                         (utcnow(), a["id"]))
            stats["sent"] += 1
        except Exception as e:
            attempts = a["attempts"] + 1
            conn.execute("UPDATE alert SET attempts=?, error=?, status=? WHERE id=?",
                         (attempts, str(e)[:500], "failed" if attempts >= 20 else "pending",
                          a["id"]))
            stats["failed"] += 1
    return stats


def make_sender(settings: Settings) -> Sender | None:
    return NtfySender(settings.ntfy_url, settings.ntfy_topic) if settings.ntfy_topic else None
