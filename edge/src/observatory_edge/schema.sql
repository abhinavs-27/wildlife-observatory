-- Wildlife Observatory schema (design §7.4). All timestamps are UTC ISO-8601 strings ending in Z.

CREATE TABLE IF NOT EXISTS device (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'camera',          -- camera | microphone | env_sensor | pond_sensor | rain_gauge
  name TEXT NOT NULL UNIQUE,
  adapter TEXT,
  config_json TEXT NOT NULL DEFAULT '{}',
  location TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY,
  device_id INTEGER NOT NULL REFERENCES device(id),
  kind TEXT NOT NULL,                            -- capture | (future) audio_clip | reading
  occurred_at TEXT NOT NULL,
  occurred_at_source TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_device_time ON event(device_id, occurred_at);

CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES event(id),
  device_id INTEGER NOT NULL REFERENCES device(id),
  sha256 TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,                            -- image | video
  original_path TEXT NOT NULL,
  original_name TEXT NOT NULL,
  source_adapter TEXT NOT NULL,
  mime TEXT,
  size INTEGER,
  width INTEGER,
  height INTEGER,
  duration_s REAL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  captured_at TEXT NOT NULL,
  captured_at_source TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',        -- pending | detected | empty | failed
  error TEXT,
  has_person INTEGER NOT NULL DEFAULT 0,
  suppress_alerts INTEGER NOT NULL DEFAULT 0,
  active_detection_run_id INTEGER,
  active_classification_run_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_device_time ON media(device_id, captured_at);

CREATE TABLE IF NOT EXISTS frame (
  id INTEGER PRIMARY KEY,
  media_id INTEGER NOT NULL REFERENCES media(id),
  idx INTEGER NOT NULL,
  time_offset_s REAL NOT NULL DEFAULT 0,
  path TEXT NOT NULL,                            -- the original for images; derived jpg for video
  width INTEGER,
  height INTEGER,
  UNIQUE(media_id, idx)
);

CREATE TABLE IF NOT EXISTS model (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  task TEXT NOT NULL,                            -- detection | classification | tracking | analysis
  weights_hash TEXT,
  params_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(name, version, task)
);

CREATE TABLE IF NOT EXISTS inference_run (
  id INTEGER PRIMARY KEY,
  model_id INTEGER NOT NULL REFERENCES model(id),
  scope TEXT NOT NULL DEFAULT 'live',
  status TEXT NOT NULL DEFAULT 'running',
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS detection (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES inference_run(id),
  media_id INTEGER NOT NULL REFERENCES media(id),
  frame_id INTEGER NOT NULL REFERENCES frame(id),
  category TEXT NOT NULL,                        -- animal | person | vehicle
  confidence REAL NOT NULL,
  bbox_x REAL NOT NULL, bbox_y REAL NOT NULL, bbox_w REAL NOT NULL, bbox_h REAL NOT NULL,
  observed_at TEXT NOT NULL,
  verification_status TEXT NOT NULL DEFAULT 'unverified'
);
CREATE INDEX IF NOT EXISTS idx_detection_media ON detection(media_id, run_id);

CREATE TABLE IF NOT EXISTS classification (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES inference_run(id),
  detection_id INTEGER NOT NULL REFERENCES detection(id),
  raw_label TEXT NOT NULL,
  taxon_class TEXT, taxon_order TEXT, taxon_family TEXT, taxon_genus TEXT, taxon_species TEXT,
  common_name TEXT,
  rollup_level TEXT,
  score REAL NOT NULL,
  source TEXT,
  raw_topk_json TEXT NOT NULL DEFAULT '[]',
  is_uncertain INTEGER NOT NULL DEFAULT 0,
  geofence TEXT,
  verification_status TEXT NOT NULL DEFAULT 'unverified',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cls_detection ON classification(detection_id);
CREATE INDEX IF NOT EXISTS idx_cls_taxa ON classification(taxon_class, taxon_family, taxon_genus, common_name);

CREATE TABLE IF NOT EXISTS track (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES inference_run(id),
  device_id INTEGER NOT NULL REFERENCES device(id),
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  species TEXT NOT NULL DEFAULT 'pending',
  species_label TEXT,
  confidence REAL,
  is_uncertain INTEGER NOT NULL DEFAULT 0,
  verification_status TEXT NOT NULL DEFAULT 'unverified'
);
CREATE TABLE IF NOT EXISTS track_detection (
  track_id INTEGER NOT NULL REFERENCES track(id) ON DELETE CASCADE,
  detection_id INTEGER NOT NULL REFERENCES detection(id),
  PRIMARY KEY (track_id, detection_id)
);

CREATE TABLE IF NOT EXISTS encounter (
  id INTEGER PRIMARY KEY,
  device_id INTEGER NOT NULL REFERENCES device(id),
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  species_json TEXT NOT NULL DEFAULT '[]',       -- [{"species": "...", "count": n, "uncertain": bool}]
  best_frame_id INTEGER REFERENCES frame(id),
  best_detection_id INTEGER REFERENCES detection(id),
  status TEXT NOT NULL DEFAULT 'pending',        -- pending (species unknown yet) | classified
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_encounter_time ON encounter(device_id, start_at);
CREATE TABLE IF NOT EXISTS encounter_track (
  encounter_id INTEGER NOT NULL REFERENCES encounter(id) ON DELETE CASCADE,
  track_id INTEGER NOT NULL REFERENCES track(id) ON DELETE CASCADE,
  PRIMARY KEY (encounter_id, track_id)
);
CREATE TABLE IF NOT EXISTS encounter_media (
  encounter_id INTEGER NOT NULL REFERENCES encounter(id) ON DELETE CASCADE,
  media_id INTEGER NOT NULL REFERENCES media(id),
  PRIMARY KEY (encounter_id, media_id)
);

CREATE TABLE IF NOT EXISTS individual (
  id INTEGER PRIMARY KEY,
  species TEXT,
  nickname TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS individual_track (
  individual_id INTEGER NOT NULL REFERENCES individual(id),
  track_id INTEGER NOT NULL REFERENCES track(id) ON DELETE CASCADE,
  PRIMARY KEY (individual_id, track_id)
);

CREATE TABLE IF NOT EXISTS correction (
  id INTEGER PRIMARY KEY,
  target_type TEXT NOT NULL,                     -- detection | classification | track | encounter
  target_id INTEGER NOT NULL,
  action TEXT NOT NULL,                          -- confirm | reject | relabel
  label TEXT,
  note TEXT,
  device_id INTEGER,
  window_start TEXT,
  window_end TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correction_target ON correction(target_type, target_id);

CREATE TABLE IF NOT EXISTS job (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                            -- detect | classify | analyze
  media_id INTEGER NOT NULL REFERENCES media(id),
  status TEXT NOT NULL DEFAULT 'queued',         -- queued | running | done | failed
  priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  claim_token TEXT,
  worker_id TEXT,
  lease_until TEXT,
  not_before TEXT,
  error TEXT,
  timings_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_queue ON job(status, kind, priority, id);

CREATE TABLE IF NOT EXISTS worker (
  id TEXT PRIMARY KEY,
  kinds TEXT NOT NULL,
  info_json TEXT NOT NULL DEFAULT '{}',
  last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert (
  id INTEGER PRIMARY KEY,
  encounter_id INTEGER REFERENCES encounter(id),
  kind TEXT NOT NULL DEFAULT 'encounter',        -- encounter | heartbeat | failure
  channel TEXT NOT NULL DEFAULT 'owner',         -- owner | family
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  attach_frame_id INTEGER,
  attach_detection_id INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',        -- pending | sent | failed | stale
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT
);

CREATE TABLE IF NOT EXISTS ingest_failure (
  path TEXT PRIMARY KEY,
  attempts INTEGER NOT NULL,
  last_error TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backup (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL,
  size INTEGER,
  verified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- Stories & insights (2026-11-21-stories-and-insights-design.md)
CREATE TABLE IF NOT EXISTS species_info (
  common_name TEXT PRIMARY KEY,
  wiki_title TEXT,
  extract TEXT,
  page_url TEXT,
  thumbnail_path TEXT,
  status TEXT NOT NULL DEFAULT 'pending',        -- pending | ok | missing | error
  fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS milestone (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,                       -- kind:species:night
  kind TEXT NOT NULL,                             -- first_species | first_this_year | back_after | record_night | new_species_count
  species TEXT,
  encounter_id INTEGER REFERENCES encounter(id) ON DELETE SET NULL,
  text TEXT NOT NULL,
  night TEXT,
  status TEXT NOT NULL DEFAULT 'active',          -- active | awaiting_confirmation | withdrawn
  pushed_owner INTEGER NOT NULL DEFAULT 0,
  pushed_family INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digest (
  week TEXT PRIMARY KEY,                          -- ISO week of the covered Monday, e.g. 2026-W47
  payload_json TEXT NOT NULL,
  sent_at TEXT
);

CREATE TABLE IF NOT EXISTS weather_daily (
  date TEXT PRIMARY KEY,
  precip_mm REAL,
  tmin_c REAL,
  tmax_c REAL
);
