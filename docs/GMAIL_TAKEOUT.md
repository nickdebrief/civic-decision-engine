# Google Takeout Gmail Archives

## Supported Inputs

CDE Platform Stage 40 accepts administrator-supplied Google Takeout Gmail ZIP
exports through ordinary governed Document Intake. The existing synchronous
intake size limit remains authoritative. The server verifies that a ZIP is a
plausible Takeout export containing Gmail MBOX data; a `.zip` extension or
browser MIME type alone is insufficient.

Administrators may also select an extracted Takeout directory. Because a web
browser cannot transmit a directory as one original archive, CDE preserves each
selected file byte-for-byte inside a deterministic, uncompressed ZIP storage
envelope. The metadata records this distinction. No MBOX, message, line ending,
MIME payload, or attachment is normalised.

## Parser Adapter

`ArchiveParser` is the source-neutral contract. `GmailTakeoutParser` implements
that contract and contains Gmail-specific detection and parsing. Outlook
behavior and its parser contract remain unchanged.

The adapter applies bounded ZIP and MBOX processing:

- safe relative paths only;
- no symlinks or encrypted entries;
- bounded entry count, expansion ratio, and uncompressed size;
- bounded line, message, message-count, attachment-count, and decoded
  attachment size;
- sequential MBOX processing with private spooling for larger messages.

## Projection Model

Gmail data uses the existing archive projection model:

```text
Archive -> Label -> Thread -> Message -> Attachment -> Canonical Record
```

Labels occupy the existing folder projection boundary. A message with multiple
labels has one stable message projection identity and multiple label
relationships. Thread identity is preserved from exported Gmail metadata where
available. Bounded private body and HTML projections support administrative
review only.

## Attachment and Promotion Governance

Attachments reuse CDE Platform Stage 39E. Each receives an immutable `ATT-`
identifier, SHA-256, size, media type, extraction timestamp, source message, and
source archive provenance. Attachment bytes are private, are not independently
downloadable, and are never promoted automatically.

Eligible messages and attachments reuse the existing explicit administrator
promotion workflows from CDE Platform Stages 39D and 39E. They create ordinary
Canonical Records only after confirmation. There is no Gmail-specific
Canonical Record type or lifecycle.

## Relationship Graph

The protected archive graph adds deterministic Label and Thread nodes alongside
the existing Archive, Message, Attachment, Person, Institution, and Canonical
Record concepts. It derives only relationships present in preserved or
projected evidence. It performs no AI inference and does not change the public
`/api/mailbox/graph` semantics.

## Governance Boundary

The preserved Takeout export is authoritative. Labels, threads, message
metadata, bounded body views, and governed attachments are private projections.
Public document pages expose archive-level metadata only. They expose no Gmail
message body, attachment content, extraction interface, promotion control, or
Takeout archive download.

Google Takeout support is archive ingestion, not Gmail account integration. CDE
does not access Gmail APIs, authenticate to Google, retrieve remote content, or
synchronise a mailbox.
