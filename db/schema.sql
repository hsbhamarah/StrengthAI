-- StrengthOS AI starter schema. Apply to a fresh SQLite database.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE athletes (
  athlete_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  goal TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
  created_at TEXT NOT NULL
);

CREATE TABLE training_blocks (
  block_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL REFERENCES athletes(athlete_id),
  label TEXT NOT NULL,
  phase TEXT NOT NULL CHECK(phase IN ('hypertrophy','strength','peaking','taper','deload','general','other')),
  start_date TEXT,
  end_date TEXT,
  CHECK(end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE training_weeks (
  week_id TEXT PRIMARY KEY,
  block_id TEXT NOT NULL REFERENCES training_blocks(block_id),
  week_key TEXT NOT NULL,
  week_index INTEGER NOT NULL CHECK(week_index > 0),
  start_date TEXT,
  end_date TEXT,
  checkin_due_at TEXT,
  CHECK(end_date >= start_date),
  UNIQUE(block_id, week_index),
  UNIQUE(block_id, week_key)
);

CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  week_id TEXT NOT NULL REFERENCES training_weeks(week_id),
  session_date TEXT,
  label TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK(ordinal > 0),
  UNIQUE(week_id, ordinal)
);

CREATE TABLE exercises (
  exercise_id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL UNIQUE,
  movement_group TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE exercise_prescriptions (
  prescription_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(session_id),
  exercise_id TEXT NOT NULL REFERENCES exercises(exercise_id),
  source_label TEXT,
  ordinal INTEGER NOT NULL CHECK(ordinal > 0),
  notes TEXT,
  UNIQUE(session_id, ordinal)
);

CREATE TABLE prescribed_sets (
  prescribed_set_id TEXT PRIMARY KEY,
  prescription_id TEXT NOT NULL REFERENCES exercise_prescriptions(prescription_id),
  set_index INTEGER NOT NULL CHECK(set_index > 0),
  side TEXT NOT NULL DEFAULT 'both' CHECK(side IN ('both','right','left')),
  set_type TEXT NOT NULL CHECK(set_type IN ('top','backoff','warmup','other')),
  target_reps REAL CHECK(target_reps IS NULL OR target_reps >= 0),
  target_reps_min REAL CHECK(target_reps_min IS NULL OR target_reps_min >= 0),
  target_reps_max REAL CHECK(target_reps_max IS NULL OR target_reps_max >= target_reps_min),
  target_load_kg REAL CHECK(target_load_kg IS NULL OR target_load_kg >= 0),
  target_rpe REAL CHECK(target_rpe IS NULL OR target_rpe BETWEEN 0 AND 10),
  target_rpe_min REAL CHECK(target_rpe_min IS NULL OR target_rpe_min BETWEEN 0 AND 10),
  target_rpe_max REAL CHECK(target_rpe_max IS NULL OR (target_rpe_max BETWEEN 0 AND 10 AND target_rpe_max >= target_rpe_min)),
  target_rir REAL CHECK(target_rir IS NULL OR target_rir >= 0),
  target_rir_min REAL CHECK(target_rir_min IS NULL OR target_rir_min >= 0),
  target_rir_max REAL CHECK(target_rir_max IS NULL OR target_rir_max >= target_rir_min),
  percent_1rm REAL CHECK(percent_1rm IS NULL OR percent_1rm BETWEEN 0 AND 100),
  reference_1rm_kg REAL CHECK(reference_1rm_kg IS NULL OR reference_1rm_kg > 0),
  UNIQUE(prescription_id, set_index, side)
);

CREATE TABLE actual_sets (
  actual_set_id TEXT PRIMARY KEY,
  prescription_id TEXT NOT NULL REFERENCES exercise_prescriptions(prescription_id),
  prescribed_set_id TEXT UNIQUE REFERENCES prescribed_sets(prescribed_set_id),
  set_index INTEGER NOT NULL CHECK(set_index > 0),
  side TEXT NOT NULL DEFAULT 'both' CHECK(side IN ('both','right','left')),
  status TEXT NOT NULL CHECK(status IN ('completed','failed','skipped')),
  reps REAL CHECK(reps IS NULL OR reps >= 0),
  load_kg REAL CHECK(load_kg IS NULL OR load_kg >= 0),
  actual_rpe REAL CHECK(actual_rpe IS NULL OR actual_rpe BETWEEN 0 AND 10),
  actual_rir REAL CHECK(actual_rir IS NULL OR actual_rir >= 0),
  is_extra INTEGER NOT NULL DEFAULT 0 CHECK(is_extra IN (0,1)),
  updated_at TEXT NOT NULL,
  CHECK((status <> 'skipped') OR (reps IS NULL AND load_kg IS NULL AND actual_rpe IS NULL)),
  CHECK((prescribed_set_id IS NOT NULL AND is_extra=0) OR (prescribed_set_id IS NULL AND is_extra=1))
);

CREATE TABLE data_sources (
  source_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL REFERENCES athletes(athlete_id),
  kind TEXT NOT NULL CHECK(kind IN ('excel','google_sheet')),
  display_name TEXT NOT NULL,
  external_id TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  UNIQUE(kind, external_id)
);

CREATE TABLE mapping_profiles (
  mapping_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES data_sources(source_id),
  version INTEGER NOT NULL CHECK(version > 0),
  layout_fingerprint TEXT NOT NULL,
  mapping_json TEXT NOT NULL CHECK(json_valid(mapping_json)),
  approved_at TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  UNIQUE(source_id, version)
);

CREATE TABLE import_jobs (
  import_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES data_sources(source_id),
  mapping_id TEXT REFERENCES mapping_profiles(mapping_id),
  source_snapshot_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','cancelled')),
  started_at TEXT,
  finished_at TEXT,
  error_code TEXT,
  preview_json TEXT,
  snapshot_path TEXT,
  UNIQUE(source_id, source_snapshot_hash, mapping_id)
);

CREATE TABLE source_records (
  source_record_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES data_sources(source_id),
  import_id TEXT NOT NULL REFERENCES import_jobs(import_id),
  mapping_id TEXT NOT NULL REFERENCES mapping_profiles(mapping_id),
  natural_key TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  sheet_name TEXT NOT NULL,
  cell_range TEXT NOT NULL,
  raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
  canonical_type TEXT,
  canonical_id TEXT,
  current_revision INTEGER NOT NULL DEFAULT 1 CHECK(current_revision > 0),
  UNIQUE(source_id, natural_key)
);

CREATE TABLE record_revisions (
  revision_id TEXT PRIMARY KEY,
  source_record_id TEXT NOT NULL REFERENCES source_records(source_record_id),
  revision_no INTEGER NOT NULL CHECK(revision_no > 0),
  prior_json TEXT CHECK(prior_json IS NULL OR json_valid(prior_json)),
  new_json TEXT NOT NULL CHECK(json_valid(new_json)),
  changed_at TEXT NOT NULL,
  reason TEXT NOT NULL,
  UNIQUE(source_record_id, revision_no)
);

CREATE TABLE recovery_checkins (
  checkin_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL REFERENCES athletes(athlete_id),
  week_id TEXT NOT NULL REFERENCES training_weeks(week_id),
  source_record_id TEXT REFERENCES source_records(source_record_id),
  submitted_at_claimed TEXT,
  observed_at TEXT NOT NULL,
  sleep_hours REAL CHECK(sleep_hours IS NULL OR sleep_hours BETWEEN 0 AND 24),
  sleep_quality INTEGER CHECK(sleep_quality IS NULL OR sleep_quality BETWEEN 1 AND 5),
  soreness INTEGER CHECK(soreness IS NULL OR soreness BETWEEN 1 AND 5),
  stress INTEGER CHECK(stress IS NULL OR stress BETWEEN 1 AND 5),
  readiness INTEGER CHECK(readiness IS NULL OR readiness BETWEEN 1 AND 5),
  pain_instability INTEGER CHECK(pain_instability IS NULL OR pain_instability IN (0,1)),
  symptom_details TEXT,
  comments TEXT,
  validation_state TEXT NOT NULL CHECK(validation_state IN ('incomplete','complete')),
  revision_no INTEGER NOT NULL DEFAULT 1 CHECK(revision_no > 0),
  CHECK(validation_state='incomplete' OR (
    submitted_at_claimed IS NOT NULL AND sleep_hours IS NOT NULL AND
    sleep_quality IS NOT NULL AND soreness IS NOT NULL AND stress IS NOT NULL AND
    readiness IS NOT NULL AND pain_instability IS NOT NULL AND
    (pain_instability=0 OR length(trim(coalesce(symptom_details,''))) > 0)
  )),
  UNIQUE(athlete_id, week_id)
);

CREATE TABLE recovery_revisions (
  recovery_revision_id TEXT PRIMARY KEY,
  checkin_id TEXT NOT NULL REFERENCES recovery_checkins(checkin_id),
  revision_no INTEGER NOT NULL CHECK(revision_no > 0),
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  observed_at TEXT NOT NULL,
  UNIQUE(checkin_id, revision_no)
);

CREATE TABLE metric_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL REFERENCES athletes(athlete_id),
  week_id TEXT REFERENCES training_weeks(week_id),
  metric_key TEXT NOT NULL,
  value REAL,
  unit TEXT,
  sample_count INTEGER NOT NULL CHECK(sample_count >= 0),
  method_version TEXT NOT NULL,
  evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
  input_fingerprint TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('valid','stale','insufficient')),
  calculated_at TEXT NOT NULL
);

