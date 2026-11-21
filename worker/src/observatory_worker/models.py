"""Model wrappers. `SpeciesNetModels` loads MegaDetector + SpeciesNet once and keeps them resident."""

from __future__ import annotations

import logging
import time
from typing import Protocol

from PIL import Image

log = logging.getLogger("observatory.worker.models")

CATEGORY = {"1": "animal", "2": "person", "3": "vehicle"}
MIN_STORE_CONF = 0.1  # MegaDetector emits down to 0.01; keep the DB lean.


class Models(Protocol):
    detector_info: dict
    classifier_info: dict

    def detect(self, img: Image.Image) -> list[dict]: ...

    def classify(self, img: Image.Image, dets: list[dict], country: str | None,
                 admin1_region: str | None) -> list[dict]: ...


class SpeciesNetModels:
    """In-process SpeciesNet 5.x: SpeciesNetDetector, SpeciesNetClassifier, SpeciesNetEnsemble."""

    def __init__(self, model_name: str | None = None, load_detector: bool = True,
                 load_classifier: bool = True, device: str | None = None):
        import speciesnet
        from speciesnet.classifier import SpeciesNetClassifier
        from speciesnet.detector import SpeciesNetDetector
        from speciesnet.ensemble import SpeciesNetEnsemble

        self.model_name = model_name or speciesnet.DEFAULT_MODEL
        self.load_times: dict[str, float] = {}
        self.detector = self.classifier = self.ensemble = None
        version = self.model_name.rstrip("/").split("/")[-2] if "/" in self.model_name else self.model_name
        self.detector_info = {"name": "MegaDetector", "version": "v5a.0.1"}
        self.classifier_info = {"name": "SpeciesNet", "version": version}
        if load_detector:
            t = time.perf_counter()
            self.detector = SpeciesNetDetector(self.model_name)
            if device and device != self.detector.device:  # e.g. force CPU on a Mac
                self.detector.model = self.detector.model.to(device)
                self.detector.device = device
            self.load_times["detector"] = time.perf_counter() - t
            self.device = self.detector.device
        if load_classifier:
            t = time.perf_counter()
            self.classifier = SpeciesNetClassifier(self.model_name, device=device)
            self.load_times["classifier"] = time.perf_counter() - t
            t = time.perf_counter()
            self.ensemble = SpeciesNetEnsemble(self.model_name, geofence=True)
            self.load_times["ensemble"] = time.perf_counter() - t
            self.device = getattr(self.classifier, "device", "cpu")

    def detect(self, img: Image.Image) -> list[dict]:
        pre = self.detector.preprocess(img.convert("RGB"))
        res = self.detector.predict("frame", pre)
        if "failures" in res:
            raise RuntimeError(f"detector failure: {res['failures']}")
        out = []
        for d in res.get("detections", []):
            if d["conf"] < MIN_STORE_CONF:
                continue
            out.append({"category": CATEGORY.get(d["category"], "animal"),
                        "conf": round(float(d["conf"]), 4),
                        "bbox": [round(float(v), 5) for v in d["bbox"]]})
        return out

    def classify(self, img: Image.Image, dets: list[dict], country: str | None,
                 admin1_region: str | None) -> list[dict]:
        """Classify each detection crop, then run the ensemble (geofence + rollup).

        `dets` are [{detection_id, bbox, conf}] for one frame. Returns one entry per detection.
        """
        from speciesnet.geolocation import find_admin1_region
        from speciesnet.multiprocessing import build_classifier_result
        from speciesnet.utils import BBox

        if not dets:
            return []
        img = img.convert("RGB")
        fp = "frame"
        md_dets = [{"category": "1", "label": "animal", "conf": float(d["conf"]),
                    "bbox": list(d["bbox"])} for d in dets]
        order = sorted(range(len(md_dets)), key=lambda i: -md_dets[i]["conf"])
        md_sorted = [md_dets[i] for i in order]
        indices = list(range(len(md_sorted)))
        crops = self.classifier.preprocess(img, bboxes=[BBox(*d["bbox"]) for d in md_sorted])
        raw = self.classifier.predict(fp, crops, num_classes=5)
        cls_result = build_classifier_result(raw, md_sorted, indices, False)
        geo = {"country": country,
               "admin1_region": find_admin1_region(country, admin1_region, None, None),
               "latitude": None, "longitude": None}
        preds = self.ensemble.combine(
            filepaths=[fp], classifier_results={fp: cls_result},
            detector_results={fp: {"filepath": fp, "detections": md_sorted}},
            geolocation_results={fp: geo}, max_classifications_per_detection=5)
        pred = preds[0]
        if "failures" in pred and pred.get("failures"):
            log.warning("ensemble reported failures: %s", pred["failures"])
        out_dets = pred.get("detections", [])
        results = []
        for pos, orig_i in enumerate(order):
            d = out_dets[pos] if pos < len(out_dets) else {}
            processed = d.get("processed_classification") or pred.get("prediction_info") or {}
            raw_c = d.get("raw_classifications") or {}
            label = processed.get("class") or pred.get("prediction")
            score = processed.get("score", pred.get("prediction_score", 0.0))
            source = processed.get("source", pred.get("prediction_source"))
            topk = [{"label": c, "score": round(float(s), 4)} for c, s in
                    zip(raw_c.get("classes", []), raw_c.get("scores", []))]
            results.append({"detection_id": dets[orig_i]["detection_id"], "label": label,
                            "score": round(float(score or 0), 4), "source": source, "raw": topk})
        return results
