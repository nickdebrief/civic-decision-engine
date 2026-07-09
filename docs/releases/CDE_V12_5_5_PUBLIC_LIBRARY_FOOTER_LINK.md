# CDE v12.5.5 — Public Library Footer Link

## Objective

CDE v12.5.5 adds the existing Public Document Library route to the shared
public footer navigation. The public route already exists at `/documents`; this
stage makes it discoverable from the same footer navigation that already links
to Records, Conditions, Patterns, Stats, Graph, and API docs.

## Footer Navigation

The public footer navigation now renders:

Records · Conditions · Patterns · Stats · Graph · API docs · Public Library

The **Public Library** link:

- appears immediately after **API docs**;
- targets exactly `/documents`;
- uses the existing `public-footer-link` styling;
- uses the label **Public Library**, not Documents.

## Behaviour Boundary

This stage does not change `/documents` access rules or publication behaviour.
The Public Document Library still shows only documents whose lifecycle state is
Published. Pending Intake, Under Review, Approved, Archived, and Rejected
documents remain private and inaccessible through public routes.

## Security Boundary

This stage does not add admin navigation to the public footer navigation and
does not expose intake documents, lifecycle states, review queues, evidence,
private files, administrative counts, or admin state.

It does not change authentication, authorization, document intake, approval
workflow, publication controls, evidence relationships, classification logic,
hashes, verification, records, attachments, database state, or public API
behaviour.

## Tests

Focused tests verify that the public footer includes **Public Library**, the
link target is exactly `/documents`, the link appears after **API docs**, the
existing public footer links remain present, the public navigation does not add
admin navigation, and private/unpublished document data remains excluded from
public document-library behaviour.

The full regression suite remains required before release.

## Limitation

CDE v12.5.5 is a navigation-only refinement. It introduces no new route,
visibility rule, lifecycle behaviour, or administrative capability.
