CREATE TABLE IF NOT EXISTS record_attachment_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL,
    record_version INTEGER NOT NULL,
    attachment_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL
        CHECK (relationship_type IN ('supports', 'contradicts', 'context_for')),
    target_type TEXT NOT NULL
        CHECK (target_type IN ('condition', 'signal', 'finding', 'record')),
    target_key TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'admin',
    removed_at TEXT,
    removed_by TEXT,
    FOREIGN KEY (attachment_id)
        REFERENCES record_attachments(id)
);

CREATE INDEX IF NOT EXISTS idx_attachment_relationships_attachment
    ON record_attachment_relationships(reference, attachment_id, is_active);

CREATE INDEX IF NOT EXISTS idx_attachment_relationships_target
    ON record_attachment_relationships(reference, target_type, target_key, is_active);
