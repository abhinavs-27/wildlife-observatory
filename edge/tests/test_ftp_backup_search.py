import ftplib
import io
import json
import threading
import time

import pytest
from conftest import make_jpeg
from test_flow import RACCOON, add_image, classify, detect, animal

from observatory_edge.backup import create_backup, restore_backup, rotate, verify_backup
from observatory_edge.db import connect
from observatory_edge.ftp_receiver import build_server
from observatory_edge.search import UNKNOWN, answer

# ----------------------------------------------------------------------------- FTP receiver


@pytest.fixture
def ftp(tmp_path):
    inbox = tmp_path / "inbox"
    server = build_server(inbox, "camera", "secret", host="127.0.0.1", port=0,
                          passive_ports=None)
    port = server.address[1]
    t = threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True)
    t.start()
    yield inbox, port, server
    server.close_all()


def test_ftp_upload_lands_in_ready_atomically(ftp, tmp_path):
    inbox, port, _ = ftp
    jpg = make_jpeg(tmp_path / "snap.jpg").read_bytes()
    c = ftplib.FTP()
    c.connect("127.0.0.1", port)
    c.login("camera", "secret")
    c.storbinary("STOR snap.jpg", io.BytesIO(jpg))
    c.quit()
    for _ in range(50):
        if (inbox / "ready" / "snap.jpg").exists():
            break
        time.sleep(0.05)
    assert (inbox / "ready" / "snap.jpg").read_bytes() == jpg
    assert not list((inbox / ".incoming").glob("*"))


def test_ftp_refuses_when_disk_floor_reached(tmp_path):
    inbox = tmp_path / "inbox2"
    server = build_server(inbox, "camera", "secret", host="127.0.0.1", port=0,
                          disk_floor_pct=0.0)
    port = server.address[1]
    threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    c = ftplib.FTP()
    c.connect("127.0.0.1", port)
    c.login("camera", "secret")
    with pytest.raises(ftplib.error_temp, match="452"):
        c.storbinary("STOR x.jpg", io.BytesIO(b"abc"))
    c.quit()
    server.close_all()
    assert not list((inbox / "ready").glob("*"))


def test_ftp_wrong_password_rejected(ftp):
    _, port, _ = ftp
    c = ftplib.FTP()
    c.connect("127.0.0.1", port)
    with pytest.raises(ftplib.error_perm):
        c.login("camera", "nope")


# ----------------------------------------------------------------------------- backups


def test_backup_restore_round_trip(conn, settings, tmp_path):
    m = add_image(conn, settings, tmp_path)
    detect(conn, settings, m, [animal()])
    b = create_backup(conn, settings)
    assert verify_backup(b)
    conn.execute("DELETE FROM alert")
    restored = tmp_path / "restored.sqlite"
    restore_backup(b, restored)
    c2 = connect(restored)
    assert c2.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 1
    assert c2.execute("SELECT COUNT(*) FROM encounter").fetchone()[0] == 1
    c2.close()


def test_corrupt_backup_refused(tmp_path):
    bad = tmp_path / "observatory-bad.sqlite"
    bad.write_bytes(b"not a database")
    assert not verify_backup(bad)
    with pytest.raises(RuntimeError):
        restore_backup(bad, tmp_path / "x.sqlite")


def test_rotation_keeps_newest(settings):
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        (settings.backups_dir / f"observatory-2024010{i}T000000Z.sqlite").write_bytes(b"x")
    rotate(settings)
    left = sorted(p.name for p in settings.backups_dir.glob("observatory-*.sqlite"))
    assert len(left) == settings.backups_keep and left[-1].startswith("observatory-20240109")


# ----------------------------------------------------------------------------- search

FOX = "f;mammalia;carnivora;canidae;vulpes;vulpes;red fox"
DEER = "d;mammalia;cetartiodactyla;cervidae;odocoileus;virginianus;white-tailed deer"
SQUIRREL = "s;mammalia;rodentia;sciuridae;sciurus;carolinensis;eastern gray squirrel"


@pytest.fixture
def populated(conn, settings, tmp_path):
    # fox x2 (separate visits), deer x3 (2 at night ~22h local... times are EXIF local), squirrel x1
    plan = [(0, FOX), (1000, FOX), (2000, DEER), (3000, DEER), (4000, DEER), (90000, SQUIRREL)]
    for off, label in plan:
        m = add_image(conn, settings, tmp_path, offset_s=off, live=False)
        detect(conn, settings, m, [animal()])
        classify(conn, settings, m, label)
    return conn


def test_list_species_matches_sql(populated, settings):
    a = answer(populated, settings, "What animals have visited?")
    assert a.intent == "list_species"
    assert {r["species"]: r["encounters"] for r in a.rows} == \
        {"white-tailed deer": 3, "red fox": 2, "eastern gray squirrel": 1}
    assert len(a.sources) == populated.execute("SELECT COUNT(*) FROM encounter").fetchone()[0]


def test_show_fox_sightings_by_group_word(populated, settings):
    a = answer(populated, settings, "Show all fox sightings")
    assert a.intent == "sightings_of" and len(a.sources) == 2
    assert "2 fox encounters" in a.text


def test_squirrels_match_family(populated, settings):
    a = answer(populated, settings, "show me squirrel sightings")
    assert len(a.sources) == 1


def test_deer_activity(populated, settings):
    a = answer(populated, settings, "When are deer most active?")
    assert a.intent == "activity_of"
    assert sum(r["count"] for r in a.rows) == 3
    assert "most active around" in a.text


def test_rarest(populated, settings):
    a = answer(populated, settings, "What was the rarest species detected?")
    assert "eastern gray squirrel" in a.text and len(a.sources) == 1


def test_unknown_question_refused(populated, settings):
    a = answer(populated, settings, "What is the meaning of life?")
    assert a.text == UNKNOWN and a.sources == []


def test_no_sightings_for_absent_species(populated, settings):
    a = answer(populated, settings, "Show all bear sightings")
    assert a.text.startswith("No bear sightings found") and a.sources == []


def test_count_of(populated, settings):
    a = answer(populated, settings, "How many deer visits")
    assert a.text.startswith("3 deer encounters")


def test_empty_db(conn, settings):
    assert answer(conn, settings, "What animals have visited?").text.startswith("No wildlife")