CREATE TABLE analysis_runs (
  analysis_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL REFERENCES athletes(athlete_id),
  week_id TEXT REFERENCES training_weeks(week_id),
  state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','incomplete')),
  recovery_state TEXT NOT NULL,
  model_name TEXT,
  model_digest TEXT,
  prompt_version TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  evidence_snapshot_json TEXT NOT NULL CHECK(json_valid(evidence_snapshot_json)),
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE recommendations (
  recommendation_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id),
  finding TEXT NOT NULL,
  interpretation TEXT NOT NULL,
  alternatives_json TEXT NOT NULL CHECK(json_valid(alternatives_json)),
  evidence_ids_json TEXT NOT NULL CHECK(json_valid(evidence_ids_json)),
  proposed_action_json TEXT NOT NULL CHECK(json_valid(proposed_action_json)),
  evidence_quality TEXT NOT NULL CHECK(evidence_quality IN ('strong','limited','insufficient')),
  safety_review INTEGER NOT NULL DEFAULT 0 CHECK(safety_review IN (0,1)),
  created_at TEXT NOT NULL
);

CREATE TABLE coach_decisions (
  decision_id TEXT PRIMARY KEY,
  recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
  decision TEXT NOT NULL CHECK(decision IN ('approve','reject','defer')),
  note TEXT,
  decided_at TEXT NOT NULL
);

CREATE TABLE ai_conversations (
  conversation_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL REFERENCES athletes(athlete_id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE job_queue (
  job_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('excel_import','google_sync','metric_recalc','weekly_analysis','ollama_inference','backup')),
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','cancelled')),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
  lease_until TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE audit_events (
  event_id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  details_json TEXT NOT NULL CHECK(json_valid(details_json)),
  occurred_at TEXT NOT NULL
);

CREATE INDEX idx_weeks_block ON training_weeks(block_id);
CREATE INDEX idx_sessions_week ON sessions(week_id);
CREATE INDEX idx_actual_prescription ON actual_sets(prescription_id);
CREATE INDEX idx_source_records_import ON source_records(import_id);
CREATE INDEX idx_checkins_week ON recovery_checkins(week_id);
CREATE INDEX idx_metric_athlete_week ON metric_snapshots(athlete_id, week_id, metric_key);
CREATE INDEX idx_recommendations_analysis ON recommendations(analysis_id);
CREATE INDEX idx_jobs_state ON job_queue(state, created_at);
