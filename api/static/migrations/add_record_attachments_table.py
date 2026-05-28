CREATE TABLE IF NOT EXISTS record_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    reference TEXT NOT NULL,
    record_version INTEGER NOT NULL,
    attachment_version INTEGER NOT NULL DEFAULT 1,

    filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,

    content_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,

    visibility TEXT NOT NULL CHECK (visibility IN ('private', 'public')),
    redaction_status TEXT NOT NULL DEFAULT 'none'
        CHECK (redaction_status IN ('none', 'redacted', 'withheld')),
    redaction_note TEXT,

    title TEXT,
    description TEXT,
    source_label TEXT,

    uploaded_at TEXT NOT NULL,
    uploaded_by TEXT,
    supersedes_attachment_id INTEGER,

    is_latest INTEGER NOT NULL DEFAULT 1,
    is_deleted INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (reference, record_version)
        REFERENCES records(reference, version),
    FOREIGN KEY (supersedes_attachment_id)
        REFERENCES record_attachments(id)
);

CREATE INDEX IF NOT EXISTS idx_record_attachments_reference
    ON record_attachments(reference, record_version);

CREATE INDEX IF NOT EXISTS idx_record_attachments_public
    ON record_attachments(reference, visibility, redaction_status, is_latest, is_deleted);

CREATE UNIQUE INDEX IF NOT EXISTS idx_record_attachments_version
    ON record_attachments(reference, record_version, filename, attachment_version);
