CREATE TABLE IF NOT EXISTS record_embeddings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id           INTEGER NOT NULL,
    reference           TEXT NOT NULL,
    version             INTEGER NOT NULL,
    content_hash        TEXT NOT NULL,
    embedding_model     TEXT NOT NULL,
    embedding_json      TEXT NOT NULL,
    indexed_fields_json TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(record_id) REFERENCES records(id),
    UNIQUE(record_id, embedding_model, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_record_embeddings_ref_version
    ON record_embeddings(reference, version);

CREATE INDEX IF NOT EXISTS idx_record_embeddings_record_model
    ON record_embeddings(record_id, embedding_model);
