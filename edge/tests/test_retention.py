from datetime import datetime, timedelta, timezone

from conftest import make_jpeg
from test_flow import RACCOON, add_image, animal, classify, detect

from observatory_edge.corrections import add_correction
from observatory_edge.queries import health_details
from observatory_edge.retention import run_retention

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)  # everything ingested "today" is old by then


def file_of(conn, settings, mid):
    p = conn.execute("SELECT original_path FROM media WHERE id=?", (mid,)).fetchone()[0]
    return settings.data_dir / p


def make(conn, settings, tmp_path, dets, label=None, offset=0):
    m = add_image(conn, settings, tmp_path, offset_s=offset, live=False)
    detect(conn, settings, m, dets)
    if label:
        classify(conn, settings, m, label)
    return m


def test_old_empty_and_person_only_files_purged_rows_kept(conn, settings, tmp_path):
    empty = make(conn, settings, tmp_path, [])
    person = make(conn, settings, tmp_path, [{"category": "person", "conf": 0.9, "bbox": [0, 0, .2, .5]}], offset=500)
    both = make(conn, settings, tmp_path, [animal(), {"category": "person", "conf": 0.9, "bbox": [.6, 0, .2, .5]}],
                RACCOON, offset=1000)
    stats = run_retention(conn, settings, now=NOW, disk_pct=lambda: 10)
    assert stats["empty"] == 1 and stats["person"] == 1
    assert not file_of(conn, settings, empty).exists() and not file_of(conn, settings, person).exists()
    assert file_of(conn, settings, both).exists()
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 3
    assert conn.execute("SELECT purge_reason FROM media WHERE id=?", (empty,)).fetchone()[0] == "empty"


def test_recent_empty_kept(conn, settings, tmp_path):
    m = make(conn, settings, tmp_path, [])
    run_retention(conn, settings, disk_pct=lambda: 10)
    assert file_of(conn, settings, m).exists()


def test_disk_pressure_deletes_oldest_unprotected_animal_photos(conn, settings, tmp_path):
    a = make(conn, settings, tmp_path, [animal()], RACCOON, offset=0)
    b = make(conn, settings, tmp_path, [animal()], RACCOON, offset=10_000)
    c = make(conn, settings, tmp_path, [animal()], RACCOON, offset=20_000)
    enc_b = conn.execute("SELECT encounter_id FROM encounter_media WHERE media_id=?", (b,)).fetchone()[0]
    add_correction(conn, settings, "encounter", enc_b, "confirm", None)
    levels = iter([90, 90, 90, 90, 80])  # disk drops below 85% after one deletion
    stats = run_retention(conn, settings, now=NOW, disk_pct=lambda: next(levels, 80))
    assert file_of(conn, settings, b).exists()  # corrected: protected
    deleted = [m for m in (a, c) if not file_of(conn, settings, m).exists()]
    assert stats["animal"] == len(deleted) >= 1
    # the species portrait (best detection) stays
    portrait_frame = conn.execute(
        "SELECT d.frame_id FROM encounter e JOIN detection d ON d.id=e.best_detection_id "
        "ORDER BY d.confidence DESC LIMIT 1").fetchone()[0]
    assert (settings.data_dir / conn.execute("SELECT path FROM frame WHERE id=?", (portrait_frame,)).fetchone()[0]).exists()


def test_no_disk_pressure_keeps_animal_photos(conn, settings, tmp_path):
    a = make(conn, settings, tmp_path, [animal()], RACCOON)
    run_retention(conn, settings, now=NOW, disk_pct=lambda: 50)
    assert file_of(conn, settings, a).exists()


def test_camera_silent_problem(conn, settings, tmp_path):
    from observatory_edge.ingest import ingest_file
    ingest_file(conn, settings, make_jpeg(tmp_path / "cam.jpg"), adapter="folder")
    assert not any("No new photos" in p for p in health_details(conn, settings)["problems"])
    old = (datetime.now(timezone.utc) - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute("UPDATE media SET created_at=?", (old,))
    probs = health_details(conn, settings)["problems"]
    assert any("No new photos from the camera for 40 hours" in p for p in probs)


def test_cli_imports_dont_count_as_camera(conn, settings, tmp_path):
    make(conn, settings, tmp_path, [])  # add_image uses default adapter 'folder'; force cli
    conn.execute("UPDATE media SET source_adapter='cli', created_at='2020-01-01T00:00:00.000000Z'")
    assert not any("No new photos" in p for p in health_details(conn, settings)["problems"])
