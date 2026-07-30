# CDE Platform Stage 39C — Folder & Message Projection

## Purpose

CDE Platform Stage 39C introduces governed internal projection for Microsoft Outlook PST and OST archives.

Projection is not publication. Projection is not promotion. The preserved archive remains the authoritative evidence object, while folder and message metadata projections support administrative review and future governed workflows.

## Architecture

Stage 39C extends the Stage 39B archive job framework. When a configured parser supports projection, the archive job performs three bounded steps:

1. verifies the preserved archive hashes;
2. runs lightweight parser inspection;
3. stores a replaceable folder and message metadata projection.

Projection sidecars are stored separately from the archive under:

`<document-intake-root>/.outlook_archive_projections/`

Deleting or rebuilding a projection does not alter the original archive, SHA-256, SHA-512, Document Identifier, lifecycle history, publication state, or verification behavior.

## Parser Boundary

Stage 39C reuses the optional `OutlookArchiveParser` contract and adds a projection method:

- `supports(file_path)`
- `inspect(file_path)`
- `project(file_path)`

No parser dependency is introduced. If no parser is configured, Stage 39A and Stage 39B behavior remains unchanged. If a parser is configured but does not expose `project(...)`, archive inspection can still complete without projection.

## Folder Projection

Projected folders may include:

- mailbox identity;
- top-level folders;
- nested folders;
- folder path;
- folder identifier;
- parent folder identifier;
- source identifier;
- message count;
- subfolder count;
- attachment count;
- projected size.

Folders remain administrative projection metadata. They are not public archive content.

## Message Projection

Projected messages include metadata only, where available:

- projection identifier;
- Message-ID;
- subject;
- sender;
- recipients;
- CC;
- sent timestamp;
- received timestamp;
- message class;
- conversation ID;
- thread index;
- attachment count;
- read status;
- importance;
- categories;
- folder ID and folder path.

Message bodies, attachment bytes, embedded content, and mailbox item payloads are not stored in the projection.

## Provenance

Every projected folder and message records:

- archive ID;
- archive job ID;
- parser version;
- projection timestamp;
- source folder;
- source identifier;
- extraction method.

The provenance chain remains:

Preserved archive → archive job → administrative projection

No projected object becomes an independent governed evidence object in CDE Platform Stage 39C.

## Projection Lifecycle

Stage 39C supports the projection states:

- `pending`
- `projecting`
- `projected`
- `superseded`
- `rebuilt`

Current projections are deterministic JSON sidecars. Rebuilding replaces the sidecar and records prior projection state and timestamp where available.

## Administrative Browser

Stage 39C adds an authenticated administrative mailbox projection browser with:

- mailbox summary;
- folder table;
- message metadata table;
- projection statistics;
- folder detail pages;
- message metadata detail pages;
- metadata search.

The browser does not render message bodies or attachment contents.

## Administrative APIs

Stage 39C adds protected administrative endpoints:

- `GET /api/admin/session/archive/{id}/projection`
- `GET /api/admin/session/archive/{id}/folders`
- `GET /api/admin/session/archive/{id}/folders/{folder_id}`
- `GET /api/admin/session/archive/{id}/messages`
- `GET /api/admin/session/archive/{id}/messages/{message_id}`
- `GET /api/admin/session/archive/{id}/statistics`
- `GET /api/admin/session/archive/{id}/projection/search`

These endpoints require an authenticated administrative session.

## Search

Administrative projection search covers bounded metadata only:

- subject;
- sender;
- recipient;
- date;
- folder path;
- conversation ID;
- categories;
- Message-ID.

Search returns projection metadata only. It does not index or expose message body content or attachment content.

## Public Boundary

Published PST/OST archive pages may show projection state and preservation status, but they do not expose:

- folder names;
- subjects;
- senders;
- recipients;
- conversations;
- projected messages;
- message bodies;
- attachment contents.

Public verification continues to verify only the original preserved archive and its governed lifecycle.

## Regression Safety

CDE Platform Stage 39C does not change:

- Stage 39A intake boundary;
- Stage 39B preservation jobs;
- RFC 5322 `.eml` support;
- Microsoft Outlook `.msg` support;
- Apple Mail `.emlx` support;
- MBOX archive support;
- public interfaces;
- Canonical Records;
- verification hashes;
- publication workflow;
- CREF methodology;
- database schema.

## Tests

Focused tests cover:

- parser-backed projection creation;
- nested folder projection;
- message metadata projection;
- per-object provenance;
- projection statistics;
- administrative metadata search;
- projection rebuild;
- administrative browser pages;
- administrative projection APIs;
- public boundary preservation.

The full regression suite remains required before merge.

## Intentional Exclusions

CDE Platform Stage 39C does not implement:

- public mailbox projection views;
- message body rendering;
- attachment extraction;
- Canonical Record generation;
- governed message promotion;
- duplicate detection;
- conversation reconstruction;
- relationship graph expansion from PST/OST;
- parser dependency installation;
- database migration.
