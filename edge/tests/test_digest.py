import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from test_flow import RACCOON, add_image, animal, classify, detect

import test_flow
from observatory_edge.digest import build_digest, maybe_send_weekly, send_digest

FOX = "f;mammalia;carnivora;canidae;vulpes;vulpes;red fox"
DEER = "d;mammalia;cetartiodactyla;cervidae;odocoileus;virginianus;white-tailed deer"
MONDAY = date(2024, 6, 3)


@pytest.fixture(autouse=True)
def _restore_base():
    saved = test_flow.BASE
    yield
    test_flow.BASE = saved


def visit(conn, settings, tmp_path, when, label, score=0.9, person=False):
    test_flow.BASE = when
    m = add_image(conn, settings, tmp_path, live=False)
    dets = [animal()]
    if person:
        dets.append({"category": "person", "conf": 0.9, "bbox": [0.6, 0.1, 0.2, 0.6]})
    detect(conn, settings, m, dets)
    classify(conn, settings, m, label, score)


def test_week_counts_and_best_photo(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 3, 22, 0), RACCOON, 0.85)
    visit(conn, settings, tmp_path, datetime(2024, 6, 5, 23, 0), RACCOON, 0.90)
    visit(conn, settings, tmp_path, datetime(2024, 6, 6, 21, 0), FOX, 0.97)
    visit(conn, settings, tmp_path, datetime(2024, 6, 9, 23, 30), DEER, 0.80)  # Sunday night counts
    visit(conn, settings, tmp_path, datetime(2024, 6, 10, 23, 0), DEER, 0.99)  # next week
    d = build_digest(conn, settings, MONDAY)
    assert d["week"] == "2024-W23" and d["visits"] == 4 and d["species"] == 3
    assert d["best_species"] == "red fox"
    assert d["headline"] == "This week in the yard: 4 visits from 3 species."
    assert set(d["new_species"]) == {"northern raccoon", "red fox", "white-tailed deer"}


def test_person_photo_never_best(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 4, 22, 0), FOX, 0.99, person=True)
    visit(conn, settings, tmp_path, datetime(2024, 6, 5, 22, 0), RACCOON, 0.7)
    assert build_digest(conn, settings, MONDAY)["best_species"] == "northern raccoon"


def test_quiet_week(conn, settings):
    d = build_digest(conn, settings, MONDAY)
    assert d["headline"].startswith("A quiet week") and d["best_frame_id"] is None


def test_send_is_idempotent_and_queues_both_channels(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 4, 22, 0), FOX)
    s = settings.with_(dashboard_url="http://observatory:3000")
    assert send_digest(conn, s, MONDAY) is True
    assert send_digest(conn, s, MONDAY) is False
    rows = conn.execute("SELECT channel, link, body FROM alert WHERE kind='digest' ORDER BY channel").fetchall()
    assert [r["channel"] for r in rows] == ["family", "owner"]
    assert rows[0]["link"] is None and rows[1]["link"].endswith("/digest/2024-W23")
    assert "red fox" in rows[0]["body"]
    stored = json.loads(conn.execute("SELECT payload_json FROM digest").fetchone()[0])
    assert stored["visits"] == 1


def test_weekly_trigger_only_monday_morning(conn, settings):
    tz = ZoneInfo("America/New_York")
    assert maybe_send_weekly(conn, settings, datetime(2024, 6, 10, 7, 59, tzinfo=tz)) is False
    assert maybe_send_weekly(conn, settings, datetime(2024, 6, 11, 9, 0, tzinfo=tz)) is False
    assert maybe_send_weekly(conn, settings, datetime(2024, 6, 10, 8, 0, tzinfo=tz)) is True
    assert conn.execute("SELECT week FROM digest").fetchone()[0] == "2024-W23"
