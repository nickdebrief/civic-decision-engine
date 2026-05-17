CREATE TABLE IF NOT EXISTS records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reference       TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    supersedes      TEXT,
    generated_at    TEXT NOT NULL,
    trajectory      TEXT,
    system_state    TEXT,
    conditions_json TEXT,
    signals_json    TEXT,
    finding         TEXT,
    report_json     TEXT,
    language        TEXT NOT NULL DEFAULT 'en',
    generated_by    TEXT NOT NULL DEFAULT 'Civic Decision Engine',
    verification_hash TEXT NOT NULL,
    exported_at     TEXT NOT NULL,
    is_latest       INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_records_reference_version
    ON records(reference, version);

CREATE INDEX IF NOT EXISTS idx_records_reference_latest
    ON records(reference, is_latest);