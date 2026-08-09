# CDE Platform Stage 56 — Durable Document Lifecycle Decision Record

## Purpose

CDE Platform Stage 56 makes each governed post-intake lifecycle decision an
independently durable administrative record. The existing `metadata.json`
`status_history` remains the compatibility and presentation projection; a new
SQLite table in the existing governance database records the decision before
the document's current lifecycle metadata advances.

## Durable Decision Evidence

Each application-level append-only event records the intake identity, existing
Document Identifier where available, previous and new lifecycle states,
decision timestamp, verified session account and role, governance rationale,
and the CDE-recorded SHA-256 and available SHA-512 digest at decision time.

Lifecycle decision recording resolves an already-assigned Document Identifier
from the authoritative identifier registry first. Mutable document metadata
cannot override an existing registry assignment. Legacy metadata may supply the
identifier only when no registry assignment exists, and recording a lifecycle
decision does not allocate a new Document Identifier.

The digest is a snapshot of the digest already recorded by the CDE. Stage 56
does not perform a fresh transition-time rehash, add a hashing algorithm,
cryptographically sign events, or make the SQLite store cryptographically
immutable. The record establishes what the CDE recorded about an authenticated
account's decision; it does not establish natural-person identity, factual
truth, legal validity, or correctness of the decision.

## Idempotency and Recovery

Decision identity uses a per-document decision sequence and a deterministic
internal key derived from that sequence and the stable decision inputs. It does
not use `UNIQUE(intake_id, previous_status)`, so historical storage does not
permanently encode the current acyclic transition graph.

The lifecycle coordinator records the event first and then atomically replaces
the JSON compatibility projection. An identical retry reuses an existing
unprojected event and may complete the projection without duplicating history.
A conflicting decision is rejected. Administrative Audit and per-document
Status History distinguish **Durable decision record — correctly projected**,
**Decision recorded; metadata projection pending**, and **Decision record /
metadata projection inconsistent**. A genuine projection failure remains
pending while compatibility metadata still reflects the legitimate
pre-decision state. Divergence in the governed projection, including linked
history, current lifecycle state, and applicable lifecycle timestamps, can be
classified inconsistent. Administrative GET rendering is observational and
does not reconcile or repair the projection. Approval and publication fail
closed when durable recording fails or the required SHA-256 is unavailable.

SQLite lifecycle decision storage and the `metadata.json` compatibility
projection do not share a single atomic transaction. Stage 56 therefore uses
event-first recording, fail-closed lifecycle advancement, deterministic
retry/idempotency, and explicit pending or inconsistent projection visibility.
A durable historical decision record may survive a failed metadata projection
and require an explicit governed write retry. This is not strict cross-store
atomicity, and application-level append-only records are not cryptographically
immutable or tamper-proof.

## Rationale and Legacy History

The existing transition note is the decision rationale. It remains optional
when review begins and is required for approval, publication, rejection, and
archive. The server enforces the existing 500-character limit. Administrators
are reminded that lifecycle notes may appear in the existing public Publication
Pathway after publication.

No historical events are manufactured. Earlier `status_history` entries remain
visible as **Legacy sidecar history**. Future decisions on legacy documents may
create durable records from the document's actual current state. Rejection and
archive may record digest unavailability so incomplete legacy evidence can
still be withdrawn safely.

## Boundaries

Stage 56 adds no database file, document identity, lifecycle state,
relationship type, hashing algorithm, public route, public eligibility rule, or
public disclosure field. Publication continues to mean intentional release
through the governed CDE workflow; it does not certify every statement in a
document as true. Preservation, verification, Canonical Records, email archive
projection, and attachment governance are unchanged.
