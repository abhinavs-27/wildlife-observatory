#!/usr/bin/env python3
"""Compare stored predictions with the NACTI ground-truth labels in samples/manifest.csv.

  python3 -I scripts/evaluate.py --db data/observatory.sqlite --samples samples [--md out.md]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
from collections import Counter
from pathlib import Path

# Ground-truth names that SpeciesNet spells differently, or that are coarser than species.
ALIASES = {
    "raccoon": {"northern raccoon"},
    "gray fox": {"grey fox"},
    "unidentified deer": {"cervidae family", "white-tailed deer", "mule deer", "deer"},
    "unidentified rabbit": {"rabbit and hare family", "eastern cottontail", "lagomorpha order"},
    "unidentified bird": {"bird"},
    "domestic dog": {"domestic dog", "canine family"},
}


def matches(truth: str, pred: str) -> bool:
    return pred == truth or pred in ALIASES.get(truth, set())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--samples", type=Path, required=True)
    ap.add_argument("--md", type=Path)
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = []
    for r in csv.DictReader(open(a.samples / "manifest.csv")):
        digest = hashlib.sha256((a.samples / r["path"]).read_bytes()).hexdigest()
        m = conn.execute("SELECT * FROM media WHERE sha256=?", (digest,)).fetchone()
        if not m:
            continue
        det = conn.execute(
            "SELECT d.id, d.category, d.confidence FROM detection d WHERE d.media_id=? "
            "AND d.run_id=? ORDER BY (d.category='animal') DESC, d.confidence DESC LIMIT 1",
            (m["id"], m["active_detection_run_id"])).fetchone()
        cls = conn.execute(
            "SELECT common_name, score, is_uncertain FROM classification WHERE detection_id=? "
            "ORDER BY id DESC LIMIT 1", (det["id"],)).fetchone() if det else None
        truth = r["label"]
        if truth == "empty":
            pred, ok = ("empty" if m["status"] == "empty" else f"{det['category']}"), m["status"] == "empty"
        elif truth == "vehicle":
            pred = det["category"] if det else "empty"
            ok = pred == "vehicle"
        else:
            pred = cls["common_name"] if cls else (m["status"])
            ok = bool(cls) and matches(truth, cls["common_name"])
        rows.append({"file": Path(r["path"]).name, "truth": truth, "pred": pred,
                     "det_conf": round(det["confidence"], 2) if det else None,
                     "score": round(cls["score"], 2) if cls else None,
                     "uncertain": bool(cls["is_uncertain"]) if cls else None, "ok": ok})
    acc = sum(r["ok"] for r in rows) / max(1, len(rows))
    by_truth = Counter(r["truth"] for r in rows)
    ok_truth = Counter(r["truth"] for r in rows if r["ok"])
    lines = [f"Overall: {sum(r['ok'] for r in rows)}/{len(rows)} correct ({acc:.0%})", "",
             "| Ground truth | Correct | Predictions |", "|---|---|---|"]
    for t in by_truth:
        preds = Counter(r["pred"] for r in rows if r["truth"] == t)
        lines.append(f"| {t} | {ok_truth[t]}/{by_truth[t]} | "
                     + ", ".join(f"{p} ×{n}" for p, n in preds.most_common()) + " |")
    text = "\n".join(lines)
    print(text)
    if a.md:
        a.md.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
