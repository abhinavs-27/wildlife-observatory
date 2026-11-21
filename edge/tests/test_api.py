import io
from datetime import timedelta

import pytest
from conftest import make_jpeg
from fastapi.testclient import TestClient

from observatory_edge.api import create_app
from observatory_edge.db import connect, parse_iso, to_iso
from observatory_edge.ingest import ingest_file

AUTH = {"Authorization": "Bearer dev-token"}


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


@pytest.fixture
def media_id(settings, tmp_path, client):
    c = connect(settings.db_path)
    r = ingest_file(c, settings, make_jpeg(tmp_path / "x.jpg", exif_dt="2024:06:01 06:42:00"))
    c.execute("UPDATE media SET suppress_alerts=0")
    c.close()
    return r.media_id


def claim(client, kinds=("detect",)):
    return client.post("/jobs/claim", json={"kinds": list(kinds), "worker_id": "w"}, headers=AUTH)


def test_claim_requires_token(client, media_id):
    assert client.post("/jobs/claim", json={"kinds": ["detect"], "worker_id": "w"}).status_code == 401


def test_claim_then_empty_queue(client, media_id):
    r = claim(client)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "detect" and body["claim_token"]
    assert body["frames"][0]["url"].startswith("/frames/")
    assert body["geofence"] == {"country": "USA", "admin1_region": "NJ"}
    assert claim(client).status_code == 204
    assert client.get(body["media"]["url"]).status_code == 200


def test_full_detect_and_classify_round_trip(client, media_id):
    job = claim(client).json()
    res = client.post(f"/jobs/{job['job_id']}/result", headers=AUTH, json={
        "claim_token": job["claim_token"], "model": {"name": "MegaDetector", "version": "v5a"},
        "frames": [{"frame_id": job["frames"][0]["frame_id"],
                    "detections": [{"category": "animal", "conf": 0.9,
                                    "bbox": [0.1, 0.1, 0.3, 0.3]}]}]})
    assert res.status_code == 200, res.text
    cjob = claim(client, ["classify"]).json()
    inputs = cjob["classify_inputs"]
    assert len(inputs) == 1 and len(inputs[0]["detections"]) == 1
    det_id = inputs[0]["detections"][0]["detection_id"]
    r2 = client.post(f"/jobs/{cjob['job_id']}/result", headers=AUTH, json={
        "claim_token": cjob["claim_token"], "model": {"name": "SpeciesNet", "version": "v4.0.3a"},
        "classifications": [{"detection_id": det_id,
                             "label": "x;mammalia;carnivora;canidae;vulpes;vulpes;red fox",
                             "score": 0.88}]})
    assert r2.status_code == 200, r2.text
    encs = client.get("/api/encounters").json()
    assert encs[0]["species"][0]["species"] == "red fox"
    detail = client.get(f"/api/encounters/{encs[0]['id']}").json()
    det = detail["media"][0]["detections"][0]
    assert det["model"] == "MegaDetector" and det["classification"]["model"] == "SpeciesNet"
    assert client.post("/api/ask", json={"question": "Show all fox sightings"}).json()["sources"] \
        == [encs[0]["id"]]


def test_stale_token_after_lease_expiry_gets_409(client, settings, media_id):
    job = claim(client).json()
    c = connect(settings.db_path)
    past = to_iso(parse_iso("2020-01-01T00:00:00Z"))
    c.execute("UPDATE job SET lease_until=? WHERE id=?", (past, job["job_id"]))
    c.close()
    job2 = claim(client).json()
    assert job2["job_id"] == job["job_id"] and job2["claim_token"] != job["claim_token"]
    stale = client.post(f"/jobs/{job['job_id']}/result", headers=AUTH, json={
        "claim_token": job["claim_token"],
        "frames": [{"frame_id": job["frames"][0]["frame_id"],
                    "detections": [{"category": "animal", "conf": 0.9, "bbox": [0, 0, .1, .1]}]}]})
    assert stale.status_code == 409
    c = connect(settings.db_path)
    assert c.execute("SELECT COUNT(*) FROM detection").fetchone()[0] == 0
    c.close()


def test_fail_retry_then_permanent(client, settings, media_id):
    for expected in ("queued", "queued", "failed"):
        c = connect(settings.db_path)
        c.execute("UPDATE job SET not_before=NULL")
        c.close()
        job = claim(client).json()
        r = client.post(f"/jobs/{job['job_id']}/fail", headers=AUTH,
                        json={"claim_token": job["claim_token"], "error": "boom"})
        assert r.json()["status"] == expected
    c = connect(settings.db_path)
    m = c.execute("SELECT status, error FROM media").fetchone()
    assert m["status"] == "failed" and m["error"] == "boom"
    c.close()


def test_frame_upload_for_video_job(client, settings, media_id):
    job = claim(client).json()
    buf = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (32, 32)).save(buf, "JPEG")
    r = client.post(f"/jobs/{job['job_id']}/frames", headers=AUTH,
                    data={"claim_token": job["claim_token"], "indexes": "5",
                          "time_offsets": "5.0"},
                    files=[("files", ("f5.jpg", buf.getvalue(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    fid = r.json()["frames"][0]["frame_id"]
    assert client.get(f"/frames/{fid}/file").content == buf.getvalue()


def test_health_and_dashboard_endpoints(client, media_id):
    assert client.get("/api/health").json() == {"ok": True}
    h = client.get("/api/health/details").json()
    assert "Detection paused" in " ".join(h["problems"])
    assert client.get("/api/stats").json()["media"] == 1
    assert client.get("/api/media").json()[0]["id"] == media_id
    assert client.get("/api/activity").json()["total"] == 0
    assert client.post("/api/corrections", json={"target_type": "encounter", "target_id": 99,
                                                 "action": "confirm"}).status_code == 422
