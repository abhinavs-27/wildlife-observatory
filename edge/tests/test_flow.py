import json
from datetime import datetime, timedelta

import pytest
from conftest import make_jpeg

from observatory_edge.corrections import add_correction
from observatory_edge.ingest import ingest_file
from observatory_edge.jobs import claim_job
from observatory_edge.results import apply_classify_result, apply_detect_result, classify_inputs

RACCOON = "dac637...;mammalia;carnivora;procyonidae;procyon;lotor;northern raccoon"
SQUIRRELS = "abc;mammalia;rodentia;sciuridae;;;squirrel family"
BASE = datetime(2024, 6, 1, 6, 40, 0)
_counter = [0]


def add_image(conn, settings, tmp_path, offset_s=0, live=True, device="cam"):
    _counter[0] += 1
    c = _counter[0]
    dt = (BASE + timedelta(seconds=offset_s)).strftime("%Y:%m:%d %H:%M:%S")
    p = make_jpeg(tmp_path / f"img{c}.jpg", color=(c % 255, (c * 7) % 255, 9), exif_dt=dt)
    r = ingest_file(conn, settings, p, device_name=device)
    assert r.status == "created"
    # ingest suppresses alerts for old captures; tests simulate live captures explicitly
    conn.execute("UPDATE media SET suppress_alerts=? WHERE id=?", (0 if live else 1, r.media_id))
    return r.media_id


def detect(conn, settings, media_id, dets):
    job = claim_job(conn, ["detect"], "w1", 600)
    assert job["media_id"] == media_id
    frame = conn.execute("SELECT id FROM frame WHERE media_id=?", (media_id,)).fetchone()["id"]
    payload = {"claim_token": job["claim_token"],
               "model": {"name": "MegaDetector", "version": "v5a.0.1"},
               "frames": [{"frame_id": frame, "detections": dets}]}
    return apply_detect_result(conn, settings, job, payload)


def classify(conn, settings, media_id, label, score=0.9):
    job = claim_job(conn, ["classify"], "w2", 600)
    assert job and job["media_id"] == media_id
    inputs = classify_inputs(conn, settings, media_id)
    cls = [{"detection_id": d["detection_id"], "label": label, "score": score,
            "source": "classifier", "raw": [{"label": label, "score": score}]}
           for f in inputs for d in f["detections"]]
    payload = {"claim_token": job["claim_token"],
               "model": {"name": "SpeciesNet", "version": "v4.0.3a"},
               "geofence": {"country": "USA", "admin1_region": "NJ"},
               "classifications": cls}
    return apply_classify_result(conn, settings, job, payload)


def animal(x=0.2, conf=0.9):
    return {"category": "animal", "conf": conf, "bbox": [x, 0.3, 0.2, 0.2]}


def encounters(conn):
    return conn.execute("SELECT * FROM encounter ORDER BY id").fetchall()


