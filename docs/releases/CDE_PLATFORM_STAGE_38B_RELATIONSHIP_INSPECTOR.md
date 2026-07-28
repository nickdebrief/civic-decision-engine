# CDE Platform Stage 38B — Relationship Inspector

## Purpose

CDE Platform Stage 38B completes the Mailbox Relationship Graph investigation workspace by replacing the placeholder node panel with a functional Relationship Inspector.

The inspector is a UI and accessibility refinement only. It does not change relationship extraction, graph generation, the `/api/mailbox/graph` response format, verification, canonical records, publication workflow, CREF methodology, or record lifecycle.

## Architecture

The Relationship Inspector is populated entirely from the graph payload already loaded by the browser.

It reuses:

- graph nodes;
- graph edges;
- node metadata;
- relationship weights;
- relationship types;
- existing graph search state;
- existing graph selection state.

No duplicate relationship database, new schema, or new governed object type is introduced.

## Inspector Model

When no node is selected, the inspector displays a concise empty state:

- relationship summary;
- connected entities;
- metadata;
- available actions.

When a node is selected, searched, or keyboard-selected, the inspector updates immediately and uses the selected node type as its heading.

Every selected node also displays a neighbour summary:

- relationship count;
- neighbour count;
- relationship types;
- top connected entities;
- recent activity.

## Supported Node Types

The inspector includes type-specific metadata for:

- Email;
- Person;
- Institution;
- Case;
- Reference Number;
- Attachment;
- Intake Record.

Email nodes display message subject, date, sender, recipients, CC, attachments, references, case context, verification hash, and relationship degree.

Institution nodes display institution name, type, relationship degree, connected emails, connected people, connected references, connected cases, and first/latest appearance.

Person nodes display name, institution context, relationship degree, emails, cases, references, and first/latest appearance.

Reference and Case nodes display their connected institutions, people, emails, and related identifiers.

Attachment nodes display filename, file type, linked emails, linked references, and available verification metadata.

Intake Record nodes display title, status, institution context, connected emails, connected references, verification metadata, and publication status.

## Quick Actions

Quick actions are context-sensitive and are shown only where meaningful for the selected node type.

Supported actions include:

- open message;
- open related messages;
- open related record;
- highlight neighbours;
- highlight thread;
- show reply chain;
- highlight attachments;
- highlight reuse;
- highlight provenance;
- filter by institution;
- filter by person;
- filter by case;
- filter by reference;
- focus graph;
- collapse others.

The actions reuse existing graph state and filter controls. They do not create new relationship data.

## Interaction

Selecting another node refreshes the inspector immediately.

Search results select and centre the first matching node and populate the inspector.

Keyboard selection through Enter or Space also updates the inspector.

Clicking blank graph canvas clears the selection and restores the empty Relationship Inspector state.

## Accessibility

The inspector is exposed as an `aria-live` region with an explicit Relationship Inspector label.

Graph nodes remain keyboard focusable, and keyboard selection updates the same inspector state as pointer selection.

Relationship types are shown as text badges, so colour is not the only source of meaning.

## Performance

The inspector performs client-side summarisation from cached graph data.

It does not refetch the graph or regenerate relationships when a node is selected.

Neighbour summaries, relationship badges, and quick actions are derived from the already loaded node and edge arrays.

## Governance Invariants

CDE Platform Stage 38B does not change:

- relationship extraction;
- graph API;
- verification hashes;
- canonical records;
- publication workflow;
- CREF methodology;
- record lifecycle;
- document lifecycle;
- MBOX original-byte preservation;
- contained-message projections;
- search indexing;
- archive filtering.

## Tests

Focused tests cover:

- empty inspector rendering;
- Institution inspector fields;
- Person inspector fields;
- Email inspector fields;
- Reference inspector fields;
- Case inspector fields;
- Attachment inspector fields;
- Intake Record inspector fields;
- context-sensitive quick actions;
- selection updates;
- keyboard selection hooks;
- graph search integration;
- blank-canvas clearing;
- existing Stage 38 and Stage 38A graph behaviour.
