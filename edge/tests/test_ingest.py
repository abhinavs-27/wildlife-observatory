import os
import time

from conftest import make_jpeg

from observatory_edge.adapters import LocalFolderAdapter, import_folder
from observatory_edge.ingest import ingest_file
from observatory_edge.timeparse import extract_captured_at


def test_naive_exif_interpreted_in_camera_timezone(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg", exif_dt="2024:06:01 06:42:00")
    ts, src = extract_captured_at(p, "America/New_York")
    assert ts.startswith("2024-06-01T10:42:00")
    assert src == "exif"


def test_no_exif_falls_back_to_mtime(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg")
    os.utime(p, (1_700_000_000, 1_700_000_000))
    ts, src = extract_captured_at(p, "America/New_York")
    assert src == "mtime"
    assert ts.startswith("2023-11-14T22:13:20")


def test_ingest_creates_media_event_frame_and_detect_job(conn, settings, tmp_path):
    p = make_jpeg(tmp_path / "in" / "fox.jpg", exif_dt="2024:06:01 06:42:00")
    r = ingest_file(conn, settings, p)
    assert r.status == "created"
    m = conn.execute("SELECT * FROM media").fetchone()
    assert m["kind"] == "image" and m["original_name"] == "fox.jpg"
    assert (settings.data_dir / m["original_path"]).exists()
    assert conn.execute("SELECT COUNT(*) FROM event WHERE kind='capture'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM frame WHERE media_id=?", (m["id"],)).fetchone()[0] == 1
    job = conn.execute("SELECT * FROM job").fetchone()
    assert job["kind"] == "detect" and job["status"] == "queued"


def test_duplicate_import_is_noop(conn, settings, tmp_path):
    p = make_jpeg(tmp_path / "in" / "a.jpg")
    assert ingest_file(conn, settings, p).status == "created"
    assert ingest_file(conn, settings, p).status == "duplicate"
    copy = tmp_path / "in" / "renamed.jpg"
    copy.write_bytes(p.read_bytes())
    assert ingest_file(conn, settings, copy).status == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 1


def test_corrupt_file_fails_then_quarantines(conn, settings, tmp_path):
    bad = tmp_path / "in" / "bad.jpg"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    assert ingest_file(conn, settings, bad).status == "failed"
    assert ingest_file(conn, settings, bad).status == "failed"
    r = ingest_file(conn, settings, bad)
    assert r.status == "quarantined"
    assert not bad.exists()
    assert (settings.quarantine_dir / "bad.jpg").exists()
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0


def test_unsupported_extension(conn, settings, tmp_path):
    t = tmp_path / "notes.txt"
    t.write_text("hi")
    assert ingest_file(conn, settings, t).status == "unsupported"
    assert t.exists()


def test_folder_adapter_skips_growing_files(tmp_path):
    root = tmp_path / "inbox"
    old = make_jpeg(root / "old.jpg")
    os.utime(old, (time.time() - 60, time.time() - 60))
    make_jpeg(root / "new.jpg")  # just written
    ad = LocalFolderAdapter(root, stable_seconds=30)
    assert [p.name for p in ad.discover()] == ["old.jpg"]


def test_import_folder_suppresses_alerts(conn, settings, tmp_path):
    make_jpeg(tmp_path / "s" / "a.jpg", color=(1, 2, 3))
    make_jpeg(tmp_path / "s" / "sub" / "b.jpg", color=(4, 5, 6))
    counts = import_folder(conn, settings, tmp_path / "s", device="cam1")
    assert counts["created"] == 2
    assert conn.execute("SELECT COUNT(*) FROM media WHERE suppress_alerts=1").fetchone()[0] == 2
