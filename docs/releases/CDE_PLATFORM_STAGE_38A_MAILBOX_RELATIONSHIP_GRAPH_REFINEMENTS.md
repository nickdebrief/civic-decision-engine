# CDE Platform Stage 38A — Mailbox Relationship Graph Refinements

CDE Platform Stage 38A refines the Mailbox Relationship Graph workspace for readability, interaction quality, accessibility, visual presentation, and dense-archive performance.

The release does not change relationship extraction, the graph API, verification hashes, canonical records, publication workflow, record lifecycle, database schema, or the independent CREF methodology sequence.

## Purpose

CDE Platform Stage 38 introduced deterministic relationship extraction and public graph visualisation for governed MBOX archives. Dense mailboxes can contain enough emails, people, institutions, references, attachments, and intake links that showing every label at once becomes visually noisy.

CDE Platform Stage 38A keeps the same graph data model and focuses on making the graph easier to inspect.

## Visual Improvements

Labels are hidden by default and become visible through progressive detail:

- hover;
- selection;
- keyboard focus;
- close zoom;
- selected clusters;
- directly connected nodes;
- high-importance nodes with the strongest relationship degree.

Labels fade through SVG opacity transitions instead of appearing as a hard switch. Nodes remain visible at all zoom levels so the structural pattern is readable before text detail appears.

Node colours now follow semantic categories:

- Person: teal;
- Institution: purple;
- Email: slate;
- Case: amber;
- Reference Number: blue;
- Attachment: green;
- Intake Record: red.

A persistent legend includes colour and icon markers so colour is not the only identifier.

## Interaction Model

The graph workspace supports:

- hover highlighting;
- click selection;
- double-click to centre a node;
- mouse-wheel zoom;
- graph dragging;
- individual node dragging;
- fit to screen;
- reset layout;
- keyboard selection and keyboard panning.

Selecting a node opens a side information panel rather than immediately navigating away. The panel displays node type, title, relationship count, connected institutions, connected cases, connected references, mailbox index, verification hash, and available quick actions.

Quick actions include opening an email message and applying person, institution, case, or reference filters where relevant.

## Relationship Graph Theme

The rest of the Civic Decision Engine keeps the standard visual identity.

Only the Mailbox Relationship Graph workspace supports an optional **Relationship Graph Theme** toggle:

- Standard;
- High Contrast.

Standard remains the default. The selected graph-only theme is stored in `localStorage` under a graph-specific key and does not affect metadata, navigation, archive pages, record pages, verification pages, document pages, or other public/admin views.

The high-contrast graph workspace uses:

- graph background `#0F172A`;
- graph panel `#111827`;
- border `#334155`;
- primary text `#E5E7EB`;
- secondary text `#94A3B8`;
- lower-opacity default edges;
- stronger highlighted edges;
- white selected-node outline;
- soft cyan hover glow.

## Search

Graph search supports public-safe matching across node labels, node types, and node metadata. It can locate people, institutions, references, email subjects, and case labels, highlight matching nodes, and centre the first selected result.

Search operates on the rendered graph response. It does not alter the graph API or persisted mailbox metadata.

## Cluster Mode

Cluster Mode is an optional client-side presentation layer for dense graphs. When enabled, dense communities collapse into cluster nodes that expose cluster size, dominant metadata, and node count. Clicking a cluster expands the ordinary node view again.

The underlying graph returned by `/api/mailbox/graph` remains unchanged.

## Progressive Detail

The graph uses progressive detail to reduce visual overload:

- zoomed out: nodes and highlighted cluster context;
- medium zoom: selected and connected labels;
- close zoom: broader labels;
- dense areas: hidden labels remain omitted until interaction or zoom makes them useful.

This keeps large mailboxes readable without discarding governed content.

## Performance Improvements

CDE Platform Stage 38A keeps graph relationship generation unchanged and improves client-side handling by:

- caching graph layout for the current filter and cluster state;
- reusing graph layout while filters remain unchanged;
- avoiding relationship regeneration unless filters change;
- virtualising hidden labels through opacity and progressive visibility rules;
- separating full graph data from the currently visible graph representation;
- supporting cluster mode for dense graph presentation.

No new dependency is introduced.

## Accessibility

The graph workspace includes:

- accessible theme controls;
- labelled filter controls;
- labelled search;
- a live status region;
- keyboard-focusable nodes;
- visible focus styling;
- keyboard panning;
- semantic legend entries with icons and colours;
- high-contrast graph-only theme;
- side-panel details for selected nodes.

Colour is never the only visual distinction.

## Governance Invariants

CDE Platform Stage 38A does not change:

- relationship extraction;
- `GET /api/mailbox/graph`;
- graph node or edge data contracts;
- document identifiers;
- verification hashes;
- canonical records;
- publication workflow;
- lifecycle states;
- MBOX byte preservation;
- search eligibility;
- archive filtering;
- CREF methodology stages.

Contained messages, attachments, and graph nodes remain projections of the preserved mailbox archive unless separately admitted through an existing governed workflow.

## Tests

Focused tests cover label visibility contracts, zoom thresholds, node highlighting, graph search, legend rendering, graph-only theme controls, theme persistence, layout caching, cluster mode, selection panel, keyboard navigation, performance-oriented rendering contracts, and existing graph behaviour.

Regression tests cover existing graph extraction/API behaviour, MBOX archive support, streaming MBOX support, large contained-message handling, RFC 5322 `.eml`, Outlook `.msg`, Apple Mail `.emlx`, platform identity documentation, and the full test suite.
