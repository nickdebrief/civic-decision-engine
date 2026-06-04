CREATE TABLE IF NOT EXISTS attachment_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attachment_id INTEGER,
    reference TEXT NOT NULL,
    record_version INTEGER,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'admin',
    occurred_at TEXT NOT NULL,
    metadata_json TEXT,
    request_id TEXT,
    ip_hash TEXT,
    user_agent_hash TEXT,
    FOREIGN KEY (attachment_id)
        REFERENCES record_attachments(id)
);
