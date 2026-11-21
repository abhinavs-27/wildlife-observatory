# Example inference results

64 real camera-trap photos from [LILA NACTI](https://lila.science/datasets/nacti) were picked by
`scripts/fetch_samples.py`: 4 per category, all species that also occur in New Jersey, plus
empties and vehicles. They went through the full pipeline on a MacBook (Apple Silicon, MPS):
MegaDetector v5a → SpeciesNet v4.0.3a classifier → ensemble with the `USA`/`NJ` geofence.
`scripts/evaluate.py` compares the stored predictions with NACTI's ground-truth labels.

Overall: 57/64 correct (89%)

| Ground truth | Correct | Predictions |
|---|---|---|
| raccoon | 3/4 | northern raccoon ×3, empty ×1 |
| eastern gray squirrel | 4/4 | eastern gray squirrel ×4 |
| american black bear | 4/4 | american black bear ×4 |
| bobcat | 4/4 | bobcat ×4 |
| coyote | 4/4 | coyote ×4 |
| striped skunk | 3/4 | striped skunk ×3, mammal ×1 |
| gray fox | 4/4 | grey fox ×4 |
| red fox | 3/4 | red fox ×3, empty ×1 |
| wild turkey | 1/4 | bird ×3, wild turkey ×1 |
| virginia opossum | 3/4 | virginia opossum ×3, empty ×1 |
| unidentified deer | 4/4 | cervidae family ×4 |
| unidentified rabbit | 4/4 | rabbit and hare family ×4 |
| unidentified bird | 4/4 | bird ×4 |
| domestic dog | 4/4 | canine family ×3, domestic dog ×1 |
| empty | 4/4 | empty ×4 |
| vehicle | 4/4 | vehicle ×4 |

How to read the misses:
- **3 photos stored as `empty`** (one each of raccoon, red fox, opossum). MegaDetector found no
  animal above 0.2, so nothing was classified. These are small or dark subjects.
- **Wild turkey → `bird` ×3 and skunk → `mammal` ×1.** The ensemble rolled these up to a broader
  group. They're flagged *uncertain* in the dashboard and in search, never shown as a confident
  species.
- **Domestic dog → `canine family` ×3** counts as correct here, because NACTI's label is the
  coarser one and the dog is in the canine family.

## Sample stored predictions

| File | Category | Det. conf | Box (x, y, w, h, normalized) | Species | Score | Level | Source |
|---|---|---|---|---|---|---|---|
| CA-02_06_07_2016_CA-02_0016460.JPG | animal | 0.90 | 0.823, 0.053, 0.177, 0.908 | american black bear | 0.99 | species | classifier |
| CA-18_09_18_2015_CA-18_0020302.jpg | animal | 0.97 | 0.756, 0.521, 0.244, 0.368 | american black bear | 1.00 | species | classifier |
| CA-06_11_13_2015_CA-06_0008609.jpg | animal | 0.97 | 0.034, 0.483, 0.311, 0.209 | bobcat | 1.00 | species | classifier |
| CA-29_08_03_2015_CA-29_0024869.jpg | animal | 0.92 | 0.187, 0.376, 0.075, 0.166 | bobcat | 1.00 | species | classifier |

Every row also stores the model name and version, the source frame, the capture timestamp and
its source, the top-5 raw classes, and the verification status.

## Search answers on this data

```
Q: What animals have visited?
Visitors: bird (7), american black bear (4), bobcat (4), cervidae family (4), coyote (4), eastern gray squirrel (4), grey fox (4), northern raccoon (4), rabbit and hare family (4), canine family (3), red fox (3), striped skunk (3), virginia opossum (3), domestic dog (1), mammal (1), wild turkey (1).
Q: Show all fox sightings
7 fox encounters (grey fox, red fox). Most recent: Nov 1, 2026 4:38 AM.
Q: What was the rarest species detected?
The rarest species are domestic dog, mammal, wild turkey, seen in 1 encounter. Note: some of these identifications are uncertain.
Q: Were there any bears this week?
No bear sightings found this week.
Q: what's the weather
I don't understand that yet. Try: "What animals have visited?", ...
```

Each answer also returns the encounter IDs it was computed from, and the dashboard links them.
Most times come from the photos' real EXIF timestamps. The fox "most recent" time above is one of
the few synthetic fallbacks (see [limitations.md](limitations.md)).
