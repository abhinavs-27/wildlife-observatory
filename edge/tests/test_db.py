from observatory_edge.db import connect, init_db, utcnow

EXPECTED = {
    "device", "event", "media", "frame", "model", "inference_run", "detection",
    "classification", "track", "track_detection", "encounter", "encounter_track",
    "encounter_media", "individual", "individual_track", "correction", "job", "worker",
    "alert", "backup", "ingest_failure",
}


def test_init_db_creates_all_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED <= names


def test_init_db_is_idempotent(conn):
    init_db(conn)


def test_persistence_across_connections(settings, conn):
    conn.execute("INSERT INTO device(name, created_at) VALUES ('cam', ?)", (utcnow(),))
    conn.close()
    c2 = connect(settings.db_path)
    assert c2.execute("SELECT name FROM device").fetchone()["name"] == "cam"
    c2.close()
