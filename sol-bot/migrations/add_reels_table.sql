-- Reels feature migration
CREATE TABLE IF NOT EXISTS reels (
  reel_id TEXT PRIMARY KEY,
  alert_id TEXT,
  hook TEXT NOT NULL,
  body TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT 'BREAKING',
  topic_tag TEXT,
  rhetorical_move TEXT,
  duration_sec INTEGER DEFAULT 18,
  local_path TEXT NOT NULL,
  thumbnail_path TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN ('draft','publishing','published','failed'))
);
CREATE INDEX IF NOT EXISTS idx_reels_status ON reels(status);
CREATE INDEX IF NOT EXISTS idx_reels_alert ON reels(alert_id);
CREATE INDEX IF NOT EXISTS idx_reels_created ON reels(created_at);

CREATE TABLE IF NOT EXISTS reel_publishes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reel_id TEXT NOT NULL,
  network_name TEXT NOT NULL,
  remote_post_id TEXT,
  permalink TEXT,
  published_at TEXT,
  error_message TEXT,
  FOREIGN KEY(reel_id) REFERENCES reels(reel_id)
);
CREATE INDEX IF NOT EXISTS idx_reel_publishes_reel ON reel_publishes(reel_id);
