# Stories, animal info and insights — Design

Date: 2026-11-21 · Status: draft, approaches agreed in conversation

## 1. Intent

The owner wants the dashboard to go "up a notch". It should be something to show family, make the
animals feel alive, teach something about each animal, and explain what the data means (trends
in plain English), not just chart it. The owner asked for all five upgrades:
1. moving visits
2. an activity clock
3. a field-guide page per species
4. milestones
5. a weekly digest

They put particular emphasis on **animal information** and **trends with explanations**.

## 2. Goals

- Visits feel alive: bursts and clips play as short loops.
- Each species has a field-guide page: your photos, your stats, general info about the animal,
  and insights about how it uses your yard.
- The home page surfaces **insights** ("Raccoons usually arrive ~2 h after sunset") and
  **milestones** ("First bobcat ever!").
- A Monday-morning push summarizes the previous week, so family gets the story without opening anything.

## 3. Non-goals

- AI-written text (an optional Ollama narrative may come later, but it's not part of this).
- Multi-camera comparisons, maps.
- Weather-driven insights in the first pass (§7.7 is optional, last).

## 4. Anti-goals

- **Inventing facts or trends.** Every insight is computed by a rule from stored data, states its
  sample size, and is suppressed below a minimum. General animal info comes from Wikipedia
  (attributed and linked) or a small bundled facts table. Nothing is generated.
- Over-claiming from sparse data. One camera may see zero to a dozen visits a night, so quiet
  weeks must look intentional, not broken.
- Breaking offline operation. Wikipedia data and images are cached on the Pi, and everything
  computed (sun, moon, insights) works without internet.
- Sending the parents' location to outside services without the owner opting in (§7.7).

## 5. Constraints

- Builds on the existing edge (FastAPI + SQLite), worker and Next.js app. It follows the moonlit
  design (`2026-11-21-dashboard-moonlit-design.md`) and the dataviz rules (validated palette, one
  axis, legend for 2+ series, table view, hover).
- Python 3.12 on the edge; no new heavy dependencies. Sunrise/sunset and moon phase are computed
  with a small local algorithm (NOAA solar equations), not a network service.
- Wikipedia: REST API `https://en.wikipedia.org/api/rest_v1/page/summary/{title}`. Free, no key.
  Requests send only species names and a generic User-Agent (`wildlife-observatory/0.1`).
  Text is CC BY-SA, so we show attribution and a link.
- **Camera location** is needed for sunset times: `CAMERA_LAT`, `CAMERA_LON` in `.env`. The default
  is a central NJ point (40.06, −74.41). Real coordinates are never committed.

## 6. Approaches (agreed)

| Decision | Options | Chosen |
|---|---|---|
| Animal info | A. Wikipedia summaries, cached · B. hand-written cards for ~40 NJ species · C. AI-written | **A + a small bundled facts table** for common NJ species (activity pattern, size, NJ status). C rejected (can invent). |
| "What it means" | A. rule-based insights with minimum-data rules · B. AI narrative over the stats | **A.** B is a possible later layer. |
| Weekly digest | A. ntfy push · B. email | **A** (reuses alerts; parents install the ntfy app). |
| Weather | Open-Meteo archive (free, no key) | **Optional, last**, opt-in because it sends location. |

## 7. Design

### 7.1 Visit replay (moving visits)
- Frame sequence for an encounter: all frames of its media that have animal detections (plus the
  photo itself for images), ordered by capture time + frame offset. Person-containing media are
  excluded from replay on the home page and digest.
- **Home hero:** a client component crossfades through up to 8 frames, about 0.9 s each, and
  loops. Boxes follow each frame. Hover or tap pauses it. With `prefers-reduced-motion` it shows a
  static best frame. With a single frame it's static, with a subtle slow zoom.
- **Sighting page:** the same player, plus a scrubber (range input) and the frame time, in
  addition to the existing per-photo list.
- Data: `GET /api/encounters/{id}/frames` → `[{frame_id, t, bbox_list, species}]`.

### 7.2 Activity clock
- A 24-hour radial SVG with midnight at the bottom and noon at the top.
  - Each encounter is a dot at its local time. The ring position spreads overlapping dots.
  - The background is shaded night (sunset → sunrise) for the median date in range, from §7.5.
- **Color by species:** the top 6 species get categorical hues in fixed order from a validated
  palette (run `validate_palette.js`, dark mode, surface `#0c1416`). Everything else is "Other",
  in neutral grey. A legend plus direct labels, a hover tooltip (species, time, link), and a
  table view.
- Placement: the Activity page (all species, with a species filter) and a mini version on each
  species page (that species only, one hue).
- Data: `GET /api/activity` gains `points: [{encounter_id, minute_of_day, date, species}]` and
  `night: {sunset_min, sunrise_min}`.

### 7.3 Species field-guide pages (`/species/[name]`)
- **Header:** best photo cropped wide, common name, scientific name (from SpeciesNet taxonomy),
  and an NJ status badge from the facts table, when known.
- **"In your yard":** first seen, last seen, total visits, usual time (median, as "around 10 pm"),
  and the mini clock.
- **A calendar heatmap** of visits by day: last 26 weeks, single-hue sequential ramp, a legend,
  and hover counts.
- **Insights for this species** (§7.4).
- **"About the {animal}":** the Wikipedia summary (first ~2–3 sentences), thumbnail, "From
  Wikipedia" link, and the bundled facts (active at night/day/dawn and dusk, typical size, diet in
  a few words).
