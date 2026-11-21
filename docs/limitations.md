# Known limitations

- **A few sample timestamps are synthetic.** Most NACTI photos (62 of 65 in our sample) carry a
  real EXIF capture time from 2010–2017, and the pipeline uses it. For the few without one,
  `scripts/fetch_samples.py` stamps the file's mtime with a made-up time in the last 30 days
  (night hours for nocturnal species). These times are recorded in `samples/manifest.csv` as
  `synthetic_time`. The sample clip is one of them. Real camera uploads use their own timestamps.
- **The sample clip is assembled.** `raccoon_burst.mp4` is four real NACTI raccoon photos from
  one location stitched together at 1 fps. It isn't a native camera video.
- **The tracker is geometric only:** greedy IoU/centroid matching within 30 s. Two similar
  animals crossing paths can swap tracks. Visual re-identification is not built.
- **Individual animals:** the schema has an `individual` table, but there's no UI or automatic
  matching. It's experimental by design.
- **Search is rule-based.** It covers listing species, sightings of X, activity of X, rarest, most
  common, last seen and how many, with simple date phrases. Anything else gets "I don't
  understand that yet". The optional LLM layer (Ollama) for behavior questions is designed but
  not built.
- **Species names come from SpeciesNet** ("grey fox", "northern raccoon"). Rolled-up labels like
  "cervidae family" or "bird" are shown as uncertain. Search maps common words (fox, deer,
  squirrel, bird…) to taxonomy, so "fox" matches both grey fox and red fox.
- **Accuracy on the 64 samples is 89%.** Misses: 3 animals MegaDetector missed entirely
  (small or dark), 3 wild turkeys rolled up to "bird", and 1 skunk rolled up to "mammal".
  See [example-results.md](example-results.md).
- **Insights need data.** With a handful of visits, most insight rules stay silent by design.
  Trends and moon effects need weeks of real captures. On the sample data (photos from
  2010–2017), the "back after more than a year" milestones are artifacts of that old dataset.
- **Wikipedia rate-limits bursts.** Species info is fetched slowly in the background (a couple of
  species per minute), so a brand-new install takes a few minutes to fill in every page.
- **Bundled facts** (`species_facts.json`) are hand-written general natural history for about 40
  species. They're worth a skim, and easy to correct.
- **Not built yet:**
  - the reprocessing UI and API (the schema and per-media active-run pointers support it)
  - the FtpPullAdapter and RtspAdapter (stubs or docs only)
- **The dashboard has no login.** It must only be reachable over the LAN or Tailscale. Photos of
  people are hidden from the gallery and from alerts, but are visible on sighting detail pages.
- **The Docker worker on macOS is CPU-only.** Run the worker natively on the Mac to use MPS.
