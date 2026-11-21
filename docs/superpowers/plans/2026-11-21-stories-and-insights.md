# Stories, Animal Info & Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add moving visits, an activity clock, species field-guide pages with Wikipedia info,
rule-based insights, milestones with pushes, a weekly digest, and optional weather.

**Architecture:** New focused edge modules (`astro`, `species_info`, `insights`, `milestones`,
`digest`, `weather`), each pure-ish over SQLite, exposed through new `/api/*` routes and driven by
the existing background loops. The web adds a species page, digest pages and three components
(ActivityClock, CalendarHeatmap, Replay), all following the moonlit design.

**Tech Stack:** Python 3.12, FastAPI, sqlite3, httpx (Wikipedia, Open-Meteo); Next.js 15 / TS / SVG.

**Spec:** `docs/superpowers/specs/2026-11-21-stories-and-insights-design.md`

**Execution:** native, in-session (owner: "fully finish up and commit").

## Global Constraints

- **No generated text.** Insights come from rules with minimums (spec §7.4 table, verbatim
  thresholds), and every insight carries `n`.
- **"Uncertain"** = `classification.is_uncertain = 1`. Excluded from insights, milestones and the
  digest's best photo.
- **Wikipedia:** only species names are sent, with User-Agent `wildlife-observatory/0.1`. Cached
  in `species_info`. Attribution is shown.
- **Location:** `CAMERA_LAT`/`CAMERA_LON` default to 40.06/−74.41. Weather is opt-in
  (`WEATHER_ENABLED`), with coordinates rounded to 2 decimals.
- **Channels:** `NTFY_TOPIC` (owner, everything, Click link) and `NTFY_FAMILY_TOPIC` (digest +
  big milestones, self-contained, no link).
- **Family milestone push:** only if species-level, not uncertain, score ≥ 0.80. Otherwise
  `awaiting_confirmation` until the owner confirms or relabels.
- **Digest:** Monday 08:00 local, covering the previous Monday 00:00 to Monday 00:00. Key = ISO
  week string `YYYY-Www` of the covered Monday.
- **Bulk-imported** (suppressed) captures create milestones but never push.

## Review Focus

1. Species with zero classified visits, or only uncertain ones → species page renders with
   "not enough visits" and no insights (Task 3 test).
2. Wikipedia unreachable → info status `error` and the page shows the offline message; nothing is
   cached as content (Task 2 test).
3. Milestone re-evaluation after a merge or correction → no duplicate rows or pushes (Task 4 test).
4. A digest week with zero visits → "A quiet week" and no photo attached (Task 5 test).
5. A person-containing best photo → never attached to the digest or a family push (Task 5 test).

---

### Task 1: Config, schema, astro

**Files:** Modify `config.py` and `schema.sql`. Create `astro.py`. Test `tests/test_astro.py`.

**Produces:**
- `Settings.camera_lat=40.06`, `camera_lon=-74.41`, `ntfy_family_topic=""`,
  `dashboard_url=""`, `family_min_score=0.8`, `weather_enabled=False`, plus their env vars.
- Tables:
  - `species_info(common_name PK, wiki_title, extract, page_url, thumbnail_path, status, fetched_at)`
  - `milestone(id, key UNIQUE, kind, species, encounter_id, text, night, status, pushed_owner, pushed_family, created_at)`
  - `digest(week PK, payload_json, sent_at)`
  - `weather_daily(date PK, precip_mm, tmin_c, tmax_c)`
- `sun_times(d: date, lat, lon, tz) -> tuple[datetime, datetime]` (aware, local tz),
  `moon_illumination(dt: datetime) -> float`, `night_of(ts_utc: datetime, tz) -> date` (the
  date of the evening a nocturnal visit belongs to; before noon counts as the previous date).

- [ ] Tests:
  - Trenton (40.22, −74.76), 2024-06-21: sunrise 05:29 ±3 min, sunset 20:32 ±3 min, EDT.
  - Same place, 2024-12-21: sunrise 07:17 ±3, sunset 16:37 ±3.
  - `moon_illumination(2024-01-11 11:57Z)` < 0.02 and `(2024-01-25 17:54Z)` > 0.98.
  - `night_of(2024-06-02T06:00Z, NY)` == 2024-06-01.
- [ ] Implement (NOAA simplified solar equations); tests pass; commit.

### Task 2: Species info (Wikipedia + facts)

**Files:** Create `species_info.py` and `data/species_facts.json`. Test `tests/test_species_info.py`.

**Produces:**
- `wiki_candidates(conn, common_name) -> list[str]`: binomial → genus/family (capitalized) →
  common name.
- `fetch_species_info(conn, settings, common_name, client: httpx.Client) -> str` (status).
- `get_species_info(conn, settings, common_name) -> dict`, which merges the facts by binomial.
- `refresh_species_info(conn, settings, client=None, limit=20) -> int`, for missing, failed, or
  older-than-90-days entries.
- The thumbnail is saved to `data/species/<slug>.jpg`.

- [ ] Tests (`httpx.MockTransport`):
  - a raccoon row resolves "Procyon lotor" first
  - a successful fetch stores the extract and thumbnail file
  - a 404 on the binomial falls back to the next candidate
  - a network error leaves status `error` with no extract
  - the facts lookup returns `activity == "nocturnal"` for raccoon
