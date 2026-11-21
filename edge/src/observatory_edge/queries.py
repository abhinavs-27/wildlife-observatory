"""Read models for the dashboard and search. Facts come only from the database."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections import Counter
from zoneinfo import ZoneInfo

from .config import Settings
from .db import parse_iso, utcnow

SPECIES_MATCH = ("EXISTS (SELECT 1 FROM json_each(e.species_json) j "
                 "WHERE json_extract(j.value,'$.species') = ?)")


def _enc_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["species"] = json.loads(d.pop("species_json"))
    return d


def list_encounters(conn: sqlite3.Connection, species: str | None = None,
                    species_any: list[str] | None = None, date_from: str | None = None,
                    date_to: str | None = None, uncertain: bool | None = None,
                    status: str | None = None, include_rejected: bool = False,
                    limit: int = 50, offset: int = 0) -> list[dict]:
    where, args = ["1=1"], []
    if not include_rejected:
        where.append("e.status != 'rejected'")
    if species:
        where.append(SPECIES_MATCH)
        args.append(species)
    if species_any:
        marks = ",".join("?" * len(species_any))
        where.append("EXISTS (SELECT 1 FROM json_each(e.species_json) j "
                     f"WHERE json_extract(j.value,'$.species') IN ({marks}))")
        args.extend(species_any)
    if date_from:
        where.append("e.end_at >= ?")
        args.append(date_from)
    if date_to:
        where.append("e.start_at < ?")
        args.append(date_to)
    if uncertain is not None:
        where.append("EXISTS (SELECT 1 FROM json_each(e.species_json) j "
                     "WHERE json_extract(j.value,'$.uncertain') = ?)")
        args.append(1 if uncertain else 0)
    if status:
        where.append("e.status = ?")
        args.append(status)
    rows = conn.execute(
        f"""SELECT e.id, e.device_id, dv.name AS device, e.start_at, e.end_at, e.species_json,
                   e.status, e.best_frame_id, e.best_detection_id,
                   (SELECT COUNT(*) FROM encounter_media em WHERE em.encounter_id=e.id) media_count,
                   d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h
            FROM encounter e JOIN device dv ON dv.id=e.device_id
            LEFT JOIN detection d ON d.id=e.best_detection_id
            WHERE {' AND '.join(where)}
            ORDER BY e.start_at DESC LIMIT ? OFFSET ?""", (*args, limit, offset)).fetchall()
    out = []
    for r in rows:
        d = _enc_row(r)
        box = [d.pop(k) for k in ("bbox_x", "bbox_y", "bbox_w", "bbox_h")]
        d["best_bbox"] = box if box[0] is not None else None
        out.append(d)
    return out


def get_encounter(conn: sqlite3.Connection, encounter_id: int) -> dict | None:
    r = conn.execute("SELECT e.*, dv.name device FROM encounter e JOIN device dv "
                     "ON dv.id=e.device_id WHERE e.id=?", (encounter_id,)).fetchone()
    if not r:
        return None
    enc = _enc_row(r)
    media = conn.execute(
        "SELECT m.* FROM media m JOIN encounter_media em ON em.media_id=m.id "
        "WHERE em.encounter_id=? ORDER BY m.captured_at", (encounter_id,)).fetchall()
    enc["media"] = [media_detail(conn, m) for m in media]
    enc["tracks"] = [dict(t) for t in conn.execute(
        "SELECT t.id, t.start_at, t.end_at, t.species, t.confidence, t.is_uncertain, "
        "(SELECT COUNT(*) FROM track_detection td WHERE td.track_id=t.id) n_detections "
        "FROM track t JOIN encounter_track et ON et.track_id=t.id WHERE et.encounter_id=?",
        (encounter_id,)).fetchall()]
    enc["corrections"] = [dict(c) for c in conn.execute(
        "SELECT * FROM correction WHERE target_type='encounter' AND target_id=? ORDER BY id",
        (encounter_id,)).fetchall()]
    enc["alerts"] = [dict(a) for a in conn.execute(
        "SELECT id, status, body, created_at, sent_at, error FROM alert WHERE encounter_id=?",
        (encounter_id,)).fetchall()]
    return enc


def media_detail(conn: sqlite3.Connection, m: sqlite3.Row) -> dict:
    frames = conn.execute("SELECT id, idx, time_offset_s, width, height FROM frame "
                          "WHERE media_id=? ORDER BY idx", (m["id"],)).fetchall()
    dets = conn.execute(
        """SELECT d.id, d.frame_id, d.category, d.confidence, d.bbox_x, d.bbox_y, d.bbox_w,
                  d.bbox_h, d.verification_status, mo.name model, mo.version model_version
           FROM detection d JOIN inference_run r ON r.id=d.run_id JOIN model mo ON mo.id=r.model_id
           WHERE d.media_id=? AND d.run_id=? ORDER BY d.confidence DESC""",
        (m["id"], m["active_detection_run_id"])).fetchall()
    out_dets = []
    for d in dets:
        dd = dict(d)
        dd["bbox"] = [dd.pop("bbox_x"), dd.pop("bbox_y"), dd.pop("bbox_w"), dd.pop("bbox_h")]
        c = conn.execute(
            """SELECT c.id, c.common_name, c.score, c.is_uncertain, c.rollup_level, c.source,
                      c.raw_topk_json, c.taxon_class, c.taxon_order, c.taxon_family,
                      c.taxon_genus, c.taxon_species, c.geofence, c.verification_status,
                      mo.name model, mo.version model_version
               FROM classification c JOIN inference_run r ON r.id=c.run_id
               JOIN model mo ON mo.id=r.model_id
               WHERE c.detection_id=? AND c.run_id=? ORDER BY c.id DESC LIMIT 1""",
            (d["id"], m["active_classification_run_id"])).fetchone()
        if c:
            cc = dict(c)
            cc["raw_topk"] = json.loads(cc.pop("raw_topk_json"))
            dd["classification"] = cc
        corr = conn.execute(
            "SELECT action, label, created_at FROM correction WHERE target_type='detection' "
            "AND target_id=? ORDER BY id DESC LIMIT 1", (d["id"],)).fetchone()
        dd["correction"] = dict(corr) if corr else None
        out_dets.append(dd)
    return {"id": m["id"], "kind": m["kind"], "original_name": m["original_name"],
            "captured_at": m["captured_at"], "captured_at_source": m["captured_at_source"],
            "status": m["status"], "error": m["error"], "has_person": bool(m["has_person"]),
            "width": m["width"], "height": m["height"], "duration_s": m["duration_s"],
            "frames": [dict(f) for f in frames], "detections": out_dets}


def list_media(conn: sqlite3.Connection, status: str | None = None, kind: str | None = None,
               include_person: bool = False, species: str | None = None,
               limit: int = 60, offset: int = 0) -> list[dict]:
    where, args = ["1=1"], []
    if status:
        where.append("m.status=?")
        args.append(status)
    if kind:
        where.append("m.kind=?")
        args.append(kind)
    if not include_person:
        where.append("m.has_person=0")
    if species:
        where.append("EXISTS (SELECT 1 FROM encounter_media em JOIN encounter e ON "
                     f"e.id=em.encounter_id WHERE em.media_id=m.id AND {SPECIES_MATCH})")
        args.append(species)
    rows = conn.execute(
        f"""SELECT m.id, m.kind, m.original_name, m.captured_at, m.status, m.error,
                   m.has_person, m.width, m.height,
                   (SELECT f.id FROM frame f WHERE f.media_id=m.id ORDER BY f.idx LIMIT 1) frame_id,
                   (SELECT em.encounter_id FROM encounter_media em WHERE em.media_id=m.id
                     LIMIT 1) encounter_id,
                   (SELECT COUNT(*) FROM detection d WHERE d.media_id=m.id
                     AND d.run_id=m.active_detection_run_id AND d.category='animal') n_animals
            FROM media m WHERE {' AND '.join(where)}
            ORDER BY m.captured_at DESC LIMIT ? OFFSET ?""", (*args, limit, offset)).fetchall()
    return [dict(r) for r in rows]


def species_summary(conn: sqlite3.Connection, include_pending: bool = False) -> list[dict]:
    rows = conn.execute(
        """SELECT json_extract(j.value,'$.species') species,
                  COUNT(DISTINCT e.id) encounters,
                  SUM(json_extract(j.value,'$.count')) animals,
                  MAX(json_extract(j.value,'$.uncertain')) any_uncertain,
                  MIN(e.start_at) first_seen, MAX(e.start_at) last_seen,
                  MAX(e.id) last_encounter_id
           FROM encounter e, json_each(e.species_json) j
           WHERE e.status != 'rejected'
           GROUP BY species ORDER BY encounters DESC, species""").fetchall()
    out = [dict(r) for r in rows]
    if not include_pending:
        out = [r for r in out if r["species"] != "pending"]
    for r in out:
        # Portrait: highest-confidence best detection among this species' encounters.
        # encounter.best_detection_id already excludes media that contain a person.
        best = conn.execute(
            f"""SELECT d.frame_id, d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h
                FROM encounter e JOIN detection d ON d.id = e.best_detection_id
                WHERE e.status != 'rejected' AND {SPECIES_MATCH}
                ORDER BY d.confidence DESC LIMIT 1""", (r["species"],)).fetchone()
        r["best_frame_id"] = best["frame_id"] if best else None
        r["best_bbox"] = [best["bbox_x"], best["bbox_y"], best["bbox_w"], best["bbox_h"]] \
            if best else None
    return out


def activity(conn: sqlite3.Connection, settings: Settings, species: str | None = None,
             species_any: list[str] | None = None) -> dict:
    encs = list_encounters(conn, species=species, species_any=species_any, limit=100000)
    tz = ZoneInfo(settings.camera_timezone)
    by_hour, by_day, by_weekday = Counter(), Counter(), Counter()
    for e in encs:
        local = parse_iso(e["start_at"]).astimezone(tz)
        by_hour[local.hour] += 1
        by_day[local.date().isoformat()] += 1
        by_weekday[local.strftime("%a")] += 1
    return {"timezone": settings.camera_timezone, "total": len(encs),
            "by_hour": [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)],
            "by_day": [{"day": d, "count": c} for d, c in sorted(by_day.items())],
            "by_weekday": [{"weekday": w, "count": by_weekday.get(w, 0)}
                           for w in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]],
            "encounter_ids": [e["id"] for e in encs[:50]]}


def stats(conn: sqlite3.Connection) -> dict:
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "media": one("SELECT COUNT(*) FROM media"),
        "media_by_status": {r[0]: r[1] for r in conn.execute(
            "SELECT status, COUNT(*) FROM media GROUP BY status")},
        "encounters": one("SELECT COUNT(*) FROM encounter WHERE status!='rejected'"),
        "species": len(species_summary(conn)),
        "pending_classification": one(
            "SELECT COUNT(*) FROM job WHERE kind='classify' AND status IN ('queued','running')"),
    }


def health_details(conn: sqlite3.Connection, settings: Settings) -> dict:
    now = parse_iso(utcnow())
    try:
        conn.execute("SELECT 1").fetchone()
        db_ok = True
    except sqlite3.Error:
        db_ok = False
    usage = shutil.disk_usage(settings.data_dir)
    disk_pct = round(100 * usage.used / usage.total, 1)
    queues = {f"{r['kind']}:{r['status']}": r["n"] for r in conn.execute(
        "SELECT kind, status, COUNT(*) n FROM job GROUP BY kind, status")}
    workers = []
    for w in conn.execute("SELECT * FROM worker ORDER BY last_seen DESC"):
        age = (now - parse_iso(w["last_seen"])).total_seconds()
        workers.append({"id": w["id"], "kinds": w["kinds"].split(","), "last_seen": w["last_seen"],
                        "online": age < settings.worker_offline_s,
                        "info": json.loads(w["info_json"] or "{}")})
    online_kinds = {k for w in workers if w["online"] for k in w["kinds"]}
    last = lambda sql: (conn.execute(sql).fetchone() or [None])[0]  # noqa: E731
    problems = []
    if not db_ok:
        problems.append("database unavailable")
    if disk_pct >= settings.disk_floor_pct:
        problems.append(f"disk {disk_pct}% full — ingest paused")
    for kind in ("detect", "classify"):
        waiting = queues.get(f"{kind}:queued", 0)
        if waiting and kind not in online_kinds:
            label = "Species classification" if kind == "classify" else "Detection"
            problems.append(f"{label} paused — no {kind} worker online ({waiting} waiting)")
    failed_jobs = sum(v for k, v in queues.items() if k.endswith(":failed"))
    quarantined = len(list(settings.quarantine_dir.glob("*"))) if settings.quarantine_dir.exists() else 0
    if quarantined:
        problems.append(f"{quarantined} file(s) quarantined")
    return {
        "ok": not problems, "problems": problems, "db_ok": db_ok, "disk_pct": disk_pct,
        "disk_free_gb": round(usage.free / 1e9, 2), "queues": queues, "failed_jobs": failed_jobs,
        "workers": workers, "last_ingest": last("SELECT MAX(created_at) FROM media"),
        "last_capture": last("SELECT MAX(captured_at) FROM media"),
        "last_backup": last("SELECT MAX(created_at) FROM backup WHERE verified=1"),
        "alert_backlog": last("SELECT COUNT(*) FROM alert WHERE status='pending'"),
        "alerts_failed": last("SELECT COUNT(*) FROM alert WHERE status='failed'"),
        "quarantined": quarantined,
        "models": [dict(r) for r in conn.execute("SELECT name, version, task FROM model")],
        "settings": {"camera_timezone": settings.camera_timezone, "country": settings.country,
                     "admin1_region": settings.admin1_region,
                     "ntfy_enabled": bool(settings.ntfy_topic)},
    }
