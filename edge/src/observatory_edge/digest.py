"""Weekly digest: Monday 08:00, covering the previous full Monday–Sunday week (local time)."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .alerts import queue_system_alert
from .config import Settings
from .db import to_iso, utcnow
from .insights import compute_insights
from .queries import list_encounters


def week_key(monday: date) -> str:
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


def previous_monday(now_local: datetime) -> date:
    this_monday = now_local.date() - timedelta(days=now_local.weekday())
    return this_monday - timedelta(days=7)


def build_digest(conn: sqlite3.Connection, settings: Settings, monday: date) -> dict:
    tz = ZoneInfo(settings.camera_timezone)
    start = datetime.combine(monday, time.min, tzinfo=tz)
    end = start + timedelta(days=7)
    encs = list_encounters(conn, date_from=to_iso(start), date_to=to_iso(end), limit=100000)
    encs = [e for e in encs if e["start_at"] >= to_iso(start)]
    counts: Counter = Counter()
    for e in encs:
        for s in e["species"]:
            if s["species"] != "pending" and not s.get("uncertain"):
                counts[s["species"]] += 1
    seen_before = {r[0] for r in conn.execute(
        "SELECT DISTINCT json_extract(j.value,'$.species') FROM encounter e, json_each(e.species_json) j "
        "WHERE e.start_at < ? AND e.status != 'rejected'", (to_iso(start),))}
    new_species = sorted(sp for sp in counts if sp not in seen_before)

    # Best photo: confident, no person (best_frame_id is NULL for person media), rarest wins ties.
    def score(e):
        s = e["species"][0] if e["species"] else {}
        return (s.get("confidence") or 0, -counts.get(s.get("species"), 99))
    candidates = [e for e in encs if e["best_frame_id"] and e["species"]
                  and e["species"][0]["species"] != "pending" and not e["species"][0].get("uncertain")]
    best = max(candidates, key=score) if candidates else None

    highlights: list[str] = []
    for m in conn.execute(  # same clock window as the visit counts
            "SELECT m.text FROM milestone m JOIN encounter e ON e.id = m.encounter_id "
            "WHERE m.status='active' AND e.start_at >= ? AND e.start_at < ? ORDER BY m.id",
            (to_iso(start), to_iso(end))):
        highlights.append(m["text"])
    for ins in compute_insights(conn, settings, now=end.astimezone(ZoneInfo("UTC"))):
        if len(highlights) >= 3:
            break
        if ins.text not in highlights:
            highlights.append(ins.text)

    visits = len(encs)
    sp_n = len(counts)
    if visits == 0:
        headline = "A quiet week in the yard: no visitors were recorded."
    elif visits <= 2:
        headline = f"A quiet week in the yard: {visits} visit{'s' if visits != 1 else ''}."
    else:
        headline = f"This week in the yard: {visits} visits from {sp_n} species."
    return {
        "week": week_key(monday), "start": monday.isoformat(),
        "end": (monday + timedelta(days=6)).isoformat(), "visits": visits, "species": sp_n,
        "species_counts": counts.most_common(), "new_species": new_species,
        "best_encounter_id": best["id"] if best else None,
        "best_frame_id": best["best_frame_id"] if best else None,
        "best_detection_id": best["best_detection_id"] if best else None,
        "best_species": best["species"][0]["species"] if best else None,
        "headline": headline, "highlights": highlights[:3],
    }


def digest_body(d: dict) -> str:
    lines = [d["headline"]]
    if d["species_counts"]:
        lines.append("Visitors: " + ", ".join(f"{sp} ({n})" for sp, n in d["species_counts"][:6]) + ".")
    if d["new_species"]:
        lines.append("New this week: " + ", ".join(d["new_species"]) + "!")
    lines += [f"• {h}" for h in d["highlights"]]
    if d["best_species"]:
        lines.append(f"Photo: {d['best_species']}.")
    return "\n".join(lines)


def send_digest(conn: sqlite3.Connection, settings: Settings, monday: date) -> bool:
    """Build, store and queue the digest for the week starting `monday`. Idempotent."""
    key = week_key(monday)
    if conn.execute("SELECT 1 FROM digest WHERE week=?", (key,)).fetchone():
        return False
    d = build_digest(conn, settings, monday)
    conn.execute("INSERT INTO digest(week, payload_json, sent_at) VALUES (?,?,?)",
                 (key, json.dumps(d), utcnow()))
    body = digest_body(d)
    link = f"{settings.dashboard_url.rstrip('/')}/digest/{key}" if settings.dashboard_url else None
    title = d["headline"].split(":")[0]
    for channel in ("owner", "family"):
        queue_system_alert(conn, "digest", title, body, channel=channel,
                           encounter_id=d["best_encounter_id"], attach_frame_id=d["best_frame_id"],
                           attach_detection_id=d["best_detection_id"], link=link)
    return True


def maybe_send_weekly(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> bool:
    """Called by the background loop: on Mondays from 08:00 local, send last week's digest."""
    tz = ZoneInfo(settings.camera_timezone)
    now_local = (now or datetime.now(tz)).astimezone(tz)
    if now_local.weekday() != 0 or now_local.hour < 8:
        return False
    return send_digest(conn, settings, previous_monday(now_local))
