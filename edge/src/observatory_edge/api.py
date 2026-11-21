"""FastAPI app: worker job protocol + dashboard API."""


import json
import logging
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Iterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .backup import latest_backup
from .config import Settings, get_settings
from .corrections import CorrectionError, add_correction
from .db import connect, init_db, tx
from .jobs import claim_job, fail_job, heartbeat, touch_worker, verify_token
from .insights import compute_insights
from .queries import (activity, encounter_frames, get_encounter, health_details, list_encounters,
                      list_media, species_detail, species_summary, stats)
from .results import (ResultError, StaleResult, apply_classify_result, apply_detect_result,
                      classify_inputs)
from .search import answer

log = logging.getLogger("observatory.api")


class ClaimReq(BaseModel):
    kinds: list[str]
    worker_id: str
    capabilities: dict = Field(default_factory=dict)


class TokenReq(BaseModel):
    claim_token: str


class FailReq(BaseModel):
    claim_token: str
    error: str
    retryable: bool = True


class WorkerBeat(BaseModel):
    worker_id: str
    kinds: list[str]
    info: dict = Field(default_factory=dict)


class CorrectionReq(BaseModel):
    target_type: str
    target_id: int
    action: str
    label: str | None = None
    note: str | None = None


class AskReq(BaseModel):
    question: str


