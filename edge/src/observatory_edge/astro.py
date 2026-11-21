"""Sun and moon, computed locally (no network). NOAA simplified solar equations."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SYNODIC_DAYS = 29.530588853
NEW_MOON_2000 = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def sun_times(d: date, lat: float, lon: float, tz: str) -> tuple[datetime, datetime]:
    """Return (sunrise, sunset) for local date `d`, as aware datetimes in `tz`."""
    n = d.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    phi = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl))
              - math.tan(phi) * math.tan(decl))
    cos_ha = max(-1.0, min(1.0, cos_ha))  # polar day/night clamp
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    rise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    set_ = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    z = ZoneInfo(tz)
    return rise.astimezone(z), set_.astimezone(z)


def moon_illumination(dt: datetime) -> float:
    """Fraction of the moon's disc lit (0 new … 1 full), synodic approximation."""
    age = ((dt - NEW_MOON_2000).total_seconds() / 86400) % SYNODIC_DAYS
    return (1 - math.cos(2 * math.pi * age / SYNODIC_DAYS)) / 2


def night_of(ts: datetime, tz: str) -> date:
    """The evening a visit belongs to: anything before local noon counts as the previous night."""
    local = ts.astimezone(ZoneInfo(tz))
    return (local - timedelta(days=1)).date() if local.hour < 12 else local.date()
