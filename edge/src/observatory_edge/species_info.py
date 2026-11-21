"""General information about each species: cached Wikipedia summaries + bundled facts.

Only species names leave the Pi (no location, no user data). Everything is cached so the
dashboard works offline. If Wikipedia can't be reached, the UI says so; nothing is guessed.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from functools import lru_cache
from importlib import resources
from urllib.parse import quote

import httpx

from .config import Settings
from .db import parse_iso, utcnow

log = logging.getLogger("observatory.species_info")
WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HEADERS = {"User-Agent": "wildlife-observatory/0.1 (backyard camera-trap hobby project)"}
REFRESH_DAYS = 90


@lru_cache(maxsize=1)
def _facts() -> dict:
    raw = resources.files("observatory_edge").joinpath("data/species_facts.json").read_text()
    return json.loads(raw)["species"]


def _taxon(conn: sqlite3.Connection, common_name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT taxon_class, taxon_order, taxon_family, taxon_genus, taxon_species "
        "FROM classification WHERE common_name=? ORDER BY score DESC LIMIT 1",
        (common_name,)).fetchone()


def binomial(conn: sqlite3.Connection, common_name: str) -> str | None:
    t = _taxon(conn, common_name)
    if t and t["taxon_genus"] and t["taxon_species"]:
        return f"{t['taxon_genus']} {t['taxon_species']}"
    return None


def facts_for(conn: sqlite3.Connection, common_name: str) -> dict | None:
    b = binomial(conn, common_name)
    return _facts().get(b) if b else None


def wiki_candidates(conn: sqlite3.Connection, common_name: str) -> list[str]:
    """Most specific first: binomial → genus → family → order → common name."""
    out: list[str] = []
    t = _taxon(conn, common_name)
    if t:
        if t["taxon_genus"] and t["taxon_species"]:
            out.append(f"{t['taxon_genus'].capitalize()} {t['taxon_species']}")
        for col in ("taxon_genus", "taxon_family", "taxon_order"):
            if t[col] and not out:
                out.append(t[col].capitalize())
    name = re.sub(r"\b(family|species|order|genus)\b", "", common_name).strip()
    if name and name.lower() not in {"animal", "unknown", "blank", "mammal", "bird"}:
        out.append(name.capitalize())
    elif name.lower() in {"mammal", "bird"}:
        out.append(name.capitalize())
    seen, uniq = set(), []
    for c in out:
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append(c)
    return uniq


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch_species_info(conn: sqlite3.Connection, settings: Settings, common_name: str,
                       client: httpx.Client) -> str:
    """Fetch and cache one species. Returns status: ok | missing | error."""
    status, last_err = "missing", None
    for title in wiki_candidates(conn, common_name):
        try:
            r = client.get(WIKI + quote(title.replace(" ", "_")), headers=HEADERS, timeout=15,
                           follow_redirects=True)
        except httpx.HTTPError as e:
            status, last_err = "error", str(e)
            break
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            status, last_err = "error", f"HTTP {r.status_code}"
            break
        data = r.json()
        if data.get("type") == "disambiguation" or not data.get("extract"):
            continue
        thumb_rel = None
        src = (data.get("thumbnail") or {}).get("source")
        if src:
            try:
                img = client.get(src, headers=HEADERS, timeout=20, follow_redirects=True)
                if img.status_code == 200 and img.headers.get("content-type", "").startswith("image/"):
                    d = settings.data_dir / "species"
                    d.mkdir(parents=True, exist_ok=True)
                    path = d / f"{_slug(common_name)}.jpg"
                    path.write_bytes(img.content)
                    thumb_rel = str(path.relative_to(settings.data_dir))
            except httpx.HTTPError as e:
                log.info("thumbnail fetch failed for %s: %s", common_name, e)
        conn.execute(
            "INSERT INTO species_info(common_name, wiki_title, extract, page_url, thumbnail_path, "
            "status, fetched_at) VALUES (?,?,?,?,?, 'ok', ?) ON CONFLICT(common_name) DO UPDATE "
            "SET wiki_title=excluded.wiki_title, extract=excluded.extract, page_url=excluded.page_url, "
            "thumbnail_path=COALESCE(excluded.thumbnail_path, species_info.thumbnail_path), "
            "status='ok', fetched_at=excluded.fetched_at",
            (common_name, data.get("title"), data.get("extract"),
             ((data.get("content_urls") or {}).get("desktop") or {}).get("page"), thumb_rel,
             utcnow()))
        return "ok"
    # Keep any previously good content; only record the failure status when we have nothing.
    conn.execute(
        "INSERT INTO species_info(common_name, status, fetched_at) VALUES (?,?,?) "
        "ON CONFLICT(common_name) DO UPDATE SET status=CASE WHEN species_info.status='ok' "
        "THEN 'ok' ELSE excluded.status END, fetched_at=excluded.fetched_at",
        (common_name, status, utcnow()))
    if last_err:
        log.info("species info for %s: %s", common_name, last_err)
    return status


def refresh_species_info(conn: sqlite3.Connection, settings: Settings,
                         client: httpx.Client | None = None, limit: int = 20) -> int:
    """Fetch info for species we don't have yet, that failed, or that are stale."""
    names = [r[0] for r in conn.execute(
        "SELECT DISTINCT json_extract(j.value,'$.species') FROM encounter e, "
        "json_each(e.species_json) j WHERE e.status != 'rejected'")]
    names = [n for n in names if n and n != "pending"]
    todo = []
    for n in names:
        row = conn.execute("SELECT status, fetched_at FROM species_info WHERE common_name=?",
                           (n,)).fetchone()
        if not row or row["status"] in ("pending", "error"):
            todo.append(n)
        elif row["fetched_at"] and (parse_iso(utcnow()) - parse_iso(row["fetched_at"])).days > REFRESH_DAYS:
            todo.append(n)
    own = client is None
    client = client or httpx.Client()
    try:
        done = 0
        for n in todo[:limit]:
            if fetch_species_info(conn, settings, n, client) == "error":
                break  # probably offline; try again later
            done += 1
        return done
    finally:
        if own:
            client.close()


def get_species_info(conn: sqlite3.Connection, settings: Settings, common_name: str) -> dict:
    row = conn.execute("SELECT * FROM species_info WHERE common_name=?", (common_name,)).fetchone()
    info = dict(row) if row else {"common_name": common_name, "status": "pending"}
    info["has_image"] = bool(row and row["thumbnail_path"]
                             and (settings.data_dir / row["thumbnail_path"]).exists())
    info["scientific_name"] = binomial(conn, common_name)
    info["facts"] = facts_for(conn, common_name)
    return info
