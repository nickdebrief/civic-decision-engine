# CDE v12.5 — Admin Navigation Console

## Objective

CDE v12.5 turns the existing authenticated admin area into a coherent
Administration Console without creating a second administration system. It
connects document intake, lifecycle review, record evidence inspection, public
library verification, and session tools through a shared navigation model.

## Administration Dashboard

`GET /admin` is the authenticated console landing page. It provides:

- links to new document intake;
- links to full intake management;
- lifecycle counts for Pending Intake, Under Review, Approved, Published,
  Archived, and Rejected;
- an active review queue for Pending Intake, Under Review, and Approved items;
- direct links from queue rows to individual review pages;
- a record-reference entry form for the existing Admin Record Evidence page;
- a link to the Public Document Library; and
- the existing admin-session logout action.

The record-reference form does not publish or enumerate private records. It
navigates to the existing evidence view only for the reference supplied by the
administrator.

## Shared Navigation

The shared **Administration Console** navigation appears on:

- the Administration Dashboard;
- Admin Document Intake;
- individual Document Intake Review pages;
- Admin Attachment Management; and
- Admin Record Evidence.

Its destinations are:

- Administration / Dashboard;
- Document Intake;
- Intake Management;
- Record Evidence; and
- Public Library.

Record-specific pages preserve the current reference in their Record Evidence
link. Other pages return administrators to the dashboard's reference-entry
tool.

## Intake Review Linkage

Review pages are reachable from the intake-management table and the dashboard
review queue. The intake page separates the new-upload section from the
management section with stable anchors so navigation can target each workflow
directly.

## Public Library Linkage

The Public Library navigation item points to `GET /documents`, allowing an
administrator to verify the exact public view. It does not grant the public
library access to private intake states or admin metadata.

## Security Boundaries

- `/admin` and every existing admin page continue to require the signed admin
  session.
- `/admin/login` remains the sole login surface and its response contract is
  unchanged.
- The Public Document Library remains intentionally public.
- Dashboard counts and review links are rendered only after admin
  authentication.
- Private intake records remain unavailable through public library routes.
- Navigation introduces no file serving, lifecycle transition, publication, or
  record mutation behavior.

## Tests Run

Tests cover authenticated dashboard rendering, unauthenticated denial, all
required navigation links, lifecycle counts, review-queue deep links,
record-aware evidence navigation, shared navigation on intake/review pages,
private review protection, and preservation of the existing login contract.
Existing admin, intake, public-library, upload, and full regression suites
remain mandatory.

## Limitations

The dashboard requires an administrator to enter a known record reference; it
does not introduce a private record search or index. Counts describe current
intake sidecars only. This stage does not add role-based permissions, named
administrator identities, or new session capabilities.

## Preserved Behaviour

CDE v12.5 is navigation and usability only. It changes no CREF methodology,
CREF 3.1 specification, document lifecycle rule, approval transition,
publication rule, public API behavior, evidence relationship, verification
hash, classification, evaluation, database schema, or public/private state.