def create_app(settings: Settings | None = None, start_background: bool = False) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    boot = connect(settings.db_path)
    init_db(boot)
    boot.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loops = None
        if start_background:
            from .background import BackgroundLoops
            loops = BackgroundLoops(settings)
            loops.start()
        yield
        if loops:
            loops.stop()

    app = FastAPI(title="Wildlife Observatory Edge", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    def get_conn() -> Iterator[sqlite3.Connection]:
        c = connect(settings.db_path)
        try:
            yield c
        finally:
            c.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def worker_auth(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {settings.worker_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, "missing or invalid worker token")

    Auth = Depends(worker_auth)

    def _job(conn, job_id: int) -> dict:
        row = conn.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        return dict(row)

    def _check(conn, job_id: int, token: str) -> dict:
        job = _job(conn, job_id)
        if not verify_token(conn, job_id, token):
            raise HTTPException(409, "stale or invalid claim token")
        return job

    # ---------------------------------------------------------------- worker protocol
    @app.post("/jobs/claim", dependencies=[Auth])
    def claim(req: ClaimReq, conn: Conn, response: Response):
        touch_worker(conn, req.worker_id, req.kinds, json.dumps(req.capabilities))
        job = claim_job(conn, req.kinds, req.worker_id, settings.lease_s, settings.max_attempts)
        if not job:
            response.status_code = 204
            return None
        media = conn.execute("SELECT * FROM media WHERE id=?", (job["media_id"],)).fetchone()
        frames = conn.execute("SELECT id, idx, time_offset_s FROM frame WHERE media_id=? "
                              "ORDER BY idx", (media["id"],)).fetchall()
        out = {
            "job_id": job["id"], "kind": job["kind"], "claim_token": job["claim_token"],
            "lease_s": settings.lease_s,
            "media": {"id": media["id"], "kind": media["kind"],
                      "url": f"/media/{media['id']}/original",
                      "original_name": media["original_name"],
                      "captured_at": media["captured_at"]},
            "frames": [{"frame_id": f["id"], "idx": f["idx"], "time_offset_s": f["time_offset_s"],
                        "url": f"/frames/{f['id']}/file"} for f in frames],
            "geofence": {"country": settings.country, "admin1_region": settings.admin1_region},
        }
        if job["kind"] == "classify":
            out["classify_inputs"] = classify_inputs(conn, settings, media["id"])
        return out

    @app.post("/jobs/{job_id}/heartbeat", dependencies=[Auth])
    def job_heartbeat(job_id: int, req: TokenReq, conn: Conn):
        _job(conn, job_id)
        if not heartbeat(conn, job_id, req.claim_token, settings.lease_s):
            raise HTTPException(409, "stale or invalid claim token")
        return {"ok": True, "lease_s": settings.lease_s}

    @app.post("/jobs/{job_id}/frames", dependencies=[Auth])
    async def upload_frames(job_id: int, conn: Conn,
                            claim_token: Annotated[str, Form()],
                            indexes: Annotated[str, Form()],
                            time_offsets: Annotated[str, Form()],
                            files: Annotated[list[UploadFile], File()]):
        job = _check(conn, job_id, claim_token)
        idxs = [int(x) for x in indexes.split(",") if x != ""]
        offs = [float(x) for x in time_offsets.split(",") if x != ""]
        if not (len(idxs) == len(offs) == len(files)):
            raise HTTPException(422, "indexes, time_offsets and files must align")
        media_id = job["media_id"]
        out_dir = settings.frames_dir / str(media_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        payloads = [await up.read() for up in files]  # read before taking the DB write lock
        result = []
        with tx(conn):
            for i, off, data in zip(idxs, offs, payloads):
                rel = Path("frames") / str(media_id) / f"{i:05d}.jpg"
                (settings.data_dir / rel).write_bytes(data)
                conn.execute(
                    "INSERT INTO frame(media_id, idx, time_offset_s, path) VALUES (?,?,?,?) "
                    "ON CONFLICT(media_id, idx) DO UPDATE SET path=excluded.path, "
                    "time_offset_s=excluded.time_offset_s", (media_id, i, off, str(rel)))
                fid = conn.execute("SELECT id FROM frame WHERE media_id=? AND idx=?",
                                   (media_id, i)).fetchone()["id"]
                result.append({"idx": i, "frame_id": fid})
        return {"frames": result}

    @app.post("/jobs/{job_id}/result", dependencies=[Auth])
    def job_result(job_id: int, payload: dict, conn: Conn):
        job = _check(conn, job_id, payload.get("claim_token", ""))
        try:
            if job["kind"] == "detect":
                return apply_detect_result(conn, settings, job, payload)
            if job["kind"] == "classify":
                return apply_classify_result(conn, settings, job, payload)
        except ResultError as e:
            raise HTTPException(422, str(e)) from e
        except StaleResult as e:
            raise HTTPException(409, str(e)) from e
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, f"malformed result payload: {e}") from e
        raise HTTPException(400, f"unsupported job kind {job['kind']}")

    @app.post("/jobs/{job_id}/fail", dependencies=[Auth])
    def job_fail(job_id: int, req: FailReq, conn: Conn):
        _job(conn, job_id)
        status = fail_job(conn, job_id, req.claim_token, req.error[:2000], req.retryable,
                          settings.max_attempts)
        if status is None:
            raise HTTPException(409, "stale or invalid claim token")
        return {"status": status}

    @app.post("/workers/heartbeat", dependencies=[Auth])
    def worker_heartbeat(req: WorkerBeat, conn: Conn):
        touch_worker(conn, req.worker_id, req.kinds, json.dumps(req.info))
        return {"ok": True}

    # ---------------------------------------------------------------- files
    def _file(path_rel: str) -> FileResponse:
        p = (settings.data_dir / path_rel).resolve()
        if not str(p).startswith(str(settings.data_dir.resolve())) or not p.exists():
            raise HTTPException(404, "file not found")
        return FileResponse(p)

    @app.get("/media/{media_id}/original")
    def media_original(media_id: int, conn: Conn):
        m = conn.execute("SELECT original_path FROM media WHERE id=?", (media_id,)).fetchone()
        if not m:
            raise HTTPException(404, "media not found")
        return _file(m["original_path"])

    @app.get("/frames/{frame_id}/file")
    def frame_file(frame_id: int, conn: Conn):
        f = conn.execute("SELECT path FROM frame WHERE id=?", (frame_id,)).fetchone()
        if not f:
            raise HTTPException(404, "frame not found")
        return _file(f["path"])

    # ---------------------------------------------------------------- dashboard API
    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/health/details")
    def health_full(conn: Conn):
        return health_details(conn, settings)

    @app.get("/api/stats")
    def api_stats(conn: Conn):
        return stats(conn)

    @app.get("/api/encounters")
    def api_encounters(conn: Conn, species: str | None = None, date_from: str | None = None,
                       date_to: str | None = None, uncertain: bool | None = None,
                       status: str | None = None, limit: int = 50, offset: int = 0):
        return list_encounters(conn, species=species, date_from=date_from, date_to=date_to,
                               uncertain=uncertain, status=status, limit=min(limit, 500),
                               offset=offset)

    @app.get("/api/encounters/{encounter_id}")
    def api_encounter(encounter_id: int, conn: Conn):
        enc = get_encounter(conn, encounter_id)
        if not enc:
            raise HTTPException(404, "encounter not found")
        return enc

    @app.get("/api/encounters/{encounter_id}/frames")
    def api_encounter_frames(encounter_id: int, conn: Conn):
        if not conn.execute("SELECT 1 FROM encounter WHERE id=?", (encounter_id,)).fetchone():
            raise HTTPException(404, "encounter not found")
        return encounter_frames(conn, encounter_id)

    @app.get("/api/insights")
    def api_insights(conn: Conn, species: str | None = None):
        return [i.to_dict() for i in compute_insights(conn, settings, species=species, use_cache=True)]

    @app.get("/api/species/{name}")
    def api_species_detail(name: str, conn: Conn):
        d = species_detail(conn, settings, name)
        if not d:
            raise HTTPException(404, "no visits from that species")
        return d

    @app.get("/api/species/{name}/image")
    def api_species_image(name: str, conn: Conn):
        r = conn.execute("SELECT thumbnail_path FROM species_info WHERE common_name=?",
                         (name,)).fetchone()
        if not r or not r["thumbnail_path"]:
            raise HTTPException(404, "no image cached")
        return _file(r["thumbnail_path"])

    @app.get("/api/milestones")
    def api_milestones(conn: Conn, limit: int = 20):
        return [dict(r) for r in conn.execute(
            "SELECT id, kind, species, encounter_id, text, night, status, created_at FROM milestone "
            "WHERE status != 'withdrawn' ORDER BY night DESC, id DESC LIMIT ?", (min(limit, 200),))]

    @app.get("/api/digests")
    def api_digests(conn: Conn):
        return [{"week": r["week"], "sent_at": r["sent_at"], **{k: json.loads(r["payload_json"]).get(k)
                 for k in ("headline", "visits", "species", "best_frame_id", "start", "end")}}
                for r in conn.execute("SELECT * FROM digest ORDER BY week DESC LIMIT 104")]

    @app.get("/api/digests/current")
    def api_digest_current(conn: Conn):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from .digest import build_digest
        now = datetime.now(ZoneInfo(settings.camera_timezone))
        return {**build_digest(conn, settings, (now - timedelta(days=now.weekday())).date()),
                "in_progress": True}

    @app.get("/api/digests/{week}")
    def api_digest(week: str, conn: Conn):
        r = conn.execute("SELECT * FROM digest WHERE week=?", (week,)).fetchone()
        if not r:
            raise HTTPException(404, "no digest for that week")
        return {**json.loads(r["payload_json"]), "sent_at": r["sent_at"]}

    @app.get("/api/media")
    def api_media(conn: Conn, status: str | None = None, kind: str | None = None,
                  species: str | None = None, include_person: bool = False, limit: int = 60,
                  offset: int = 0):
        return list_media(conn, status=status, kind=kind, species=species,
                          include_person=include_person, limit=min(limit, 500), offset=offset)

    @app.get("/api/species")
    def api_species(conn: Conn):
        return species_summary(conn)

    @app.get("/api/activity")
    def api_activity(conn: Conn, species: str | None = None):
        return activity(conn, settings, species=species)

    @app.post("/api/corrections")
    def api_correction(req: CorrectionReq, conn: Conn):
        try:
            cid = add_correction(conn, settings, req.target_type, req.target_id, req.action,
                                 req.label, req.note)
        except CorrectionError as e:
            raise HTTPException(422, str(e)) from e
        return {"id": cid}

    @app.get("/api/labels")
    def api_labels(conn: Conn, q: str = ""):
        rows = conn.execute(
            "SELECT DISTINCT common_name FROM classification WHERE common_name LIKE ? "
            "ORDER BY common_name LIMIT 50", (f"%{q.lower()}%",)).fetchall()
        return [r[0] for r in rows]

    @app.post("/api/ask")
    def api_ask(req: AskReq, conn: Conn):
        a = answer(conn, settings, req.question)
        return {"text": a.text, "intent": a.intent, "rows": a.rows, "sources": a.sources}

    @app.get("/api/backups/latest", dependencies=[Auth])
    def api_backup_latest():
        b = latest_backup(settings)
        if not b:
            raise HTTPException(404, "no verified backup yet")
        return FileResponse(b, headers={"x-backup-name": b.name})

    return app
