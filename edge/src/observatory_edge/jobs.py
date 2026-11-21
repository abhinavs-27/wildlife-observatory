"""Job queue with leases and claim tokens. One job = one media item."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import timedelta

from .db import parse_iso, to_iso, tx, utcnow


def _now_plus(seconds: float) -> str:
    return to_iso(parse_iso(utcnow()) + timedelta(seconds=seconds))


def enqueue(conn: sqlite3.Connection, kind: str, media_id: int, priority: int = 0) -> int:
    existing = conn.execute(
        "SELECT id FROM job WHERE kind=? AND media_id=? AND status IN ('queued','running')",
        (kind, media_id)).fetchone()
    if existing:
        return existing["id"]
    now = utcnow()
    return conn.execute(
        "INSERT INTO job(kind, media_id, priority, created_at, updated_at) VALUES (?,?,?,?,?)",
        (kind, media_id, priority, now, now)).lastrowid


def requeue_expired(conn: sqlite3.Connection, max_attempts: int = 3) -> int:
    """Expired leases count as a failed attempt, so a job that crashes its worker every time
    (e.g. an OOM on a huge video) ends up `failed` instead of looping forever."""
    now = utcnow()
    expired = conn.execute(
        "SELECT id, kind, media_id, attempts FROM job WHERE status='running' AND lease_until < ?",
        (now,)).fetchall()
    for j in expired:
        attempts = j["attempts"] + 1
        if attempts >= max_attempts:
            conn.execute(
                "UPDATE job SET status='failed', attempts=?, error='lease expired repeatedly "
                "(worker crashed or hung)', claim_token=NULL, lease_until=NULL, updated_at=? "
                "WHERE id=?", (attempts, now, j["id"]))
            if j["kind"] == "detect":
                conn.execute("UPDATE media SET status='failed', error='worker crashed or hung "
                             "repeatedly on this file' WHERE id=?", (j["media_id"],))
        else:
            conn.execute(
                "UPDATE job SET status='queued', attempts=?, claim_token=NULL, worker_id=NULL, "
                "lease_until=NULL, updated_at=? WHERE id=?", (attempts, now, j["id"]))
    return len(expired)


def claim_job(conn: sqlite3.Connection, kinds: list[str], worker_id: str,
              lease_s: int, max_attempts: int = 3) -> dict | None:
    if not kinds:
        return None
    now = utcnow()
    with tx(conn):
        requeue_expired(conn, max_attempts)
        marks = ",".join("?" * len(kinds))
        row = conn.execute(
            f"SELECT id FROM job WHERE status='queued' AND kind IN ({marks}) "
            "AND (not_before IS NULL OR not_before <= ?) "
            "ORDER BY priority DESC, id LIMIT 1", (*kinds, now)).fetchone()
        if not row:
            return None
        token = secrets.token_urlsafe(16)
        conn.execute(
            "UPDATE job SET status='running', claim_token=?, worker_id=?, lease_until=?, "
            "updated_at=? WHERE id=?", (token, worker_id, _now_plus(lease_s), now, row["id"]))
        job = conn.execute("SELECT * FROM job WHERE id=?", (row["id"],)).fetchone()
    return dict(job)


def verify_token(conn: sqlite3.Connection, job_id: int, token: str) -> bool:
    row = conn.execute("SELECT status, claim_token FROM job WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["status"] == "running" and token
                and secrets.compare_digest(row["claim_token"] or "", token))


def heartbeat(conn: sqlite3.Connection, job_id: int, token: str, lease_s: int) -> bool:
    if not verify_token(conn, job_id, token):
        return False
    conn.execute("UPDATE job SET lease_until=?, updated_at=? WHERE id=?",
                 (_now_plus(lease_s), utcnow(), job_id))
    return True


def complete_job(conn: sqlite3.Connection, job_id: int, timings_json: str | None = None) -> None:
    conn.execute(
        "UPDATE job SET status='done', claim_token=NULL, lease_until=NULL, timings_json=?, "
        "updated_at=? WHERE id=? AND status='running'", (timings_json, utcnow(), job_id))


def fail_job(conn: sqlite3.Connection, job_id: int, token: str, error: str, retryable: bool,
             max_attempts: int) -> str | None:
    """Returns the new status, or None when the token is stale."""
    with tx(conn):
        if not verify_token(conn, job_id, token):
            return None
        job = conn.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
        attempts = job["attempts"] + 1
        if retryable and attempts < max_attempts:
            backoff = 30 * (2 ** (attempts - 1))
            conn.execute(
                "UPDATE job SET status='queued', attempts=?, error=?, claim_token=NULL, "
                "worker_id=NULL, lease_until=NULL, not_before=?, updated_at=? WHERE id=?",
                (attempts, error, _now_plus(backoff), utcnow(), job_id))
            return "queued"
        conn.execute(
            "UPDATE job SET status='failed', attempts=?, error=?, claim_token=NULL, "
            "lease_until=NULL, updated_at=? WHERE id=?", (attempts, error, utcnow(), job_id))
        if job["kind"] == "detect":
            conn.execute("UPDATE media SET status='failed', error=? WHERE id=?",
                         (error, job["media_id"]))
        return "failed"


def touch_worker(conn: sqlite3.Connection, worker_id: str, kinds: list[str],
                 info_json: str = "{}") -> None:
    conn.execute(
        "INSERT INTO worker(id, kinds, info_json, last_seen) VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET kinds=excluded.kinds, info_json=excluded.info_json, "
        "last_seen=excluded.last_seen", (worker_id, ",".join(kinds), info_json, utcnow()))
