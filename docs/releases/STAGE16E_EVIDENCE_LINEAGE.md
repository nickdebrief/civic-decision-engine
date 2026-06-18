# Stage 16E — Evidence Lineage

## Purpose

Stage 16E adds an Evidence Lineage layer to the read-only Admin Record Evidence
view. It exposes the recorded history of evidence support relationships for
each condition, signal, finding, and record target.

## Relationship to Stage 16D Evidence Traceability

Stage 16D Evidence Traceability answers which active evidence relationships
currently support a target.

Stage 16E Evidence Lineage answers how the target's evidence support history
developed over time using existing relationship metadata.

Traceability continues to count active `supports` relationships only. Lineage
may display inactive or removed `supports` relationships as historical events
when existing metadata is available.

## Lineage Summary Fields

The Evidence Lineage summary displays:

- Total Lineage Targets
- Total Relationship Events
- Active Support Relationships
- Inactive / Removed Relationships
- Targets With Lineage
- Targets Without Lineage

## Target-Level Lineage Fields

Each target lineage entry displays:

- target type and label
- total relationship events
- active support relationship count
- inactive or removed relationship count
- first support creation timestamp
- latest support creation timestamp
- active supporting attachment titles
- current sufficiency state
- current completeness state
- current confidence state
- ordered lineage events

Targets without relationship history display:

`No recorded evidence lineage events.`

## Active and Inactive Relationship Handling

Lineage is derived from existing attachment relationship rows. Active
relationships contribute to active support counts. Inactive or removed
relationships contribute only to lineage history and inactive/removed counts.

Non-`supports` relationships do not contribute to evidence support lineage.

## Deleted Attachment Handling

Deleted attachments are not treated as active support. The lineage layer does
not expose file bytes, storage paths, stored filenames, or download links.

## Admin-Only Scope

Stage 16E is an admin-only evidence assessment layer. It does not add upload
functionality, public file access, public download routes, public evidence pages,
or mutation controls.

## Canonical Verification

Stage 16E does not change canonical verification hashes, public manifests,
schemas, record versioning, attachment storage, or Stage 11-15 deterministic
progression logic.

## Example

For `Strike-LA-20260710-004`, a single active `supports` relationship for
`Escalation Without Response` produces one lineage event, one active support
relationship, and current target states derived from the existing sufficiency,
completeness, and confidence layers.
