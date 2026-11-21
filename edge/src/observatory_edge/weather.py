"""Optional daily weather history from Open-Meteo (free, no key). Opt-in: WEATHER_ENABLED=true.

This is the only feature that sends (approximate) location off the Pi; coordinates are rounded
to 2 decimals (~1 km).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta

import httpx

from .config import Settings

log = logging.getLogger("observatory.weather")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather(conn: sqlite3.Connection, settings: Settings, start: date, end: date,
                  client: httpx.Client | None = None) -> int:
    if not settings.weather_enabled or start > end:
        return 0
    params = {
        "latitude": round(settings.camera_lat, 2), "longitude": round(settings.camera_lon, 2),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "precipitation_sum,temperature_2m_min,temperature_2m_max",
        "timezone": settings.camera_timezone,
    }
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.get(ARCHIVE, params=params, headers={"User-Agent": "wildlife-observatory/0.1"})
        r.raise_for_status()
        daily = r.json().get("daily") or {}
    finally:
        if own:
            client.close()
    rows = list(zip(daily.get("time", []), daily.get("precipitation_sum", []),
                    daily.get("temperature_2m_min", []), daily.get("temperature_2m_max", [])))
    conn.executemany(
        "INSERT INTO weather_daily(date, precip_mm, tmin_c, tmax_c) VALUES (?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET precip_mm=excluded.precip_mm, tmin_c=excluded.tmin_c, "
        "tmax_c=excluded.tmax_c", rows)
    return len(rows)


def backfill_weather(conn: sqlite3.Connection, settings: Settings, today: date,
                     client: httpx.Client | None = None) -> int:
    """Fill missing days from the first visit (max one year back) to 2 days ago."""
    if not settings.weather_enabled:
        return 0
    first = conn.execute("SELECT MIN(start_at) FROM encounter").fetchone()[0]
    if not first:
        return 0
    start = max(date.fromisoformat(first[:10]), today - timedelta(days=365))
    end = today - timedelta(days=2)  # the archive lags a couple of days
    have = conn.execute("SELECT MAX(date) FROM weather_daily").fetchone()[0]
    if have and date.fromisoformat(have) >= start:
        start = date.fromisoformat(have) + timedelta(days=1)
    try:
        return fetch_weather(conn, settings, start, end, client)
    except httpx.HTTPError as e:
        log.info("weather fetch failed: %s", e)
        return 0
