"""Apply worker results: detections (then tracks/encounters/alerts) and classifications."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from .config import Settings
from .db import parse_iso, to_iso, tx, utcnow
from .jobs import complete_job, enqueue
from .runs import get_live_run
from .taxonomy import display_name, is_uncertain, parse_label
from .tracking import rebuild_window

CATEGORIES = {"animal", "person", "vehicle"}


class ResultError(ValueError):
    pass


def apply_detect_result(conn: sqlite3.Connection, settings: Settings, job: dict,
                        payload: dict) -> dict:
    media = conn.execute("SELECT * FROM media WHERE id=?", (job["media_id"],)).fetchone()
    model = payload.get("model") or {}
    frames = {r["id"]: r for r in conn.execute(
        "SELECT * FROM frame WHERE media_id=?", (media["id"],)).fetchall()}
    with tx(conn):
        run_id = get_live_run(conn, model.get("name", "megadetector"),
                              model.get("version", "unknown"), "detection")
        n_animals = 0
        has_person = False
        for fr in payload.get("frames", []):
            frame = frames.get(fr["frame_id"])
            if frame is None:
                raise ResultError(f"frame {fr['frame_id']} does not belong to media {media['id']}")
            observed = to_iso(parse_iso(media["captured_at"])
                              + timedelta(seconds=frame["time_offset_s"] or 0))
            for d in fr.get("detections", []):
                cat = d["category"]
                if cat not in CATEGORIES:
                    raise ResultError(f"bad category {cat!r}")
                x, y, w, h = (float(v) for v in d["bbox"])
                conn.execute(
                    "INSERT INTO detection(run_id, media_id, frame_id, category, confidence, "
                    "bbox_x, bbox_y, bbox_w, bbox_h, observed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run_id, media["id"], frame["id"], cat, float(d["conf"]), x, y, w, h, observed))
                if cat == "animal" and d["conf"] >= settings.animal_threshold:
                    n_animals += 1
                if cat == "person" and d["conf"] >= settings.person_threshold:
                    has_person = True
        conn.execute(
            "UPDATE media SET status=?, has_person=?, active_detection_run_id=?, error=NULL "
            "WHERE id=?", ("detected" if n_animals else "empty", int(has_person), run_id,
                           media["id"]))
        if n_animals:
            enqueue(conn, "classify", media["id"], priority=0)
        complete_job(conn, job["id"], json.dumps(payload.get("timings") or {}))
        encounters = rebuild_window(conn, settings, media["device_id"], media["captured_at"]) \
            if n_animals else []
    return {"animals": n_animals, "has_person": has_person, "encounters": encounters}


def apply_classify_result(conn: sqlite3.Connection, settings: Settings, job: dict,
                          payload: dict) -> dict:
    media = conn.execute("SELECT * FROM media WHERE id=?", (job["media_id"],)).fetchone()
    model = payload.get("model") or {}
    geo = payload.get("geofence") or {}
    ensemble = payload.get("ensemble") or {}
    with tx(conn):
        run_id = get_live_run(conn, model.get("name", "speciesnet"),
                              model.get("version", "unknown"), "classification",
                              {"ensemble": ensemble})
        n = 0
        now = utcnow()
        for c in payload.get("classifications", []):
            det = conn.execute("SELECT media_id FROM detection WHERE id=?",
                               (c["detection_id"],)).fetchone()
            if not det or det["media_id"] != media["id"]:
                raise ResultError(f"detection {c['detection_id']} not in media {media['id']}")
            taxon = parse_label(c["label"])
            score = float(c.get("score") or 0)
            conn.execute(
                "INSERT INTO classification(run_id, detection_id, raw_label, taxon_class, "
                "taxon_order, taxon_family, taxon_genus, taxon_species, common_name, "
                "rollup_level, score, source, raw_topk_json, is_uncertain, geofence, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, c["detection_id"], c["label"], taxon.cls, taxon.order, taxon.family,
                 taxon.genus, taxon.species, display_name(taxon), taxon.level, score,
                 c.get("source"), json.dumps(c.get("raw") or []),
                 int(is_uncertain(taxon, score, settings.uncertain_score)),
                 f"{geo.get('country') or ''}/{geo.get('admin1_region') or ''}", now))
            n += 1
        conn.execute("UPDATE media SET active_classification_run_id=? WHERE id=?",
                     (run_id, media["id"]))
        complete_job(conn, job["id"], json.dumps(payload.get("timings") or {}))
        encounters = rebuild_window(conn, settings, media["device_id"], media["captured_at"])
    return {"classifications": n, "encounters": encounters}


def classify_inputs(conn: sqlite3.Connection, settings: Settings, media_id: int) -> list[dict]:
    """Animal detections (active run) the classifier should look at, grouped by frame."""
    rows = conn.execute(
        "SELECT d.id, d.frame_id, d.confidence, d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h "
        "FROM detection d JOIN media m ON m.id=d.media_id "
        "WHERE d.media_id=? AND d.run_id=m.active_detection_run_id AND d.category='animal' "
        "AND d.confidence >= ? ORDER BY d.frame_id, d.confidence DESC",
        (media_id, settings.animal_threshold)).fetchall()
    frames: dict[int, dict] = {}
    for r in rows:
        f = frames.setdefault(r["frame_id"], {"frame_id": r["frame_id"],
                                             "url": f"/frames/{r['frame_id']}/file",
                                             "detections": []})
        f["detections"].append({"detection_id": r["id"], "conf": r["confidence"],
                                "bbox": [r["bbox_x"], r["bbox_y"], r["bbox_w"], r["bbox_h"]]})
    return list(frames.values())
