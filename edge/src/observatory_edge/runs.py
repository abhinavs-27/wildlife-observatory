"""Model + inference run provenance helpers."""

from __future__ import annotations

import json
import sqlite3

from .db import utcnow


def get_or_create_model(conn: sqlite3.Connection, name: str, version: str, task: str,
                        params: dict | None = None) -> int:
    row = conn.execute("SELECT id FROM model WHERE name=? AND version=? AND task=?",
                       (name, version, task)).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO model(name, version, task, params_json) VALUES (?,?,?,?)",
        (name, version, task, json.dumps(params or {}))).lastrowid


def get_live_run(conn: sqlite3.Connection, name: str, version: str, task: str,
                 params: dict | None = None) -> int:
    """One long-lived 'live' run per model; reprocessing creates scoped runs instead."""
    model_id = get_or_create_model(conn, name, version, task, params)
    row = conn.execute(
        "SELECT id FROM inference_run WHERE model_id=? AND scope='live' ORDER BY id LIMIT 1",
        (model_id,)).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO inference_run(model_id, scope, status, started_at) VALUES (?, 'live', "
        "'running', ?)", (model_id, utcnow())).lastrowid
