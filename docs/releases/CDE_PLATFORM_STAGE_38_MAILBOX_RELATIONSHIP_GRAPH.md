# CDE Platform Stage 38 — Mailbox Relationship Graph

The Civic Decision Engine can now generate a deterministic Mailbox Relationship Graph from existing governed MBOX archive projections.

The graph reveals communication structure across emails, people, institutions, cases, references, attachments, and intake records without creating a duplicate relationship database.

## Purpose

Mailbox archives already provide chronological access through the Mailbox Overview, Message Index, and Message Detail views. CDE Platform Stage 38 adds a structural view so investigators can identify communication clusters, institutional hubs, reply chains, isolated conversations, shared references, attachment relationships, case relationships, and intake provenance without reading every message one by one.

## Architecture

The relationship graph is generated dynamically from existing published mailbox metadata:

- document intake metadata;
- immutable Document Identifiers;
- MBOX message projections;
- message indexes;
- byte ranges;
- contained-message digests;
- parsed RFC 5322 headers;
- attachment metadata;
- administrator-entered institution, reference, category, description, and keyword fields.

No schema, migration, duplicate relationship table, or stored graph artefact is introduced. Generation is deterministic and uses only recorded metadata. It does not use AI inference, probabilistic matching, or unstated assumptions.

## Relationship Model

Supported node categories are:

- Email;
- Person;
- Institution;
- Case;
- Reference Number;
- Attachment;
- Intake Record.

Each node includes an `id`, `type`, `label`, metadata, icon hint, and colour category.

Supported relationship types are:

- Sent By;
- Sent To;
- CC;
- Replies To;
- References;
- Attached To;
- Belongs To Case;
- Created Intake;
- Mentions Reference;
- Related Communication.

Edges include source, target, relationship type, deterministic weight, and evidence metadata. Weights are derived from explicit metadata such as reply headers, shared case references, shared institutions, message references, attachment reuse, and intake linkage.

## API

CDE Platform Stage 38 exposes:

`GET /api/mailbox/graph`

The response shape is:

```json
{
  "nodes": [],
  "edges": []
}
```

Supported filters include:

- `document`;
- `institution`;
- `person`;
- `case`;
- `reference`;
- `from`;
- `to`;
- `status`;
- `offset`;
- `limit`.

The `document` filter scopes the graph to one published mailbox document. The offset and limit controls allow incremental graph loading for large mailboxes without changing the underlying mailbox projection model.

## Public Presentation

Published MBOX document pages now include a mailbox tab set:

- Inbox;
- Cases;
- Timeline;
- Relationship Graph.

The Relationship Graph tab renders an interactive SVG graph with zoom, pan, fit-to-screen, node selection, connected-node highlighting, unrelated-node fading, and dark-mode styling. Email nodes link to the existing Mailbox Message Detail view. Person and Institution nodes populate the corresponding graph filters.

The existing Mailbox Overview, Message Index, Message Detail, Mailbox Governance Boundary, Publication Provenance, Publication Pathway, search, archive filtering, and original `.mbox` download behaviour remain unchanged.

## Performance Considerations

The graph generator builds from the already loaded mailbox projections and avoids a duplicate relationship store. It supports deterministic pagination through `offset` and `limit`, bounds API output, and keeps the client renderer focused on the returned node set.

The browser graph uses a lightweight force-directed SVG layout rather than adding a new dependency. Large mailboxes can be explored by filtering, scoping to a document, and incrementally loading graph slices.

## Accessibility

The graph surface includes labelled filters, button controls, a live status region, keyboard-focusable graph nodes, accessible SVG labelling, and deterministic text labels. The graph remains a supplementary presentation of relationships already available through the underlying published mailbox metadata.

## Governance Invariants

CDE Platform Stage 38 does not change:

- governed object identity;
- document SHA-256 hashes;
- MBOX byte preservation;
- lifecycle states;
- publication workflow;
- provenance;
- archive filtering semantics;
- search eligibility;
- associations;
- collections;
- transmissions;
- CREF methodology stages.

Contained messages, attachments, and graph nodes are projections of the preserved mailbox archive unless separately admitted through an existing governed workflow.

## Tests

Focused tests cover relationship extraction, node and edge generation, deterministic weighting, reply-chain relationships, institution clustering, case/reference linking, attachment linking, API response format, filtering, deterministic output, incremental graph loading, and public mailbox page graph controls.

Regression validation covers existing MBOX archive support, governed streaming MBOX ingestion, large contained-message handling, RFC 5322 `.eml`, Outlook `.msg`, Apple Mail `.emlx`, and the full test suite.

## Future Extensions

Future CDE Platform stages may add richer graph persistence, virtualized graph rendering, administrative investigation workspaces, cross-mailbox graph comparison, or explicit governed promotion of contained mailbox messages. Those extensions remain out of scope for CDE Platform Stage 38.
