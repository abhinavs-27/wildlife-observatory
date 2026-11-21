import io
import json

import httpx
import numpy as np
import pytest
from PIL import Image

from observatory_worker.client import EdgeClient
from observatory_worker.frames import sample_video
from observatory_worker.runner import Runner


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (100, 120, 80)).save(buf, "JPEG")
    return buf.getvalue()


class FakeModels:
    detector_info = {"name": "FakeMD", "version": "0"}
    classifier_info = {"name": "FakeSN", "version": "0"}

    def __init__(self, dets=None, fail=False):
        self.dets = dets if dets is not None else [{"category": "animal", "conf": 0.9,
                                                    "bbox": [0.1, 0.1, 0.2, 0.2]}]
        self.fail = fail

    def detect(self, img):
        if self.fail:
            raise RuntimeError("model exploded")
        return self.dets

    def classify(self, img, dets, country, admin1):
        return [{"detection_id": d["detection_id"], "label": "x;;;;;;red fox", "score": 0.9,
                 "source": "classifier", "raw": []} for d in dets]


class FakeEdge:
    def __init__(self, job):
        self.job = job
        self.calls = []

    def handler(self, request: httpx.Request):
        path = request.url.path
        body = request.content
        self.calls.append((request.method, path, body))
        if path == "/jobs/claim":
            if self.job is None:
                return httpx.Response(204)
            j, self.job = self.job, None
            return httpx.Response(200, json=j)
        if path.startswith("/media/") or path.startswith("/frames/"):
            return httpx.Response(200, content=jpeg())
        if path.endswith("/frames"):
            return httpx.Response(200, json={"frames": [{"idx": 0, "frame_id": 77}]})
        return httpx.Response(200, json={"ok": True})


def make(job, models):
    edge = FakeEdge(job)
    client = EdgeClient("http://edge", "t", transport=httpx.MockTransport(edge.handler))
    return edge, Runner(client, models, ["detect", "classify"], "w")


DETECT_JOB = {"job_id": 1, "kind": "detect", "claim_token": "tok", "lease_s": 600,
              "media": {"id": 5, "kind": "image", "url": "/media/5/original"},
              "frames": [{"frame_id": 11, "idx": 0, "url": "/frames/11/file"}],
              "geofence": {"country": "USA", "admin1_region": "NJ"}}


def test_detect_posts_frames_with_detections():
    edge, runner = make(dict(DETECT_JOB), FakeModels())
    assert runner.run_once() is True
    method, path, body = edge.calls[-1]
    assert path == "/jobs/1/result"
    payload = json.loads(body)
    assert payload["claim_token"] == "tok"
    assert payload["model"]["name"] == "FakeMD"
    assert payload["frames"] == [{"frame_id": 11, "detections": FakeModels().dets}]


def test_empty_queue_returns_false():
    edge, runner = make(None, FakeModels())
    assert runner.run_once() is False


def test_model_failure_reports_non_retryable():
    edge, runner = make(dict(DETECT_JOB), FakeModels(fail=True))
    runner.run_once()
    method, path, body = edge.calls[-1]
    assert path == "/jobs/1/fail"
    p = json.loads(body)
    assert p["retryable"] is False and "model exploded" in p["error"]


def test_classify_returns_per_detection_labels():
    job = {"job_id": 2, "kind": "classify", "claim_token": "c", "lease_s": 600,
           "media": {"id": 5, "kind": "image", "url": "/media/5/original"}, "frames": [],
           "geofence": {"country": "USA", "admin1_region": "NJ"},
           "classify_inputs": [{"frame_id": 11, "url": "/frames/11/file",
                                "detections": [{"detection_id": 3, "conf": 0.9,
                                                "bbox": [0.1, 0.1, 0.2, 0.2]},
                                               {"detection_id": 4, "conf": 0.8,
                                                "bbox": [0.5, 0.1, 0.2, 0.2]}]}]}
    edge, runner = make(job, FakeModels())
    runner.run_once()
    payload = json.loads(edge.calls[-1][2])
    assert [c["detection_id"] for c in payload["classifications"]] == [3, 4]
    assert payload["geofence"]["admin1_region"] == "NJ"


def test_sample_video(tmp_path):
    cv2 = pytest.importorskip("cv2")
    p = tmp_path / "clip.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for i in range(30):
        w.write(np.full((48, 64, 3), i * 8, dtype=np.uint8))
    w.release()
    frames = sample_video(p, fps=1.0, max_frames=10)
    assert len(frames) == 3
    assert [round(o, 1) for _, o, _ in frames] == [0.0, 1.0, 2.0]
