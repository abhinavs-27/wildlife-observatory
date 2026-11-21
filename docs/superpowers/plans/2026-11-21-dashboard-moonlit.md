# Dashboard "Moonlit" Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the dashboard into the approved "moonlit field station": a last-night filmstrip, a big hero, portraits of the regulars, and a recent-visits grid.

**Architecture:** One edge change (best frame and box per species in `/api/species`), then
web-only work: new tokens in `globals.css`, small pure helpers in `web/lib/`, new server
components for the home sections, and a client `LitImage` for night lift.

**Tech Stack:** FastAPI/SQLite (edge), Next.js 15 App Router + TypeScript (web).

**Spec:** `docs/superpowers/specs/2026-11-21-dashboard-moonlit-design.md`

**Execution:** native, in-session. The owner asked to go ahead ("let's do that").

## Global Constraints

- **Dark only.** Tokens: bg `#0c1416`, glow `#1b2b33`, ink `#e7eee9`, sage `#9cc58a`, amber
  `#f2b705`, ring `#2a3a3a`, rust `#e07a5f`.
- **Copy is templated from data only.** Uncertain → "Possibly a {species}". Pending →
  "Identifying…".
- **"Last night"** = 18:00 yesterday to 07:00 today in `NEXT_PUBLIC_CAMERA_TIMEZONE`.
- **Night lift is display-only.** Mean luminance below 0.35 → `brightness(1.5) contrast(1.08)`.
- **Never show person-containing frames.** `best_frame_id` is already null for those.

## Review Focus

1. No sightings at all → home shows the empty notice, no crash (Task 3 check: empty DB render).
2. Last night had no visitors → filmstrip says so and shows the most recent night (Task 2 unit
   test `lastNightWindow` + Task 3 render).
3. Species whose only detections are in person media → portrait falls back to an initial, not
   a person photo (Task 1 test).
4. Edge offline → `Offline` notice (already handled; Task 3 check).
5. Portrait crop at an image edge (box at x=0 or x+w=1) → position clamps to 0–100% (Task 2
   unit test `portraitStyle`).

---

### Task 1: Best frame and box per species (edge)

**Files:** Modify `edge/src/observatory_edge/queries.py` (`species_summary`). Test:
`edge/tests/test_flow.py`.

**Produces:** each `species_summary` row gains `best_frame_id: int|None` and
`best_bbox: [x,y,w,h]|None`. These come from the highest-confidence animal detection of that
species's encounters, where `media.has_person=0`.

- [ ] Test `test_species_summary_has_portrait_frame`: after detect+classify a raccoon, its row
  has `best_frame_id` equal to the frame and `best_bbox` equal to `[0.2,0.3,0.2,0.2]`.
- [ ] Test `test_species_portrait_skips_person_media`: animal + person image → `best_frame_id`
  is None.
- [ ] Implement it with a per-species SQL lookup joining encounter_track → track_detection →
  detection → media, filtered on track species = the row's species.
- [ ] `uv run pytest -q` passes; commit.

### Task 2: Web helpers

**Files:** Create `web/lib/night.ts`, `web/lib/portrait.ts`, and `web/lib/night.test.ts` (run
with `node --test` via `tsx`, or pure TS compiled by `npx tsc` check; keep them dependency-free).

**Produces:**
- `lastNightWindow(now: Date, tz: string): { from: string; to: string }` (UTC ISO strings)
- `moonPhase(d: Date): { name: string; illumination: number }` (synodic 29.530588853 days from
  the 2000-01-06 18:14 UTC new moon)
- `portraitStyle(bbox: [number,number,number,number]): { backgroundSize: string; backgroundPosition: string }`.
  Zoom `z = clamp(0.75/max(w,h), 1.2, 6)`, visible fraction `v=1/z`,
  `pos = clamp((c - v/2)/(1-v), 0, 1)`.
- `heroLine(e: EncounterSummary): { title: string; subtitle: string }`

- [ ] Tests:
  - window for 2026-11-21T12:00Z NY → from `2026-11-20T23:00:00.000Z`, to `2026-11-21T12:00:00.000Z`
  - `portraitStyle([0,0.4,0.2,0.2])` x-position is `0%`
  - `moonPhase` of the 2000-01-06 new moon gives illumination < 0.02
  - an uncertain encounter's title starts with "Possibly a"
- [ ] Implement; `npx tsx --test lib/night.test.ts` passes; commit.

### Task 3: Moonlit theme + home page

**Files:** Modify `web/app/globals.css` (tokens, dark only) and `web/app/page.tsx`. Create
`web/components/{LitImage,LastNight,Hero,Regulars,RecentGrid}.tsx`.

**Consumes:** Task 1 fields and Task 2 helpers.

- [ ] `LitImage` (client): renders `<img>`, measures mean luminance on load via a 32×32 canvas,
  and adds class `lift` when it's below 0.35.
- [ ] `LastNight`: fetches `/api/encounters?date_from&date_to` for the window. If empty, it
  fetches the latest encounter and says "No visitors last night. Most recent: {date}".
- [ ] `Hero`, `Regulars` (amber ring on the most recent `last_seen`, dashed ring when
  `any_uncertain`, initial fallback when there's no frame) and `RecentGrid` (first tile spans
  2×2), styled as in the spec.
- [ ] Other pages pick up the new tokens. Photos use `LitImage` via `Photo`.
- [ ] `npm run build` passes. Screenshot home at 1280 and 500 px, and an empty-DB render
  (`EDGE_INTERNAL_URL` pointing at an empty edge) shows the empty notice. Commit and push.
