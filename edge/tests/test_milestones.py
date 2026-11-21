from datetime import datetime, timedelta

import pytest
from test_flow import RACCOON, add_image, animal, classify, detect

import test_flow
from observatory_edge.alerts import send_pending_alerts
from observatory_edge.corrections import add_correction
from observatory_edge.milestones import evaluate_milestones

FOX = "f;mammalia;carnivora;canidae;vulpes;vulpes;red fox"


@pytest.fixture(autouse=True)
def _restore_base():
    saved = test_flow.BASE
    yield
    test_flow.BASE = saved


def visit(conn, settings, tmp_path, when, label=RACCOON, score=0.93, live=True, n_animals=1):
    test_flow.BASE = when
    m = add_image(conn, settings, tmp_path, live=live)
    detect(conn, settings, m, [animal(x=0.1 + 0.3 * i) for i in range(n_animals)])
    classify(conn, settings, m, label, score)
    return m


def milestones(conn, kind=None):
    rows = conn.execute("SELECT * FROM milestone ORDER BY id").fetchall()
    return [r for r in rows if kind is None or r["kind"] == kind]


def alerts(conn, kind="milestone"):
    return conn.execute("SELECT * FROM alert WHERE kind=? ORDER BY id", (kind,)).fetchall()


def test_first_species_once_with_owner_and_family_pushes(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0))
    assert [m["text"] for m in milestones(conn, "first_species")] == ["First northern raccoon ever!"]
    assert evaluate_milestones(conn, settings) == []  # idempotent
    chans = sorted(a["channel"] for a in alerts(conn))
    assert chans == ["family", "owner"]
    fam = [a for a in alerts(conn) if a["channel"] == "family"][0]
    assert fam["link"] is None  # family pushes are self-contained


def test_low_confidence_waits_for_confirmation(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0), score=0.6)
    m = milestones(conn, "first_species")[0]
    assert m["status"] == "awaiting_confirmation"
    assert [a["channel"] for a in alerts(conn)] == ["owner"]
    assert "(unconfirmed)" in alerts(conn)[0]["body"]
    enc = conn.execute("SELECT id FROM encounter").fetchone()[0]
    add_correction(conn, settings, "encounter", enc, "confirm", None)
    assert milestones(conn, "first_species")[0]["status"] == "active"
    assert sorted(a["channel"] for a in alerts(conn)) == ["family", "owner"]


def test_bulk_import_creates_milestone_without_push(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0), live=False)
    assert len(milestones(conn, "first_species")) == 1
    assert alerts(conn) == []


def test_back_after_two_weeks(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0), live=False)
    visit(conn, settings, tmp_path, datetime(2024, 6, 17, 22, 0))
    back = milestones(conn, "back_after")
    assert back and "back after 16 days" in back[0]["text"]


def test_record_night(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0), live=False)
    for i in range(3):  # 3 separate visits on a later night (> 2 min apart)
        visit(conn, settings, tmp_path, datetime(2024, 6, 5, 21, 0) + timedelta(minutes=30 * i),
              FOX if i else RACCOON, live=False)
    assert [m["text"] for m in milestones(conn, "record_night")] == ["Busiest night yet: 3 visits."]


def test_relabel_withdraws_unsupported_first(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0), FOX, live=False)
    enc = conn.execute("SELECT id FROM encounter").fetchone()[0]
    add_correction(conn, settings, "encounter", enc, "relabel", "northern raccoon")
    fox = [m for m in milestones(conn, "first_species") if m["species"] == "red fox"][0]
    assert fox["status"] == "withdrawn"
    assert any(m["species"] == "northern raccoon" and m["status"] == "active"
               for m in milestones(conn, "first_species"))


def test_family_alert_skipped_without_family_topic(conn, settings, tmp_path):
    visit(conn, settings, tmp_path, datetime(2024, 6, 1, 22, 0))
    sent = []

    class Fake:
        def send(self, title, body, image, tags, click=None):
            sent.append((title, body, click))
    stats = send_pending_alerts(conn, settings, {"owner": Fake(), "family": None})
    assert stats["skipped"] >= 1
    assert conn.execute("SELECT status FROM alert WHERE channel='family'").fetchone()[0] == "skipped"