- **Photo gallery** of this species' visits.
- **Rolled-up labels** ("squirrel family") get a family-level page, with an explanation that the
  model wasn't sure of the exact species.
- Home "regulars" portraits link here (replacing today's filter link), and so do species names
  elsewhere.

### 7.4 Insights engine (edge `insights.py`)
`compute_insights(conn, settings, species: str | None = None) -> list[Insight]` returns
`Insight(id, kind, species, text, detail, n, encounter_ids, strength)`. `id` is stable (kind +
species + period), so the dashboard and digest can dedupe. Rules and minimum data:

| Kind | Example text | Rule | Minimum |
|---|---|---|---|
| `timing_vs_sun` | "Raccoons usually arrive about 2 h after sunset." | median of (visit time − that day's sunset) for nocturnal visits, or relative to sunrise for daytime ones | ≥5 visits |
| `usual_time` | "Squirrels mostly visit between 8 and 11 am." | the smallest window holding ≥60% of visits | ≥5 visits |
| `trend` | "Fox visits doubled in the last 30 days (8 vs 4)." | last 30 days vs the 30 before; ratio ≥1.5 or ≤0.67 | ≥6 visits in total |
| `moon` | "Deer came more often on bright-moon nights." | visits per night on illumination >60% vs <40% nights; ratio ≥1.5 | ≥10 visits and ≥5 nights of each type |
| `regular` | "The opossum has visited 5 of the last 7 nights." | distinct nights in the last 7 | ≥4 of 7 |
| `together` | "Skunks and raccoons often visit on the same nights." | nights with both / nights with either ≥40% | ≥3 shared nights |
| `quiet` | "A quiet week: 2 visits, versus a usual 9." | the week vs the trailing 8-week median | ≥4 weeks of history |

- Every insight shows "based on N visits" and links to its encounters.
- If no rule clears its minimum, the section says "Not enough visits yet to spot patterns. Check
  back in a couple of weeks." Uncertain (rolled-up) classifications are excluded from
  species-specific insights.
- Insights are computed on read and cached for 10 minutes. There's no new table.

### 7.5 Sun and moon (edge `astro.py`)
- `sun_times(date, lat, lon, tz) -> (sunrise, sunset)` using NOAA equations, with tests against
  known values.
- `moon_illumination(date) -> float`, the same synodic approximation as the web helper, moved to
  one source of truth.
- Used by insights, the clock's night shading, and the filmstrip.

### 7.6 Milestones (edge `milestones.py`)
- A `milestone` table: `id`, `kind`, `species`, `encounter_id`, `text`, `created_at`, and a unique
  `key`. Kinds:
  - `first_species` ("First bobcat ever!")
  - `first_this_year`
  - `back_after` (species back after ≥14 days away)
  - `record_night` (most visits in one night so far)
  - `new_species_count` (10th, 25th, 50th species)
- Evaluated idempotently, using the unique key, after each classify result and nightly.
  Re-evaluating never duplicates a milestone.
- `first_species` and `back_after` on a **live** capture send an ntfy push ("🎉 New visitor: first
  bobcat ever!"), sent separately from the visit alert. Bulk imports create milestones but never
  push.
- On the dashboard: a home "Highlights" strip (the latest 3 milestones plus the top insights),
  badges on encounter cards, and a milestones list on species pages.
- Corrections can change species, so milestones are recomputed when a correction changes an
  encounter's species. A milestone whose basis disappears is deleted.

### 7.7 Weekly digest (edge `digest.py`)
- **Built:** Mondays at 08:00 in `CAMERA_TIMEZONE`, covering the previous full week (Monday 00:00 to Sunday 24:00, so Sunday night's animals are included). The week key is that Monday's ISO week. Result:
  `Digest(week_start, visits, species, new_species, best_encounter_id, highlights[])`.
- **Best photo:** the classified, non-uncertain, non-person encounter with the highest score;
  ties go to the rarer species.
- **Push:** ntfy with the best photo attached, a title ("This week in the yard: 23 visits, 7
  species"), three highlights (milestones first, then the strongest insights), and a `Click`
  header to `DASHBOARD_URL/digest/{week}`.
- **Quiet weeks:** sends "A quiet week in the yard" with whatever there is. With zero visits it
  says so plainly.
- **Dashboard:** `/digest/[week]` shows the same content, plus an archive of past weeks.
- **Stored** in a `digest` table (one row per week) so it's idempotent and browsable.

### 7.8 Animal info (edge `species_info.py`)
- A `species_info` table: `common_name` (PK), `wiki_title`, `extract`, `thumbnail_path` (cached
  locally under `data/species/`), `page_url`, `fetched_at`, `status`.
- **Resolution order:** scientific binomial from the taxonomy columns ("Procyon lotor"), then the
  genus or family for rolled-up labels ("Sciuridae"), then the common name.
- **Fetching:** in the background when a new species is first classified, plus a nightly refresh
  of entries older than 90 days or that failed. If Wikipedia is unreachable, the page shows
  "Information will appear once the observatory is online", never a guess.
- **Bundled facts** (`edge/src/observatory_edge/data/species_facts.json`), keyed by binomial,
  for roughly 40 NJ mammals and birds likely on a backyard camera. Fields: `activity`
  (nocturnal/diurnal/crepuscular/cathemeral), `size`, `diet`, `nj_status`
  (common/uncommon/rare/state-listed). Each value is conservative and well established. The file
  has a `sources` note and is easy to correct. Unknown species simply have no facts block.

### 7.9 Optional, last: weather
- Opt-in with `WEATHER_ENABLED=true`. Coordinates sent to Open-Meteo are rounded to 2 decimals.
- A nightly fetch of daily precipitation and min/max temperature into `weather_daily`.
- Adds insights `rain` ("Fewer visits on rainy nights: 0.8 vs 2.1 per night") and `cold`, with the
  same minimum-data rules (≥10 nights in each group).

## 8. Phases

1. **Backend foundations:** `astro.py`, `insights.py`, `species_info.py` + facts JSON,
   `milestones.py`, new API endpoints, all with tests. Wikipedia is mocked in tests and fetched
   live once in a manual check.
2. **Species pages + activity clock + calendar heatmap** (validated palette).
3. **Visit replay** on the home hero and sighting page.
4. **Highlights on home** (milestones + insights) and milestone pushes.
5. **Weekly digest** (push + `/digest` pages).
6. *(Optional)* **Weather.**

Each phase ends with a build, tests, screenshots and a commit.

## 9. Testing

- **Unit:** sun times against published values for Trenton, NJ (two dates, ±3 min); moon
  illumination at known new and full moons.
- **Insights:**
  - each rule fires at its threshold and is suppressed just below it
  - uncertain labels are excluded
  - text numbers match SQL ground truth
- **Milestones:** idempotent across reruns; recomputed after a correction; no push for bulk
  imports.
- **Digest:** quiet week, zero-visit week, person-photo exclusion, idempotent per week.
- **species_info:** binomial → title resolution, offline fallback, cached thumbnail served. Uses
  a mocked HTTP transport.
- **Web:** helper unit tests; `npm run build`; screenshots of each new page at 1280 and 500 px;
  the empty-data state for every new section.

## 10. Calls made (owner to check)

- **Location:** default to a central NJ point for sun times until you set the real `CAMERA_LAT` and
  `CAMERA_LON` (kept only in `.env`).
- **Thresholds:** the minimum-data rules in §7.4 are my conservative defaults.
- **Navigation:** home "regulars" portraits now open the species page instead of filtering.
- **Rolled-up labels** get family-level pages that explain the uncertainty.
- **Pushes:** digest on Monday at 08:00, covering the previous full week. Milestone pushes only for first-ever and back-after-a-break.
- **Bundled facts** are written by me from well-established natural history, and are marked as
  general info. Worth a skim.

- **"Uncertain"** means `classification.is_uncertain = 1`, which already covers both a score below 0.5 and a label rolled up above species (see `taxonomy.is_uncertain`). Uncertain results are excluded from species insights, milestones and the digest's best photo. Species-level but low-score results stay on that species' page, flagged "uncertain"; rolled-up labels get family pages.
- **Milestone identity:**
  - Milestones are keyed by `(kind, species, local night date)`, not by encounter.
  - `encounter_id` is re-pointed in `rebuild_window` alongside alerts and corrections.
  - They're re-evaluated only after classify results, corrections, and nightly.
  - A milestone that was already pushed is never retracted. If a later correction removes its basis, the row is marked `withdrawn` and hidden from the dashboard.

- **Two ntfy channels** (owner's answer):
  - `NTFY_TOPIC` is the owner's channel: visit alerts, problems, milestones and the digest.
  - `NTFY_FAMILY_TOPIC` (optional) is for the parents: the weekly digest and big milestones only.
  - Family members don't have Tailscale, so family pushes are **self-contained**: the photo is
    attached and the full summary is in the message body, with no reliance on a link. Only the
    owner's copies carry the `Click` link to the dashboard.
- **Milestone push confidence** (owner's answer):
  - A milestone is pushed to family immediately only if its classification is species-level,
    not uncertain, and scores **≥ 0.80**.
  - Otherwise it's recorded as `awaiting_confirmation`, and the owner gets the push marked
    "unconfirmed".
  - When the owner taps **Confirm prediction** (or relabels it to a species) on that sighting,
    the family push is sent.

## 11. Builder's discretion

Visual details within the moonlit system, animation timing, clock dot layout, heatmap cell size,
exact copy wording (within the "no embellishment" rule), caching mechanism, endpoint shapes not
pinned above.
