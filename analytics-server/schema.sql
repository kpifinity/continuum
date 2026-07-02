-- Continuum analytics — D1 schema. Apply once at deploy time.
CREATE TABLE IF NOT EXISTS installs (
  id         TEXT PRIMARY KEY,   -- random install id from the app
  first_seen INTEGER NOT NULL,   -- unix ts of first ping
  version    TEXT,
  os         TEXT,
  arch       TEXT
);

CREATE TABLE IF NOT EXISTS pings (
  id      TEXT NOT NULL,
  event   TEXT NOT NULL,         -- "install" | "heartbeat"
  ts      INTEGER NOT NULL,
  version TEXT, os TEXT, arch TEXT
);
CREATE INDEX IF NOT EXISTS idx_pings_ts ON pings(ts);

-- One row per (day, install) for active-user counts.
CREATE TABLE IF NOT EXISTS active_days (
  day TEXT NOT NULL,             -- YYYY-MM-DD
  id  TEXT NOT NULL,
  PRIMARY KEY (day, id)
);
