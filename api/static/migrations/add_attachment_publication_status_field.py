ALTER TABLE record_attachments
ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'internal'
    CHECK (publication_status IN ('internal', 'published', 'withdrawn'));
