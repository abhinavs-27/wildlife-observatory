"""Rule-based insights: plain-English patterns computed from stored visits.

Every rule has a minimum amount of data and says how many visits it is based on. If nothing
clears its minimum we return nothing — the UI then says there isn't enough data yet.
Uncertain classifications never count toward species-specific insights.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

from .astro import moon_illumination, night_of, sun_times
from .config import Settings
from .db import parse_iso

MIN_TIMING = 5
MIN_TREND = 6
MIN_MOON_VISITS, MIN_MOON_NIGHTS = 10, 5
MIN_REGULAR = 4
MIN_TOGETHER = 3
MIN_WEEKS = 4
MIN_RAIN_NIGHTS = 10


@dataclass
class Insight:
    id: str
    kind: str
    species: str | None
    text: str
    detail: str
    n: int
    encounter_ids: list[int] = field(default_factory=list)
    strength: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Visit:
    encounter_id: int
    species: str
    t: datetime          # UTC
    uncertain: bool


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _dur(minutes: float) -> str:
    m = abs(minutes)
    if m < 50:
        return f"{int(round(m / 5) * 5) or 5} min"
    h = round(m / 30) / 2
    return f"{h:g} h"


def _clock(minute: int) -> str:
    minute %= 1440
    h, mm = divmod(minute, 60)
    hh = 12 if h % 12 == 0 else h % 12
    return f"{hh}{f':{mm:02d}' if mm else ''} {'am' if h < 12 else 'pm'}"


def load_visits(conn: sqlite3.Connection) -> list[Visit]:
    out = []
    for r in conn.execute("SELECT id, start_at, species_json FROM encounter WHERE status != 'rejected'"):
        for s in json.loads(r["species_json"]):
            if s["species"] == "pending":
                continue
            out.append(Visit(r["id"], s["species"], parse_iso(r["start_at"]), bool(s.get("uncertain"))))
    return out


def _timing_vs_sun(species: str, vs: list[Visit], s: Settings) -> Insight | None:
    if len(vs) < MIN_TIMING:
        return None
    tz = s.camera_timezone
    night_offsets, day_offsets = [], []
    for v in vs:
        n = night_of(v.t, tz)
        _, sunset = sun_times(n, s.camera_lat, s.camera_lon, tz)
        sunrise_next, _ = sun_times(n + timedelta(days=1), s.camera_lat, s.camera_lon, tz)
        local = v.t.astimezone(ZoneInfo(tz))
        if sunset <= local < sunrise_next:
            night_offsets.append((local - sunset).total_seconds() / 60)
        else:
            d = local.date()
            sunrise, _ = sun_times(d, s.camera_lat, s.camera_lon, tz)
            day_offsets.append((local - sunrise).total_seconds() / 60)
    ids = [v.encounter_id for v in vs]
    if len(night_offsets) >= 0.6 * len(vs) and len(night_offsets) >= MIN_TIMING:
        med = statistics.median(night_offsets)
        return Insight(f"timing:{species}", "timing_vs_sun", species,
                       f"{_cap(species)} visits usually start about {_dur(med)} after sunset.",
                       f"Median of {len(night_offsets)} night-time visits, using sunset times for "
                       f"the camera's location.", len(vs), ids, 0.6 + len(night_offsets) / 100)
    if len(day_offsets) >= 0.6 * len(vs) and len(day_offsets) >= MIN_TIMING:
        med = statistics.median(day_offsets)
        when = "after sunrise" if med >= 0 else "before sunrise"
        return Insight(f"timing:{species}", "timing_vs_sun", species,
                       f"{_cap(species)} visits usually come about {_dur(med)} {when}.",
                       f"Median of {len(day_offsets)} daytime visits.", len(vs), ids,
                       0.55 + len(day_offsets) / 100)
    return None


def _usual_time(species: str, vs: list[Visit], s: Settings) -> Insight | None:
    if len(vs) < MIN_TIMING:
        return None
    tz = ZoneInfo(s.camera_timezone)
    mins = [v.t.astimezone(tz).hour * 60 + v.t.astimezone(tz).minute for v in vs]
    need = 0.6 * len(mins)
    for length in range(60, 361, 30):
        best = None
        for start in range(0, 1440, 30):
            inside = sum(1 for m in mins if (m - start) % 1440 < length)
            if inside >= need and (best is None or inside > best[1]):
                best = (start, inside)
        if best:
            start, inside = best
            return Insight(f"usual:{species}", "usual_time", species,
                           f"{_cap(species)} mostly visit between {_clock(start)} and "
                           f"{_clock(start + length)}.",
                           f"{inside} of {len(mins)} visits fall in this {length // 60}"
                           f"{'.5' if length % 60 else ''}-hour window.",
                           len(vs), [v.encounter_id for v in vs], 0.5 + inside / len(mins) / 4)
    return None


def _trend(species: str, vs: list[Visit], now: datetime) -> Insight | None:
    recent = [v for v in vs if now - timedelta(days=30) <= v.t <= now]
    before = [v for v in vs if now - timedelta(days=60) <= v.t < now - timedelta(days=30)]
    a, b = len(recent), len(before)
    if a + b < MIN_TREND:
        return None
    ratio = (a / b) if b else float("inf")
    if 0.67 < ratio < 1.5:
        return None
    if ratio >= 1.5:
        word = "doubled" if 1.9 <= ratio < 2.5 else ("tripled" if 2.8 <= ratio < 3.5 else "are up")
        text = f"{_cap(species)} visits {word} in the last 30 days ({a} vs {b} the month before)."
    else:
        word = "halved" if 0.4 <= ratio <= 0.55 else "are down"
        text = f"{_cap(species)} visits {word} in the last 30 days ({a} vs {b} the month before)."
    return Insight(f"trend:{species}:{now:%Y-%m}", "trend", species, text,
                   "Compares the last 30 days with the 30 days before.", a + b,
                   [v.encounter_id for v in recent + before],
                   0.8 + min(abs((a - b)) / max(a + b, 1), 1) / 5)


def _moon(species: str, vs: list[Visit], s: Settings) -> Insight | None:
    if len(vs) < MIN_MOON_VISITS:
        return None
    tz = s.camera_timezone
    nights = sorted({night_of(v.t, tz) for v in vs})
    first, last = nights[0], nights[-1]
    bright, dark = [], []
    d = first
    while d <= last:
        midnight = datetime(d.year, d.month, d.day, 23, 59, tzinfo=ZoneInfo(tz))
        il = moon_illumination(midnight.astimezone(timezone.utc))
        if il > 0.6:
            bright.append(d)
        elif il < 0.4:
            dark.append(d)
        d += timedelta(days=1)
    if len(bright) < MIN_MOON_NIGHTS or len(dark) < MIN_MOON_NIGHTS:
        return None
    per_night = defaultdict(int)
    for v in vs:
        per_night[night_of(v.t, tz)] += 1
    rb = sum(per_night[d] for d in bright) / len(bright)
    rd = sum(per_night[d] for d in dark) / len(dark)
    if rb == rd or min(rb, rd) == 0 and max(rb, rd) < 0.2:
        return None
    hi, lo = max(rb, rd), min(rb, rd)
    if lo > 0 and hi / lo < 1.5:
        return None
    which = "bright-moon" if rb > rd else "dark, moonless"
    return Insight(f"moon:{species}", "moon", species,
                   f"{_cap(species)} came more often on {which} nights "
                   f"({hi:.2f} vs {lo:.2f} visits per night).",
                   f"Over {len(bright)} bright and {len(dark)} dark nights between {first} and {last}.",
                   len(vs), [v.encounter_id for v in vs], 0.7)


def _regular(species: str, vs: list[Visit], s: Settings, now: datetime) -> Insight | None:
    tz = s.camera_timezone
    last_night = night_of(now, tz)
    window = {last_night - timedelta(days=i) for i in range(7)}
    hits = {night_of(v.t, tz) for v in vs} & window
    if len(hits) < MIN_REGULAR:
        return None
    ids = [v.encounter_id for v in vs if night_of(v.t, tz) in window]
    return Insight(f"regular:{species}:{last_night}", "regular", species,
                   f"The {species} has visited {len(hits)} of the last 7 nights.",
                   "Counts distinct nights with at least one visit.", len(ids), ids, 0.9)


def _together(vs: list[Visit], s: Settings) -> list[Insight]:
    tz = s.camera_timezone
    nights: dict[str, set] = defaultdict(set)
    ids: dict[str, list[int]] = defaultdict(list)
    for v in vs:
        nights[v.species].add(night_of(v.t, tz))
        ids[v.species].append(v.encounter_id)
    out = []
    for a, b in combinations(sorted(nights), 2):
        both = nights[a] & nights[b]
        either = nights[a] | nights[b]
        if len(both) >= MIN_TOGETHER and len(both) / len(either) >= 0.4:
            out.append(Insight(f"together:{a}:{b}", "together", None,
                               f"{_cap(a)} and {b} often visit on the same nights "
                               f"({len(both)} shared nights).",
                               f"{len(both)} of {len(either)} nights with either species had both.",
                               len(ids[a]) + len(ids[b]), ids[a] + ids[b],
                               0.6 + len(both) / len(either) / 4))
    return out


def _week_activity(vs: list[Visit], now: datetime) -> Insight | None:
    if not vs:
        return None
    first = min(v.t for v in vs)
    if (now - first).days < MIN_WEEKS * 7:
        return None
    this_week = [v for v in vs if now - timedelta(days=7) <= v.t <= now]
    weeks = []
    for i in range(1, 9):
        lo, hi = now - timedelta(days=7 * (i + 1)), now - timedelta(days=7 * i)
        if hi < first:
            break
        weeks.append(len({v.encounter_id for v in vs if lo <= v.t < hi}))
    if len(weeks) < MIN_WEEKS:
        return None
    usual = statistics.median(weeks)
    n = len({v.encounter_id for v in this_week})
    if usual >= 2 and n <= 0.5 * usual:
        text = f"A quiet week: {n} visit{'s' if n != 1 else ''}, versus a usual {usual:g}."
    elif n >= max(1.5 * usual, usual + 3):
        text = f"A busy week: {n} visits, versus a usual {usual:g}."
    else:
        return None
    return Insight(f"week:{now:%G-W%V}", "quiet", None, text,
                   f"Compared with the median of the previous {len(weeks)} weeks.", n,
                   [v.encounter_id for v in this_week], 0.85)


def _rain(conn: sqlite3.Connection, vs: list[Visit], s: Settings) -> Insight | None:
    rows = conn.execute("SELECT date, precip_mm FROM weather_daily").fetchall()
    if not rows:
        return None
    tz = s.camera_timezone
    per_night = defaultdict(int)
    for v in vs:
        per_night[night_of(v.t, tz).isoformat()] += 1
    wet = [r["date"] for r in rows if (r["precip_mm"] or 0) >= 1.0]
    dry = [r["date"] for r in rows if (r["precip_mm"] or 0) < 0.2]
    if len(wet) < MIN_RAIN_NIGHTS or len(dry) < MIN_RAIN_NIGHTS:
        return None
    rw = sum(per_night[d] for d in wet) / len(wet)
    rd = sum(per_night[d] for d in dry) / len(dry)
    hi, lo = max(rw, rd), min(rw, rd)
    if hi == 0 or (lo > 0 and hi / lo < 1.5):
        return None
    word = "Fewer" if rw < rd else "More"
    return Insight("rain", "rain", None,
                   f"{word} visits on rainy days ({rw:.1f} vs {rd:.1f} per day).",
                   f"{len(wet)} rainy and {len(dry)} dry days, from Open-Meteo weather history.",
                   len(vs), [], 0.75)


_cache: dict[tuple, tuple[float, list[Insight]]] = {}


def compute_insights(conn: sqlite3.Connection, settings: Settings, species: str | None = None,
                     now: datetime | None = None, use_cache: bool = False) -> list[Insight]:
    key = (str(settings.db_path), species)
    if use_cache and key in _cache and time.time() - _cache[key][0] < 600:
        return _cache[key][1]
    now_given = now
    now = now or datetime.now(timezone.utc)
    visits = load_visits(conn)
    confident = [v for v in visits if not v.uncertain]
    by_sp: dict[str, list[Visit]] = defaultdict(list)
    for v in confident:
        by_sp[v.species].append(v)
    targets = [species] if species else sorted(by_sp)
    out: list[Insight] = []
    for sp in targets:
        vs = by_sp.get(sp, [])
        for rule in (lambda: _timing_vs_sun(sp, vs, settings), lambda: _usual_time(sp, vs, settings),
                     lambda: _trend(sp, vs, now), lambda: _moon(sp, vs, settings),
                     lambda: _regular(sp, vs, settings, now)):
            ins = rule()
            if ins:
                out.append(ins)
    together = _together(confident, settings)
    out += [t for t in together if species is None or species in t.id.split(":")[1:]]
    if species is None:
        for ins in (_week_activity(visits, now), _rain(conn, visits, settings)):
            if ins:
                out.append(ins)
    if species is None:  # on the overview, one timing-style insight per species is plenty
        seen = set()
        trimmed = []
        for ins in sorted(out, key=lambda i: -i.strength):
            k = (ins.species, ins.kind in ("timing_vs_sun", "usual_time"))
            if ins.species and k in seen:
                continue
            seen.add(k)
            trimmed.append(ins)
        out = trimmed
    out.sort(key=lambda i: -i.strength)
    if use_cache and now_given is None:  # never cache results computed for another moment
        _cache[key] = (time.time(), out)
    return out


def usual_time_label(conn: sqlite3.Connection, settings: Settings, species: str) -> str | None:
    tz = ZoneInfo(settings.camera_timezone)
    mins = sorted(v.t.astimezone(tz).hour * 60 + v.t.astimezone(tz).minute
                  for v in load_visits(conn) if v.species == species)
    if not mins:
        return None
    # circular median via the densest 3-hour window centre
    best = max(range(0, 1440, 15), key=lambda c: sum(1 for m in mins if min((m - c) % 1440, (c - m) % 1440) <= 90))
    return f"around {_clock(best)}"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
