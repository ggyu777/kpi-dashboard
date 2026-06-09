-- Supabase SQL Editor에서 실행 (또는 기존 로컬 Postgres와 동일 스키마)

CREATE TABLE IF NOT EXISTS kpi_targets (
  week VARCHAR(16) NOT NULL,
  kpi_id VARCHAR(64) NOT NULL,
  target DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (week, kpi_id)
);

CREATE TABLE IF NOT EXISTS kpi_manual_data (
  week VARCHAR(16) NOT NULL,
  kpi_id VARCHAR(64) NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (week, kpi_id)
);

CREATE TABLE IF NOT EXISTS ad_conversions (
  week VARCHAR(16) NOT NULL,
  placement VARCHAR(32) NOT NULL,
  conversion_rate DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (week, placement)
);

CREATE TABLE IF NOT EXISTS ad_placement_meta (
  week VARCHAR(16) NOT NULL,
  placement VARCHAR(32) NOT NULL,
  revenue INTEGER,
  note TEXT DEFAULT '',
  PRIMARY KEY (week, placement)
);

CREATE TABLE IF NOT EXISTS weekly_notes (
  week VARCHAR(16) PRIMARY KEY,
  kpi_summary TEXT DEFAULT '',
  project_progress TEXT DEFAULT '',
  next_week_strategy TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS weekly_tasks (
  week VARCHAR(16) PRIMARY KEY,
  tasks JSONB DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS weekly_plans (
  week VARCHAR(16) PRIMARY KEY,
  author VARCHAR(128) DEFAULT '',
  north_star TEXT DEFAULT '',
  goals JSONB DEFAULT '[]',
  actions JSONB DEFAULT '[]',
  ad_revenues JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monthly_plans (
  month VARCHAR(16) PRIMARY KEY,
  author VARCHAR(128) DEFAULT '',
  north_star TEXT DEFAULT '',
  mau_target INTEGER DEFAULT 0,
  goals JSONB DEFAULT '[]',
  kpt_keep TEXT DEFAULT '',
  kpt_problem TEXT DEFAULT '',
  kpt_try TEXT DEFAULT '',
  next_actions JSONB DEFAULT '[]',
  ad_revenues JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monthly_feedback (
  month VARCHAR(16) PRIMARY KEY,
  feedback TEXT DEFAULT ''
);
