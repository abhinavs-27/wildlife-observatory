"""Geometric tracking + encounter grouping (runs in the edge; no torch, no pixels).

`rebuild_window` is the single entry point: it recomputes tracks and encounters for the
connected time window around a capture, reusing the earliest existing encounter ids so
alerts and corrections stay attached, and queues one alert per new live encounter.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Settings
from .db import parse_iso, to_iso, utcnow
from .runs import get_live_run

TRACKER_NAME, TRACKER_VERSION = "geometric-iou", "1.0"


@dataclass
class Det:
    id: int
    frame_id: int
    media_id: int
    t: datetime
    bbox: tuple[float, float, float, float]
    conf: float
    has_person: bool
    suppress: bool
    species: str = "pending"
    species_score: float = 0.0
    uncertain: bool = False


@dataclass
class Track:
    dets: list[Det] = field(default_factory=list)
    species: str = "pending"
    confidence: float = 0.0
    uncertain: bool = False

    @property
    def start(self) -> datetime:
        return self.dets[0].t

    @property
    def end(self) -> datetime:
        return self.dets[-1].t


def iou(a, b) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def centroid_dist(a, b) -> float:
    ca = (a[0] + a[2] / 2, a[1] + a[3] / 2)
    cb = (b[0] + b[2] / 2, b[1] + b[3] / 2)
    return ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5


def link_tracks(dets: list[Det], max_gap_s: float, iou_min: float = 0.3,
                centroid_max: float = 0.15) -> list[Track]:
    """Greedy frame-by-frame association. Detections in the same frame never share a track."""
    tracks: list[Track] = []
    by_frame: dict[int, list[Det]] = defaultdict(list)
    order: list[int] = []
    for d in sorted(dets, key=lambda d: (d.t, d.frame_id, -d.conf)):
        if d.frame_id not in by_frame:
            order.append(d.frame_id)
        by_frame[d.frame_id].append(d)
    for fid in order:
        used: set[int] = set()
        for d in by_frame[fid]:
            best, best_score = None, 0.0
            for i, tr in enumerate(tracks):
                if i in used or tr.dets[-1].frame_id == fid:
                    continue
                if (d.t - tr.end).total_seconds() > max_gap_s:
                    continue
                last = tr.dets[-1].bbox
                score = iou(last, d.bbox)
                if score < iou_min:
                    dist = centroid_dist(last, d.bbox)
                    score = (1 - dist / centroid_max) * iou_min if dist < centroid_max else 0
                if score > best_score:
                    best, best_score = i, score
            if best is None:
                tracks.append(Track(dets=[d]))
                used.add(len(tracks) - 1)
            else:
                tracks[best].dets.append(d)
                used.add(best)
    return tracks


def vote_species(track: Track) -> None:
    scores: dict[str, float] = defaultdict(float)
    uncertain_by: dict[str, list[bool]] = defaultdict(list)
    for d in track.dets:
        if d.species == "pending":
            continue
        scores[d.species] += d.species_score * d.conf
        uncertain_by[d.species].append(d.uncertain)
    if not scores:
        track.species, track.confidence, track.uncertain = "pending", 0.0, False
        return
    winner = max(scores, key=scores.get)
    flags = uncertain_by[winner]
    track.species = winner
    track.confidence = max(d.species_score for d in track.dets if d.species == winner)
    track.uncertain = sum(flags) * 2 >= len(flags)


def _load_dets(conn: sqlite3.Connection, settings: Settings, device_id: int, lo: str,
               hi: str) -> list[Det]:
    rows = conn.execute(
        """
        SELECT d.id, d.frame_id, d.media_id, d.observed_at, d.bbox_x, d.bbox_y, d.bbox_w,
               d.bbox_h, d.confidence, m.has_person, m.suppress_alerts,
               c.common_name, c.score, c.is_uncertain,
               (SELECT label FROM correction k
                 WHERE (k.target_type='detection' AND k.target_id=d.id)
                    OR (k.target_type='classification' AND k.target_id=c.id)
                 ORDER BY k.id DESC LIMIT 1) AS corr_label,
               (SELECT action FROM correction k
                 WHERE (k.target_type='detection' AND k.target_id=d.id)
                    OR (k.target_type='classification' AND k.target_id=c.id)
                 ORDER BY k.id DESC LIMIT 1) AS corr_action
        FROM detection d
        JOIN media m ON m.id = d.media_id
        LEFT JOIN classification c ON c.detection_id = d.id
             AND c.run_id = m.active_classification_run_id
        WHERE m.device_id = ? AND d.run_id = m.active_detection_run_id
          AND d.category = 'animal' AND d.confidence >= ?
          AND d.observed_at BETWEEN ? AND ?
        ORDER BY d.observed_at, d.frame_id
        """, (device_id, settings.animal_threshold, lo, hi)).fetchall()
    out = []
    for r in rows:
        if r["corr_action"] == "reject":
            continue
        d = Det(r["id"], r["frame_id"], r["media_id"], parse_iso(r["observed_at"]),
                (r["bbox_x"], r["bbox_y"], r["bbox_w"], r["bbox_h"]), r["confidence"],
                bool(r["has_person"]), bool(r["suppress_alerts"]))
        if r["corr_action"] in ("relabel", "confirm") and (r["corr_label"] or r["common_name"]):
            d.species, d.species_score, d.uncertain = (r["corr_label"] or r["common_name"]), 1.0, False
        elif r["common_name"] is not None:
            d.species, d.species_score = r["common_name"], r["score"] or 0.0
            d.uncertain = bool(r["is_uncertain"])
        out.append(d)
    return out


def _expand_window(conn, settings: Settings, device_id: int, around: datetime):
    gap = timedelta(seconds=settings.encounter_gap_s)
    lo = hi = around
    while True:
        row = conn.execute(
            "SELECT MIN(d.observed_at) lo, MAX(d.observed_at) hi FROM detection d "
            "JOIN media m ON m.id=d.media_id WHERE m.device_id=? "
            "AND d.run_id = m.active_detection_run_id AND d.category='animal' "
            "AND d.confidence >= ? AND d.observed_at BETWEEN ? AND ?",
            (device_id, settings.animal_threshold, to_iso(lo - gap), to_iso(hi + gap))).fetchone()
        if not row["lo"]:
            return lo, hi
        nlo, nhi = min(lo, parse_iso(row["lo"])), max(hi, parse_iso(row["hi"]))
        if nlo == lo and nhi == hi:
            return lo, hi
        lo, hi = nlo, nhi


def _group(tracks: list[Track], gap_s: float) -> list[list[Track]]:
    groups: list[list[Track]] = []
    end = None
    for tr in sorted(tracks, key=lambda t: t.start):
        if groups and (tr.start - end).total_seconds() <= gap_s:
            groups[-1].append(tr)
            end = max(end, tr.end)
        else:
            groups.append([tr])
            end = tr.end
    return groups


def _species_counts(group: list[Track]) -> list[dict]:
    per_frame: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for ti, tr in enumerate(group):
        for d in tr.dets:
            per_frame[d.frame_id][tr.species].add(ti)
    counts: dict[str, int] = defaultdict(int)
    for frame in per_frame.values():
        for sp, ids in frame.items():
            counts[sp] = max(counts[sp], len(ids))
    unc = {tr.species: tr.uncertain for tr in group}
    conf = {}
    for tr in group:
        conf[tr.species] = max(conf.get(tr.species, 0.0), tr.confidence)
    return sorted(
        ({"species": sp, "count": n, "uncertain": unc.get(sp, False),
          "confidence": round(conf.get(sp, 0.0), 4)} for sp, n in counts.items()),
        key=lambda x: (x["species"] == "pending", -x["count"], x["species"]))


def _apply_encounter_corrections(conn, enc_id: int, species: list[dict]) -> tuple[list[dict], bool]:
    row = conn.execute(
        "SELECT action, label FROM correction WHERE target_type='encounter' AND target_id=? "
        "ORDER BY id DESC LIMIT 1", (enc_id,)).fetchone()
    if not row:
        return species, False
    if row["action"] == "reject":
        return species, True
    if row["action"] == "relabel" and row["label"]:
        total = max((s["count"] for s in species), default=1)
        return [{"species": row["label"], "count": total, "uncertain": False,
                 "confidence": 1.0, "corrected": True}], False
    if row["action"] == "confirm":
        return [dict(s, uncertain=False, corrected=True) for s in species], False
    return species, False


def rebuild_window(conn: sqlite3.Connection, settings: Settings, device_id: int,
                   around_ts: str) -> list[int]:
    from .alerts import queue_encounter_alert  # local import avoids a cycle

    gap = timedelta(seconds=settings.encounter_gap_s)
    lo, hi = _expand_window(conn, settings, device_id, parse_iso(around_ts))
    dets = _load_dets(conn, settings, device_id, to_iso(lo), to_iso(hi))
    tracks = link_tracks(dets, settings.track_max_gap_s)
    for tr in tracks:
        vote_species(tr)
    groups = _group(tracks, settings.encounter_gap_s)

    old = conn.execute(
        "SELECT id, start_at, end_at FROM encounter WHERE device_id=? AND end_at >= ? "
        "AND start_at <= ? ORDER BY id",
        (device_id, to_iso(lo - gap), to_iso(hi + gap))).fetchall()
    old_ids = [o["id"] for o in old]
    run_id = get_live_run(conn, TRACKER_NAME, TRACKER_VERSION, "tracking")
    now = utcnow()

    if old_ids:
        marks = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM track WHERE id IN (SELECT track_id FROM encounter_track "
                     f"WHERE encounter_id IN ({marks}))", old_ids)
        conn.execute(f"DELETE FROM encounter_media WHERE encounter_id IN ({marks})", old_ids)

    used: set[int] = set()
    result_ids: list[int] = []
    for group in groups:
        g_start = min(t.start for t in group)
        g_end = max(t.end for t in group)
        overlapping = [o["id"] for o in old
                       if o["id"] not in used
                       and parse_iso(o["start_at"]) <= g_end + gap
                       and parse_iso(o["end_at"]) >= g_start - gap]
        species = _species_counts(group)
        all_dets = [d for t in group for d in t.dets]
        best = max((d for d in all_dets if not d.has_person), key=lambda d: d.conf, default=None)
        status = "pending" if any(s["species"] == "pending" for s in species) else "classified"
        if overlapping:
            enc_id = min(overlapping)
            for other in overlapping:
                if other != enc_id:
                    conn.execute("UPDATE alert SET encounter_id=? WHERE encounter_id=?",
                                 (enc_id, other))
                    conn.execute("UPDATE milestone SET encounter_id=? WHERE encounter_id=?",
                                 (enc_id, other))
                    conn.execute("UPDATE correction SET target_id=? WHERE target_type='encounter' "
                                 "AND target_id=?", (enc_id, other))
            used.update(overlapping)
        else:
            enc_id = conn.execute(
                "INSERT INTO encounter(device_id, start_at, end_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?)", (device_id, to_iso(g_start), to_iso(g_end), now, now)
            ).lastrowid
        species, rejected = _apply_encounter_corrections(conn, enc_id, species)
        if rejected:
            status = "rejected"
        conn.execute(
            "UPDATE encounter SET start_at=?, end_at=?, species_json=?, best_frame_id=?, "
            "best_detection_id=?, status=?, updated_at=? WHERE id=?",
            (to_iso(g_start), to_iso(g_end), json.dumps(species),
             best.frame_id if best else None, best.id if best else None, status, now, enc_id))
        for tr in group:
            tid = conn.execute(
                "INSERT INTO track(run_id, device_id, start_at, end_at, species, confidence, "
                "is_uncertain) VALUES (?,?,?,?,?,?,?)",
                (run_id, device_id, to_iso(tr.start), to_iso(tr.end), tr.species,
                 tr.confidence, int(tr.uncertain))).lastrowid
            conn.executemany("INSERT INTO track_detection(track_id, detection_id) VALUES (?,?)",
                             [(tid, d.id) for d in tr.dets])
            conn.execute("INSERT INTO encounter_track(encounter_id, track_id) VALUES (?,?)",
                         (enc_id, tid))
        conn.executemany("INSERT OR IGNORE INTO encounter_media(encounter_id, media_id) VALUES (?,?)",
                         [(enc_id, mid) for mid in {d.media_id for d in all_dets}])
        result_ids.append(enc_id)
        if any(not d.suppress for d in all_dets) and status != "rejected":
            queue_encounter_alert(conn, settings, enc_id)

    # Old encounters with no surviving detections: move their alerts/corrections to the nearest
    # rebuilt encounter if any (corrections keep their stored window either way), then drop them.
    for oid in old_ids:
        if oid in result_ids:
            continue
        if oid in used:  # merged into another encounter; alerts/corrections already moved
            conn.execute("DELETE FROM encounter WHERE id=?", (oid,))
            continue
        if result_ids:
            conn.execute("UPDATE alert SET encounter_id=? WHERE encounter_id=?", (result_ids[0], oid))
        else:
            conn.execute("UPDATE alert SET encounter_id=NULL WHERE encounter_id=?", (oid,))
        conn.execute("DELETE FROM encounter WHERE id=?", (oid,))

    # Re-attach encounter corrections by stored window (survives full regrouping).
    for c in conn.execute(
            "SELECT id, window_start, window_end FROM correction WHERE target_type='encounter' "
            "AND device_id=? AND window_end >= ? AND window_start <= ?",
            (device_id, to_iso(lo - gap), to_iso(hi + gap))).fetchall():
        hit = conn.execute(
            "SELECT id FROM encounter WHERE device_id=? AND end_at >= ? AND start_at <= ? "
            "ORDER BY id LIMIT 1", (device_id, c["window_start"], c["window_end"])).fetchone()
        if hit:
            conn.execute("UPDATE correction SET target_id=? WHERE id=?", (hit["id"], c["id"]))
    return result_ids
