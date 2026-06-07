ALTER TABLE record_attachments
ADD COLUMN classification TEXT NOT NULL DEFAULT 'other'
    CHECK (classification IN (
        'evidence', 'correspondence', 'decision', 'medical_record',
        'legal_filing', 'photograph', 'media', 'research', 'other'
    ));