- [ ] Implement; commit.

### Task 3: Insights engine + species detail API

**Files:** Create `insights.py`. Modify `queries.py` (`species_detail`, activity points/night) and
`api.py`. Test `tests/test_insights.py`.

**Produces:**
- `Insight(id, kind, species, text, detail, n, encounter_ids, strength)` and
  `compute_insights(conn, settings, species=None, now=None) -> list[Insight]`, with kinds
  `timing_vs_sun`, `usual_time`, `trend`, `moon`, `regular`, `together`, `quiet` (+ `rain` when
  weather data exists). Sorted by strength.
- `species_detail(conn, settings, name) -> dict | None`, containing summary, `scientific_name`,
  `calendar` [{date, count}] for 182 days, `usual_time`, gallery encounters, info, insights and
  milestones.
- `activity()` gains `points` and `night`.
- Routes: `GET /api/insights?species=`, `GET /api/species/{name}`,
  `GET /api/species/{name}/image`, `GET /api/encounters/{id}/frames`.

- [ ] Tests (synthetic encounters built through the existing flow helpers):
  - `timing_vs_sun` fires with 5 night visits and is silent with 4
  - `trend` "doubled" with 8 vs 4, silent at 4 vs 3
  - uncertain classifications are excluded
  - the text count equals SQL
  - an empty DB gives `[]`
  - `species_detail` for an unknown name gives None
  - `encounter frames` are ordered and person media is flagged
- [ ] Implement; commit.

### Task 4: Milestones + channels

**Files:** Create `milestones.py`. Modify `alerts.py` (channels: `owner`/`family`, Click link
for the owner), `results.py` and `corrections.py` (call evaluate/confirm), `tracking.py`
(re-point `milestone.encounter_id`), and `background.py` (nightly). Test `tests/test_milestones.py`.

**Produces:**
- `evaluate_milestones(conn, settings, now=None) -> list[int]` (new ids)
- `release_confirmed(conn, settings, encounter_id) -> int`
- alert rows with `channel` in {owner, family}
- `send_pending_alerts` picks the topic by channel and skips family when no topic is set

- [ ] Tests:
  - the first raccoon gives one `first_species` milestone; re-running gives none
  - a live capture with score 0.93 queues owner + family alerts
  - score 0.6 queues the owner alert only, status `awaiting_confirmation`; a confirm correction
    then queues the family alert
  - a suppressed capture gives a milestone but no alerts
  - `back_after` after a 15-day gap
  - `record_night` when a night exceeds the previous max
  - a correction removing the basis marks it `withdrawn`
- [ ] Implement; commit.

### Task 5: Weekly digest

**Files:** Create `digest.py`. Modify `background.py` (Monday 08:00) and `api.py`
(`/api/digests`, `/api/digests/{week}`). Test `tests/test_digest.py`.

**Produces:**
- `build_digest(conn, settings, week_monday: date) -> dict` with keys `week, start, end,
  visits, species, new_species, best_encounter_id, best_frame_id, highlights`
- `send_digest(conn, settings, week_monday) -> bool`, which is idempotent through the `digest`
  table and queues an owner alert (with Click) and a family alert (self-contained body)

- [ ] Tests:
  - a week with 3 species gives the right counts and best photo
  - a person-photo encounter is never the best
  - a zero-visit week's body starts with "A quiet week"
  - a second `send_digest` returns False
- [ ] Implement; commit.

### Task 6: Weather (optional, opt-in)

**Files:** Create `weather.py`. Wire it into `background.py` and `insights.py` (`rain`). Test
`tests/test_weather.py`.

- `fetch_weather(conn, settings, start, end, client)` calls Open-Meteo archive `daily=precipitation_sum,temperature_2m_min,temperature_2m_max` with rounded coordinates.
- [ ] Tests: the mocked response stores rows; disabled → no request; the `rain` insight respects
  ≥10 nights each.
- [ ] Implement; commit.

### Task 7: Web — species pages, clock, calendar, replay, highlights, digest pages

**Files:**
- Create `web/components/{ActivityClock,CalendarHeatmap,Replay,Highlights}.tsx`,
  `web/app/species/[name]/page.tsx`, `web/app/digest/page.tsx` and
  `web/app/digest/[week]/page.tsx`.
- Modify `HomeSections.tsx` (Hero → Replay; regulars → species links), `page.tsx` (Highlights),
  `activity/page.tsx` (clock), `encounters/[id]/page.tsx` (replay + scrubber), `layout.tsx` (nav
  "Digest") and `lib/api.ts` types.
- The clock palette must be validated with `validate_palette.js` (dark, surface `#0c1416`).

- [ ] `npm test` + `npm run build` pass. Screenshots of home, species page, activity and digest at
  1280 and 500 px look right, including the empty states. Commit and push.

### Task 8: Docs + final verification

- [ ] Update README, architecture, limitations, next-steps and `.env.example` (new vars).
- [ ] Run all suites. Do a live check: run the refresh against real Wikipedia for the sample
  species. Have one reviewer pass over the branch, fix its findings, commit and push.
