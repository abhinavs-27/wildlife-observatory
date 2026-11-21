import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from test_flow import RACCOON, add_image, animal, classify, detect

import test_flow
from observatory_edge.api import create_app
from observatory_edge.insights import compute_insights

import pytest


@pytest.fixture(autouse=True)
def _restore_base():
    saved = test_flow.BASE
    yield
    test_flow.BASE = saved


FOX = "f;mammalia;carnivora;canidae;vulpes;vulpes;red fox"
SQUIRRELS = "abc;mammalia;rodentia;sciuridae;;;squirrel family"


def visit(conn, settings, tmp_path, when_local: datetime, label=RACCOON, score=0.9):
    """Create one confident visit at a local (America/New_York, naive) time."""
    test_flow.BASE = when_local
    m = add_image(conn, settings, tmp_path, offset_s=0, live=False)
    detect(conn, settings, m, [animal()])
    classify(conn, settings, m, label, score)
    return m


def kinds(ins, species=None):
    return {i.kind for i in ins if species is None or i.species == species}


def test_empty_db_has_no_insights(conn, settings):
    assert compute_insights(conn, settings) == []


def test_timing_vs_sunset_needs_five_visits(conn, settings, tmp_path):
    base = datetime(2024, 6, 1, 22, 30)  # sunset ~20:25 EDT, so ~2 h after
    for i in range(4):
        visit(conn, settings, tmp_path, base + timedelta(days=i * 3))
    assert "timing_vs_sun" not in kinds(compute_insights(conn, settings), "northern raccoon")
    visit(conn, settings, tmp_path, base + timedelta(days=13))
    ins = [i for i in compute_insights(conn, settings, species="northern raccoon")
           if i.kind == "timing_vs_sun"]
    assert ins and "about 2 h after sunset" in ins[0].text and ins[0].n == 5


def test_trend_doubled(conn, settings, tmp_path):
    now = datetime(2024, 7, 1, tzinfo=timezone.utc)
    for i in range(8):
        visit(conn, settings, tmp_path, datetime(2024, 6, 5, 23, 0) + timedelta(days=i * 3), FOX)
    for i in range(4):
        visit(conn, settings, tmp_path, datetime(2024, 5, 5, 23, 0) + timedelta(days=i * 5), FOX)
    ins = [i for i in compute_insights(conn, settings, species="red fox", now=now) if i.kind == "trend"]
    assert ins and "doubled" in ins[0].text and "(8 vs 4" in ins[0].text
    n_sql = conn.execute("SELECT COUNT(*) FROM encounter WHERE start_at >= ?",
                         ("2024-06-01",)).fetchone()[0]
    assert n_sql == 8


def test_trend_silent_below_minimum(conn, settings, tmp_path):
    now = datetime(2024, 7, 1, tzinfo=timezone.utc)
    for i in range(4):
        visit(conn, settings, tmp_path, datetime(2024, 6, 5, 23, 0) + timedelta(days=i * 3), FOX)
    visit(conn, settings, tmp_path, datetime(2024, 5, 10, 23, 0), FOX)
    assert "trend" not in kinds(compute_insights(conn, settings, now=now))


def test_uncertain_classifications_excluded(conn, settings, tmp_path):
    for i in range(6):
        visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 30) + timedelta(days=i * 2), SQUIRRELS)
    assert compute_insights(conn, settings, species="squirrel family") == []


def test_regular_visitor(conn, settings, tmp_path):
    now = datetime(2024, 6, 10, 15, 0, tzinfo=timezone.utc)
    for d in (3, 4, 6, 8, 9):
        visit(conn, settings, tmp_path, datetime(2024, 6, d, 23, 0))
    ins = [i for i in compute_insights(conn, settings, now=now) if i.kind == "regular"]
    assert ins and "visited 5 of the last 7 nights" in ins[0].text


def test_species_detail_and_frames_api(settings, conn, tmp_path):
    for i in range(5):
        visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 30) + timedelta(days=i * 2))
    client = TestClient(create_app(settings))
    d = client.get("/api/species/northern raccoon").json()
    assert d["encounters"] == 5 and d["usual_time"].startswith("around")
    assert d["calendar_total_in_range"] == 5 and len(d["calendar"]) == 182
    assert d["info"]["facts"]["activity"] == "nocturnal"
    assert any(i["kind"] == "timing_vs_sun" for i in d["insights"])
    assert client.get("/api/species/unicorn").status_code == 404
    enc = d["gallery"][0]["id"]
    frames = client.get(f"/api/encounters/{enc}/frames").json()
    assert frames and frames[0]["boxes"][0]["category"] == "animal"
    act = client.get("/api/activity").json()
    assert len(act["points"]) == 5 and 0 < act["night"]["sunset_min"] < 1440


def test_together_filter_is_exact_and_clock_has_minutes(conn, settings, tmp_path):
    from observatory_edge.insights import _clock
    assert _clock(8 * 60 + 30) == "8:30 am" and _clock(22 * 60) == "10 pm"
    for d in range(3):
        visit(conn, settings, tmp_path, datetime(2024, 6, 1 + d, 22, 0), FOX)
        visit(conn, settings, tmp_path, datetime(2024, 6, 1 + d, 23, 30))
    assert any(i.kind == "together" for i in compute_insights(conn, settings, species="red fox"))
    assert not any(i.kind == "together" for i in compute_insights(conn, settings, species="fox"))
