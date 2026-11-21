"""SQLite online backups with integrity check + rotation, and pulling backups to another machine."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import Settings
from .db import utcnow


def create_backup(conn: sqlite3.Connection, settings: Settings) -> Path:
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = settings.backups_dir / f"observatory-{stamp}.sqlite"
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    finally:
        target.close()
    ok = verify_backup(dest)
    conn.execute("INSERT INTO backup(path, size, verified, created_at) VALUES (?,?,?,?)",
                 (str(dest), dest.stat().st_size, int(ok), utcnow()))
    rotate(settings)
    if not ok:
        raise RuntimeError(f"backup {dest} failed integrity check")
    return dest


def verify_backup(path: Path) -> bool:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.execute("SELECT COUNT(*) FROM media").fetchone()
        c.close()
        return ok
    except sqlite3.Error:
        return False


def rotate(settings: Settings) -> list[Path]:
    files = sorted(settings.backups_dir.glob("observatory-*.sqlite"))
    doomed = files[: max(0, len(files) - settings.backups_keep)]
    for f in doomed:
        f.unlink(missing_ok=True)
    return doomed


def latest_backup(settings: Settings) -> Path | None:
    files = sorted(settings.backups_dir.glob("observatory-*.sqlite"))
    for f in reversed(files):
        if verify_backup(f):
            return f
    return None


def restore_backup(backup: Path, db_path: Path) -> None:
    """Restore by copying a verified backup over the DB (edge must be stopped)."""
    if not verify_backup(backup):
        raise RuntimeError("refusing to restore a backup that fails integrity_check")
    src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    dst = sqlite3.connect(str(db_path))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def pull_backup(edge_url: str, token: str, dest_dir: Path) -> Path:
    """Run on the Mac: fetch the edge's latest verified backup over Tailscale."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", f"{edge_url.rstrip('/')}/api/backups/latest",
                      headers={"Authorization": f"Bearer {token}"}, timeout=300) as r:
        r.raise_for_status()
        name = r.headers.get("x-backup-name") or "observatory-latest.sqlite"
        tmp = dest_dir / (name + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    final = dest_dir / name
    tmp.replace(final)
    if not verify_backup(final):
        raise RuntimeError(f"pulled backup {final} failed integrity check")
    return final
