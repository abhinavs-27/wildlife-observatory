"""Natural-language questions -> fixed, parameterized queries. Never invents data.

The matcher is deterministic: if it can't map a question to a known intent it says so.
Every answer carries the encounter IDs it was computed from.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .db import to_iso
from .queries import activity, list_encounters, species_summary

UNKNOWN = ("I don't understand that yet. Try: \"What animals have visited?\", "
           "\"Show all fox sightings\", \"When are deer most active?\", "
           "\"What was the rarest species?\"")

# Group words -> taxonomic filters on the classification table.
GROUPS: dict[str, tuple[str, list[str]]] = {
    "bird": ("taxon_class", ["aves"]),
    "mammal": ("taxon_class", ["mammalia"]),
    "reptile": ("taxon_class", ["reptilia"]),
    "squirrel": ("taxon_family", ["sciuridae"]),
    "deer": ("taxon_family", ["cervidae"]),
    "fox": ("taxon_genus", ["vulpes", "urocyon"]),
    "cat": ("taxon_family", ["felidae"]),
    "dog": ("taxon_family", ["canidae"]),
    "rabbit": ("taxon_family", ["leporidae"]),
    "raccoon": ("taxon_genus", ["procyon"]),
    "opossum": ("taxon_family", ["didelphidae"]),
    "possum": ("taxon_family", ["didelphidae"]),
    "skunk": ("taxon_family", ["mephitidae"]),
    "bear": ("taxon_family", ["ursidae"]),
    "coyote": ("taxon_species", ["latrans"]),
    "mouse": ("taxon_family", ["muridae", "cricetidae"]),
    "rat": ("taxon_family", ["muridae"]),
    "rodent": ("taxon_order", ["rodentia"]),
    "turkey": ("taxon_genus", ["meleagris"]),
    "groundhog": ("taxon_species", ["monax"]),
    "woodchuck": ("taxon_species", ["monax"]),
    "chipmunk": ("taxon_genus", ["tamias"]),
}


@dataclass
class Answer:
    text: str
    intent: str
    rows: list[dict] = field(default_factory=list)
    sources: list[int] = field(default_factory=list)


def _singular(word: str) -> str:
    w = word.lower().strip()
    for suf, rep in (("ies", "y"), ("xes", "x"), ("ses", "s"), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)] + rep
    return w


def resolve_species(conn: sqlite3.Connection, phrase: str) -> tuple[str, list[str]]:
    """Map a phrase like 'foxes' to the effective species names present in the DB."""
    words = [_singular(w) for w in re.findall(r"[a-z]+", phrase.lower())]
    known = [s["species"] for s in species_summary(conn)]
    name = " ".join(words)
    exact = [s for s in known if s == name or _singular(s) == name]
    if exact:
        return name, exact
    matches: set[str] = set()
    for w in words:
        if w in GROUPS:
            col, vals = GROUPS[w]
            marks = ",".join("?" * len(vals))
            for r in conn.execute(
                    f"SELECT DISTINCT common_name FROM classification WHERE {col} IN ({marks})",
                    vals):
                matches.add(r[0])
        matches.update(s for s in known if re.search(rf"\b{re.escape(w)}", s))
    # include corrected labels that mention the word
    return name, sorted(m for m in matches if m in known)


def _date_range(q: str, tz: str) -> tuple[str | None, str | None, str]:
    z = ZoneInfo(tz)
    today = datetime.now(z).date()
    start_of = lambda d: datetime.combine(d, time.min, tzinfo=z)  # noqa: E731
    if "today" in q:
        return to_iso(start_of(today)), None, "today"
    if "yesterday" in q:
        return to_iso(start_of(today - timedelta(days=1))), to_iso(start_of(today)), "yesterday"
    if "this week" in q:
        s = today - timedelta(days=today.weekday())
        return to_iso(start_of(s)), None, "this week"
    if "last week" in q:
        s = today - timedelta(days=today.weekday() + 7)
        return to_iso(start_of(s)), to_iso(start_of(s + timedelta(days=7))), "last week"
    if "this month" in q:
        return to_iso(start_of(today.replace(day=1))), None, "this month"
    if "last month" in q:
        first = today.replace(day=1)
        prev = (first - timedelta(days=1)).replace(day=1)
        return to_iso(start_of(prev)), to_iso(start_of(first)), "last month"
    m = re.search(r"last (\d+) days", q)
    if m:
        return to_iso(start_of(today - timedelta(days=int(m.group(1))))), None, m.group(0)
    return None, None, ""


def _fmt_local(iso: str, tz: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(
        ZoneInfo(tz)).strftime("%b %-d, %Y %-I:%M %p")


SPECIES_PATTERNS = [
    ("sightings_of", r"(?:show|list|find|see)(?: me)?(?: all)?(?: the)? (.+?) (?:sightings?|visits?|encounters?|photos?|pictures?)"),
    ("sightings_of", r"(?:any|were there any|have there been any|did (?:a|an|any)) (.+?) (?:sightings?|visits?|come|show up|appear|today|this|last|$)"),
    ("activity_of", r"when (?:are|is|do|does) (?:the )?(.+?) (?:most )?(?:active|around|come|visit|show up|seen)"),
    ("activity_of", r"what time (?:do|does|are|is) (?:the )?(.+?) (?:come|visit|show up|active)"),
    ("last_seen", r"when was (?:the |a |an )?(.+?) last seen"),
    ("last_seen", r"last time (?:a |an |the )?(.+?) (?:was seen|visited|came|appeared)"),
    ("count_of", r"how many (.+?) (?:sightings?|visits?|encounters?|have|were|did|$)"),
]


def answer(conn: sqlite3.Connection, settings: Settings, question: str) -> Answer:
    q = " ".join(question.lower().strip().rstrip("?.!").split())
    tz = settings.camera_timezone
    if not q:
        return Answer(UNKNOWN, "unknown")
    date_from, date_to, date_label = _date_range(q, tz)
    when = f" {date_label}" if date_label else ""

    if re.search(r"\b(rarest|least common|least seen|rare)\b", q):
        summary = species_summary(conn)
        if not summary:
            return Answer("No species have been identified yet.", "rarest")
        low = min(s["encounters"] for s in summary)
        rarest = [s for s in summary if s["encounters"] == low]
        names = ", ".join(s["species"] for s in rarest)
        srcs = [i for s in rarest for i in _ids(conn, s["species"])]
        unc = any(s["any_uncertain"] for s in rarest)
        text = (f"The rarest {'species is' if len(rarest) == 1 else 'species are'} {names}, "
                f"seen in {low} encounter{'s' if low != 1 else ''}.")
        if unc:
            text += " Note: some of these identifications are uncertain."
        return Answer(text, "rarest", rarest, srcs)

    if re.search(r"\b(most common|most frequent|most often|most seen)\b", q):
        summary = species_summary(conn)
        if not summary:
            return Answer("No species have been identified yet.", "most_common")
        top = summary[0]
        return Answer(f"The most common visitor is {top['species']}, seen in "
                      f"{top['encounters']} encounters.", "most_common", summary[:5],
                      _ids(conn, top["species"]))

    if re.search(r"\bwhat (animals|species|wildlife|creatures)\b|\bwho (has )?visited\b|"
                 r"\blist (all )?(the )?(animals|species)\b|\bwhich (animals|species)\b", q):
        encs = list_encounters(conn, date_from=date_from, date_to=date_to, limit=100000)
        counts: dict[str, int] = {}
        for e in encs:
            for s in e["species"]:
                if s["species"] != "pending":
                    counts[s["species"]] = counts.get(s["species"], 0) + 1
        pending = sum(1 for e in encs if e["status"] == "pending")
        if not counts and not pending:
            return Answer(f"No wildlife sightings found{when}.", "list_species")
        rows = [{"species": k, "encounters": v} for k, v in
                sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        parts = [f"{r['species']} ({r['encounters']})" for r in rows]
        text = (f"Visitors{when}: " + ", ".join(parts) + ".") if parts else ""
        if pending:
            text += (f" {pending} encounter{'s' if pending != 1 else ''} "
                     "still awaiting species identification.")
        return Answer(text.strip(), "list_species", rows, [e["id"] for e in encs][:100])

    for intent, pat in SPECIES_PATTERNS:
        m = re.search(pat, q)
        if not m:
            continue
        phrase = re.sub(r"\b(today|yesterday|this week|last week|this month|last month)\b",
                        "", m.group(1)).strip()
        phrase = re.sub(r"^(the|a|an|any|all)\s+", "", phrase)
        if not phrase:
            continue
        label, names = resolve_species(conn, phrase)
        if not names:
            return Answer(f"No {label} sightings found{when}.", intent)
        encs = list_encounters(conn, species_any=names, date_from=date_from, date_to=date_to,
                               limit=100000)
        if not encs:
            return Answer(f"No {label} sightings found{when}.", intent)
        ids = [e["id"] for e in encs]
        names_txt = ", ".join(names)
        if intent == "sightings_of":
            latest = _fmt_local(encs[0]["start_at"], tz)
            return Answer(f"{len(encs)} {label} encounter{'s' if len(encs) != 1 else ''}{when} "
                          f"({names_txt}). Most recent: {latest}.", intent, encs[:50], ids)
        if intent == "count_of":
            return Answer(f"{len(encs)} {label} encounter{'s' if len(encs) != 1 else ''}{when} "
                          f"({names_txt}).", intent, encs[:50], ids)
        if intent == "last_seen":
            return Answer(f"{label.capitalize()} was last seen {_fmt_local(encs[0]['start_at'], tz)}"
                          f" ({encs[0]['species'][0]['species']}).", intent, encs[:1], ids[:1])
        if intent == "activity_of":
            act = activity(conn, settings, species_any=names)
            hours = sorted(act["by_hour"], key=lambda h: -h["count"])
            peak = [h for h in hours if h["count"] == hours[0]["count"] and h["count"] > 0]
            spans = ", ".join(_hour_label(h["hour"]) for h in sorted(peak, key=lambda h: h["hour"]))
            return Answer(f"{label.capitalize()} {'are' if label.endswith('s') or label in ('deer',) else 'is'} "
                          f"most active around {spans} ({act['total']} encounters, "
                          f"times in {tz}).", intent, act["by_hour"], act["encounter_ids"])
    return Answer(UNKNOWN, "unknown")


def _hour_label(h: int) -> str:
    def fmt(x):
        x %= 24
        return f"{12 if x % 12 == 0 else x % 12}{'am' if x < 12 else 'pm'}"
    return f"{fmt(h)}–{fmt(h + 1)}"


def _ids(conn, species: str) -> list[int]:
    return [e["id"] for e in list_encounters(conn, species=species, limit=50)]
