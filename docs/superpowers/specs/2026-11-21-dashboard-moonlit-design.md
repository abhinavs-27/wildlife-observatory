# Dashboard redesign: "Moonlit field station" — short design

Date: 2026-11-21 · Status: approved by owner in conversation (mockup `field-station-v3`, take A
colors + take B "last night" filmstrip).

## Intent

The owner likes the current field-station look and mainly wants to show the dashboard to family
("look who visited last night"). So the redesign makes it prettier and more story-like, while
staying honest. Every sentence is built from data; nothing is embellished (the mockup's "past the
woodpile" copy is not used).

## Approaches considered

- **A. Field station, polished** (chosen as base): the dark trail-cam aesthetic, made richer.
- B. Nature journal: light and magazine-like. Not chosen; the owner prefers the current dark look.
- C. Last night as a timeline: the most distinctive. Its idea survives as the filmstrip on top of A.

Within A, the owner picked my combination: take A's cooler "moonlit" palette plus take B's
"last night" filmstrip.

## Design

- **Palette (dark only):**
  - background `#0c1416`, with a soft radial glow `#1b2b33` at the top left
  - text `#e7eee9`
  - accent sage `#9cc58a`
  - detection amber `#f2b705`
  - rings and rules `#2a3a3a`
  - problems rust `#e07a5f`

  Fonts stay Barlow Condensed (headings) and Atkinson Hyperlegible (body). Light mode is dropped
  (my call: the night look is the identity).
- **Home, top to bottom:**
  1. **Last night filmstrip.**
     - Shows encounters from 6 pm yesterday to 7 am today (camera timezone), in time order, each
       with a photo, its time and the species.
     - The left card shows the visitor count and the moon phase. The moon phase is computed, not
       fetched.
     - If last night had none, it says so and shows the most recent night that did ("No visitors
       last night. Most recent: Nov 14").
  2. **Hero.**
     - The latest encounter's photo, about 16:8, with a soft vignette and a glowing amber box.
     - A time stamp chip at the top left.
     - The species name large at the bottom left, with a templated line under it: "Visited at
       3:08 am on Tuesday · 2 photos" and the confidence. Uncertain results read "Possibly a
       ___", and pending ones "Identifying…".
     - A "See the visit" button.
  3. **Facts row:** species so far · visits · busiest hour · visitors last night.
  4. **The regulars:**
     - A round portrait per species, cropped to the animal using the best detection box, with
       the visit count.
     - The species seen most recently gets an amber ring.
     - Tapping one filters to that species. Uncertain-only species get a dashed ring.
  5. **Recent visits:** a mixed-size grid (first tile 2×2), each tile with the species and time.
- **Night lift:** dark photos (mean luminance below 0.35, measured in the browser on load)
  get a display-only CSS brighten (`brightness(1.5) contrast(1.08)`). Originals are untouched.
- **Other pages** (photos, sighting detail, activity, ask, system) adopt the new tokens, rounded
  photos and glow boxes. Layouts stay the same.

## Data needed

`GET /api/species` gains each species' best frame and box: the highest-confidence animal
detection in a non-person media item, for portraits. Everything else uses existing endpoints.

## Builder's discretion

Exact spacing, moon-phase algorithm (simple synodic approximation is fine), luminance threshold,
mobile stacking.
