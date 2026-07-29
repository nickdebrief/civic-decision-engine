# CDE Platform Stage 38C — Live Relationship Inspector Binding

## Purpose

CDE Platform Stage 38C completes the Mailbox Relationship Graph investigation workspace by binding graph-node selection to live Relationship Inspector content.

The stage is a focused functional correction. It does not change relationship extraction, the `/api/mailbox/graph` response semantics, verification, canonical records, publication workflow, CREF methodology, record lifecycle, or database schema.

## Observed Gap

The graph rendered correctly and the inspector displayed its empty instructional state, but selecting a visible node did not consistently replace that state with live node content.

The practical result was that the Relationship Inspector could appear like a static help panel even though the graph, search, clustering, zoom, semantic node types, and themes were available.

## Root Cause

Selection state was split across several client-side paths. Ordinary node clicks, keyboard selection, graph search, quick actions, canvas clearing, and cluster expansion each updated `selectedNode`, graph highlighting, and inspector rendering separately.

The most visible defect was the cluster path: a cluster click selected the cluster, then expanded it, then cleared the inspector. Some quick actions also highlighted graph elements without re-rendering the inspector through the same path.

## Authoritative Selection Pathway

Stage 38C introduces a single client-side selection function, `selectGraphNode(nodeId, selectionSource, options)`.

The function resolves the node from the cached graph payload, stores the selected node ID, updates graph emphasis, centers or focuses when requested, renders the Relationship Inspector, updates accessibility state, and fails safely when a stale node ID cannot be resolved.

The following paths now converge on that function:

- ordinary node click
- cluster node click
- graph search result selection
- keyboard Enter or Space selection
- double-click programmatic focus
- quick-action highlighting and focus
- cluster expansion follow-up selection

## Live Inspector Binding

The empty state remains available only when no node is selected. It states that the inspector will display relationship summary, connected entities, metadata, and available actions.

When a node is selected, the inspector is populated immediately from the cached graph data already loaded in the browser. It displays node type, label, stable node ID, relationship counts, unique neighbour counts, relationship type badges, neighbour type counts, top connected entities, connected institutions, connected people, connected cases, connected references, connected attachments, recent activity, type-specific metadata, and context-sensitive actions where available.

The inspector does not make a second graph API request and does not regenerate relationships.

## Supported Node Types

Stage 38C preserves the Stage 38B node-type inspector model and strengthens live binding for:

- Email
- Institution
- Person
- Case
- Reference Number
- Attachment
- Intake Record
- Cluster

Cluster selection now opens cluster information instead of clearing the panel. Explicit cluster expansion remains available as a context-sensitive action.

## Selection Clearing

Selection clears only when the user activates the Clear selection control, presses Escape, clicks genuinely empty graph canvas, or applies filters that remove the selected node from the graph payload.

Selection is preserved during node drag, graph pan, zoom, layout reuse, quick-action focus, and graph rendering when the payload still contains the selected node.

## Context-Sensitive Actions

Quick actions remain type-specific and are shown only when they can perform a real operation from available metadata. Filter actions update existing filters and reload through the established filter path. Highlight actions update graph emphasis without modifying underlying graph data. Open actions use existing routes only when the graph payload provides safe route metadata.

## Accessibility

Graph nodes expose `aria-selected` and remain keyboard selectable. Enter and Space select a node; Escape clears selection. The inspector remains an `aria-live` region with structured headings and accessible text.

## Governance Boundaries

CDE Platform Stage 38C is a client-side investigation-workspace correction. It does not alter governed source bytes, verification hashes, mailbox projections, lifecycle history, publication eligibility, relationship extraction, or the independent CREF methodology.

## Validation

Validation for this stage includes focused graph tests, the full unit suite, Python compilation of the affected route and focused tests, `git diff --check`, and a conflict-marker scan.
