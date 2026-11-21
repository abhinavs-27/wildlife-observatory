"""Milestones: firsts, returns and records, computed from stored visits.

Evaluation is idempotent (unique `key` per milestone) and safe to re-run after every classify
result, correction, or nightly. Pushed milestones are never retracted; if a later correction
removes their basis they are marked `withdrawn` and hidden.

Family pushes go out only when the identification is confident (species-level, not uncertain,
score ≥ FAMILY_MIN_SCORE) or the owner has confirmed/relabelled the visit.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .alerts import encounter_link, queue_system_alert
from .astro import night_of
from .config import Settings
from .db import parse_iso, utcnow

PUSH_KINDS = {"first_species", "back_after"}
SPECIES_COUNTS = (10, 25, 50, 100)
BACK_AFTER_DAYS = 14


@dataclass
class V:
    encounter_id: int
    species: str
    t: datetime
    score: float
    corrected: bool
    live: bool
    best_frame_id: int | None
    best_detection_id: int | None


def _visits(conn: sqlite3.Connection) -> list[V]:
    rows = conn.execute(
        """SELECT e.id, e.start_at, e.species_json, e.best_frame_id, e.best_detection_id,
                  EXISTS (SELECT 1 FROM encounter_media em JOIN media m ON m.id=em.media_id
                          WHERE em.encounter_id=e.id AND m.suppress_alerts=0) AS live
           FROM encounter e WHERE e.status != 'rejected' ORDER BY e.start_at, e.id""").fetchall()
    out = []
    for r in rows:
        for s in json.loads(r["species_json"]):
            if s["species"] == "pending" or s.get("uncertain"):
                continue
            out.append(V(r["id"], s["species"], parse_iso(r["start_at"]),
                         float(s.get("confidence") or 0), bool(s.get("corrected")), bool(r["live"]),
                         r["best_frame_id"], r["best_detection_id"]))
    return out


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _gap(days: int) -> str:
    if days > 365:
        return "more than a year"
    if days >= 60:
        return f"{round(days / 30.4)} months"
    if days >= 21:
        return f"{round(days / 7)} weeks"
    return f"{days} days"


def _compute(visits: list[V], tz: str) -> dict[str, dict]:
    """Return {key: milestone dict} for everything the current data supports."""
    found: dict[str, dict] = {}
    first_seen: dict[str, V] = {}
    last_seen: dict[str, V] = {}
    first_year: set[tuple[str, int]] = set()
    species_order: list[str] = []
    for v in visits:
        night = night_of(v.t, tz)
        if v.species not in first_seen:
            first_seen[v.species] = v
            first_year.add((v.species, night.year))
            species_order.append(v.species)
            found[f"first_species:{v.species}"] = dict(
                kind="first_species", species=v.species, visit=v, night=night,
                text=f"First {v.species} ever!")
            n = len(species_order)
            if n in SPECIES_COUNTS:
                found[f"species_count:{n}"] = dict(
                    kind="new_species_count", species=v.species, visit=v, night=night,
                    text=f"{n} species seen so far — the {n}th was a {v.species}.")
        else:
            prev = last_seen[v.species]
            gap = (v.t - prev.t).days
            if gap >= BACK_AFTER_DAYS:
                found[f"back_after:{v.species}:{night}"] = dict(
                    kind="back_after", species=v.species, visit=v, night=night,
                    text=f"The {v.species} is back after {_gap(gap)} away.")
            if (v.species, night.year) not in first_year:
                first_year.add((v.species, night.year))
                found[f"first_this_year:{v.species}:{night.year}"] = dict(
                    kind="first_this_year", species=v.species, visit=v, night=night,
                    text=f"First {v.species} of {night.year}.")
        last_seen[v.species] = v

    per_night: dict = defaultdict(set)
    last_visit_of_night: dict = {}
    for v in visits:
        n = night_of(v.t, tz)
        per_night[n].add(v.encounter_id)
        last_visit_of_night[n] = v
    best = 0
    for n in sorted(per_night):
        count = len(per_night[n])
        if best and count > best and count >= 3:
            found[f"record_night:{n}"] = dict(
                kind="record_night", species=None, visit=last_visit_of_night[n], night=n,
                text=f"Busiest night yet: {count} visits.")
        best = max(best, count)
    return found


def evaluate_milestones(conn: sqlite3.Connection, settings: Settings) -> list[int]:
    """Insert new milestones, release confirmed ones, withdraw unsupported ones. Returns new ids."""
    tz = settings.camera_timezone
    found = _compute(_visits(conn), tz)
    existing = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM milestone")}
    new_ids: list[int] = []
    now = utcnow()

    for key, m in found.items():
        v: V = m["visit"]
        confident = v.corrected or v.score >= settings.family_min_score
        if key not in existing:
            status = "active" if confident or m["kind"] not in PUSH_KINDS else "awaiting_confirmation"
            mid = conn.execute(
                "INSERT INTO milestone(key, kind, species, encounter_id, text, night, status, "
                "created_at) VALUES (?,?,?,?,?,?,?,?)",
                (key, m["kind"], m["species"], v.encounter_id, m["text"], m["night"].isoformat(),
                 status, now)).lastrowid
            new_ids.append(mid)
            row = conn.execute("SELECT * FROM milestone WHERE id=?", (mid,)).fetchone()
            _push(conn, settings, dict(row), v, confident)
        else:
            row = existing[key]
            updates = {"encounter_id": v.encounter_id, "text": m["text"]}
            if row["status"] == "withdrawn":
                updates["status"] = "active" if confident else "awaiting_confirmation"
            elif row["status"] == "awaiting_confirmation" and confident:
                updates["status"] = "active"
            conn.execute(
                f"UPDATE milestone SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                (*updates.values(), row["id"]))
            if updates.get("status") == "active" or (row["status"] == "active" and confident):
                fresh = conn.execute("SELECT * FROM milestone WHERE id=?", (row["id"],)).fetchone()
                _push(conn, settings, dict(fresh), v, confident)

    for key, row in existing.items():
        if key not in found and row["status"] != "withdrawn":
            conn.execute("UPDATE milestone SET status='withdrawn' WHERE id=?", (row["id"],))
    return new_ids


def _push(conn: sqlite3.Connection, settings: Settings, m: dict, v: V, confident: bool) -> None:
    """Queue owner/family pushes for push-worthy milestones on live captures, at most once each."""
    if m["kind"] not in PUSH_KINDS or not v.live:
        return
    emoji = "🎉" if m["kind"] == "first_species" else "👋"
    if not m["pushed_owner"]:
        prefix = "" if confident else "(unconfirmed) "
        queue_system_alert(
            conn, "milestone", "Wildlife Observatory", f"{emoji} {prefix}{m['text']}",
            channel="owner", encounter_id=v.encounter_id, attach_frame_id=v.best_frame_id,
            attach_detection_id=v.best_detection_id, link=encounter_link(settings, v.encounter_id))
        conn.execute("UPDATE milestone SET pushed_owner=1 WHERE id=?", (m["id"],))
    if confident and not m["pushed_family"] and m["status"] == "active":
        when = v.t.strftime("%b %-d")
        queue_system_alert(
            conn, "milestone", "Backyard wildlife", f"{emoji} {m['text']} Seen on {when}.",
            channel="family", encounter_id=v.encounter_id, attach_frame_id=v.best_frame_id,
            attach_detection_id=v.best_detection_id)
        conn.execute("UPDATE milestone SET pushed_family=1 WHERE id=?", (m["id"],))
