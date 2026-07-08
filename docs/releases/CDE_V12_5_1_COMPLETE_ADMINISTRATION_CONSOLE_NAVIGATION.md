# CDE v12.5.1 — Complete Administration Console Navigation

## Objective

CDE v12.5.1 completes the existing authenticated Administration Console so
each principal administrative subsystem is directly represented on the
dashboard. It extends CDE v12.5 and does not create a second administration
system.

## Dashboard Navigation

`GET /admin` now presents four first-class summary cards:

- **Pending Intake** shows private uploads awaiting review and links to intake
  management.
- **Review Queue** shows the existing active-management count for Pending
  Intake, Under Review, and Approved documents.
- **Record Evidence** links to the dedicated Open Record Evidence destination.
- **Public Library** shows the current Published count and links to
  `GET /documents`.

The existing lifecycle table and detailed review queue remain available below
the summary cards.

## Open Record Evidence

The former standalone record-reference lookup is now a dedicated dashboard
card. It explains that the existing record evidence view supports inspection
of visible evidence relationships, determination traces, dependency and
stability views, provenance, verification details, and report modes.

The administrator must still supply a known record reference. CDE v12.5.1 does
not enumerate records, add a record search API, or change the existing route:

`GET /admin/records/{reference}/evidence`

## Shared Navigation

Record Evidence remains a peer destination alongside Document Intake, Intake
Management, and Public Library. Record-specific pages continue to preserve the
current reference in the navigation link; other admin pages return to the
dashboard's Open Record Evidence card.

## Security and Behaviour Boundaries

- All administration pages continue to require the existing signed session.
- Private intake records remain private.
- Public Library eligibility remains restricted to Published documents.
- No lifecycle, publication, evidence relationship, classification, hashing,
  verification, upload/download, or record mutation behaviour changes.
- No database, schema, migration, public API, or authentication changes are
  introduced.

## Tests

Focused tests cover the four summary cards, card counts and destinations, the
Open Record Evidence description and form, shared navigation, authentication,
review queue links, and existing login behaviour. The complete regression
suite remains required before release.

## Limitation

This stage is an administrative navigation and usability enhancement only. It
does not add record discovery, analytics, workflow automation, or new
administrative authority.