def test_single_animal_creates_pending_encounter_and_one_alert(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    encs = encounters(conn)
    assert len(encs) == 1
    assert json.loads(encs[0]["species_json"])[0]["species"] == "pending"
    assert encs[0]["status"] == "pending"
    alerts = conn.execute("SELECT * FROM alert").fetchall()
    assert len(alerts) == 1 and "Animal detected (1 animal)" in alerts[0]["body"]
    assert conn.execute("SELECT COUNT(*) FROM job WHERE kind='classify'").fetchone()[0] == 1


def test_burst_is_one_encounter_one_alert(conn, settings, tmp_path):
    for i in range(6):
        m = add_image(conn, settings, tmp_path, offset_s=i * 5)
        detect(conn, settings, m, [animal(x=0.2 + i * 0.01)])
    assert len(encounters(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM track").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 1


def test_multiple_animals_in_one_image_count_two(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal(x=0.05), animal(x=0.7)])
    sp = json.loads(encounters(conn)[0]["species_json"])
    assert sp[0]["count"] == 2
    assert "2 animals" in conn.execute("SELECT body FROM alert").fetchone()[0]


def test_empty_image(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [])
    assert conn.execute("SELECT status FROM media WHERE id=?", (m,)).fetchone()[0] == "empty"
    assert encounters(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM job WHERE kind='classify'").fetchone()[0] == 0


def test_person_with_animal_is_privacy_restricted(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal(), {"category": "person", "conf": 0.95,
                                          "bbox": [0.6, 0.1, 0.2, 0.6]}])
    assert conn.execute("SELECT has_person FROM media WHERE id=?", (m,)).fetchone()[0] == 1
    enc = encounters(conn)[0]
    assert enc["best_frame_id"] is None
    alert = conn.execute("SELECT * FROM alert").fetchone()
    assert alert["attach_frame_id"] is None


def test_bridging_capture_merges_into_earliest(conn, settings, tmp_path):
    a = add_image(conn, settings, tmp_path, offset_s=0)
    detect(conn, settings, a, [animal()])
    b = add_image(conn, settings, tmp_path, offset_s=210)  # 3.5 min later: separate
    detect(conn, settings, b, [animal()])
    ids = [e["id"] for e in encounters(conn)]
    assert len(ids) == 2
    c = add_image(conn, settings, tmp_path, offset_s=110)  # bridges both (gap 120 s)
    detect(conn, settings, c, [animal()])
    encs = encounters(conn)
    assert [e["id"] for e in encs] == [min(ids)]
    assert all(r[0] == min(ids) for r in conn.execute("SELECT encounter_id FROM alert"))


def test_suppressed_capture_never_alerts(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path, live=False)
    detect(conn, settings, m, [animal()])
    assert len(encounters(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 0


def test_low_confidence_animal_does_not_alert(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal(conf=0.3)])
    assert len(encounters(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 0


def test_late_classification_updates_species_without_second_alert(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    enc_id = encounters(conn)[0]["id"]
    classify(conn, settings, m, RACCOON, 0.93)
    encs = encounters(conn)
    assert [e["id"] for e in encs] == [enc_id]
    sp = json.loads(encs[0]["species_json"])
    assert sp[0]["species"] == "northern raccoon" and sp[0]["uncertain"] is False
    assert encs[0]["status"] == "classified"
    assert conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 1
    c = conn.execute("SELECT * FROM classification").fetchone()
    assert c["taxon_genus"] == "procyon" and c["rollup_level"] == "species"


def test_rolled_up_classification_is_uncertain(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    classify(conn, settings, m, SQUIRRELS, 0.8)
    sp = json.loads(encounters(conn)[0]["species_json"])
    assert sp[0]["species"] == "squirrel family" and sp[0]["uncertain"] is True


def test_correction_changes_effective_label_not_prediction(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    classify(conn, settings, m, SQUIRRELS, 0.8)
    enc = encounters(conn)[0]
    add_correction(conn, settings, "encounter", enc["id"], "relabel", "eastern gray squirrel")
    enc = encounters(conn)[0]
    sp = json.loads(enc["species_json"])
    assert sp[0]["species"] == "eastern gray squirrel" and sp[0]["corrected"] is True
    assert conn.execute("SELECT common_name FROM classification").fetchone()[0] == "squirrel family"


def test_encounter_correction_survives_regrouping(conn, settings, tmp_path):
    a = add_image(conn, settings, tmp_path, offset_s=0)
    detect(conn, settings, a, [animal()])
    enc_id = encounters(conn)[0]["id"]
    add_correction(conn, settings, "encounter", enc_id, "relabel", "red fox")
    conn.execute("DELETE FROM encounter_track")
    conn.execute("DELETE FROM track")
    conn.execute("DELETE FROM encounter_media")
    conn.execute("UPDATE alert SET encounter_id=NULL")
    conn.execute("DELETE FROM encounter")  # simulate full rebuild from scratch
    b = add_image(conn, settings, tmp_path, offset_s=20)
    detect(conn, settings, b, [animal()])
    enc = encounters(conn)[0]
    corr = conn.execute("SELECT target_id FROM correction").fetchone()[0]
    assert corr == enc["id"]
    assert json.loads(enc["species_json"])[0]["species"] == "red fox"


def test_reject_detection_removes_it_from_encounters(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    det = conn.execute("SELECT id FROM detection").fetchone()[0]
    add_correction(conn, settings, "detection", det, "reject", None)
    assert encounters(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM detection").fetchone()[0] == 1  # prediction kept


def test_bad_frame_id_rejected(conn, settings, tmp_path):
    from observatory_edge.results import ResultError
    m = add_image(conn, settings, tmp_path)
    job = claim_job(conn, ["detect"], "w", 600)
    with pytest.raises(ResultError):
        apply_detect_result(conn, settings, job, {"claim_token": job["claim_token"],
                                                 "frames": [{"frame_id": 9999, "detections": []}]})
    assert conn.execute("SELECT COUNT(*) FROM detection").fetchone()[0] == 0


def test_species_summary_has_portrait_frame(conn, settings, tmp_path):
    from observatory_edge.queries import species_summary
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    classify(conn, settings, m, RACCOON)
    frame = conn.execute("SELECT id FROM frame WHERE media_id=?", (m,)).fetchone()[0]
    row = species_summary(conn)[0]
    assert row["species"] == "northern raccoon"
    assert row["best_frame_id"] == frame
    assert row["best_bbox"] == [0.2, 0.3, 0.2, 0.2]


def test_species_portrait_skips_person_media(conn, settings, tmp_path):
    from observatory_edge.queries import species_summary
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal(), {"category": "person", "conf": 0.9,
                                          "bbox": [0.6, 0.1, 0.2, 0.6]}])
    classify(conn, settings, m, RACCOON)
    assert species_summary(conn)[0]["best_frame_id"] is None
