# CDE v12.5.6 — Public Document Library Label Alignment

## Objective

CDE v12.5.6 aligns the shared public footer navigation label with the formal feature name used in CDE documentation, release records, and CV materials.

The existing `/documents` route is unchanged. The public footer now displays **Public Document Library** instead of **Public Library**.

## Scope

This is a navigation-label refinement only. It changes the visible footer text for the existing public document library link and preserves the link target exactly as `/documents`.

No document intake, approval workflow, lifecycle status, publication control, authentication, authorization, evidence handling, SHA-256 verification, database behaviour, public/private visibility boundary, or API behaviour was changed.

## Public Footer Behaviour

The shared public footer navigation remains:

Records · Conditions · Patterns · Stats · Graph · API docs · Public Document Library

The **Public Document Library** link:

- appears immediately after **API docs**;
- targets exactly `/documents`;
- uses the same public footer link styling as the existing footer links;
- does not introduce administration navigation into the public navigation group; and
- does not expose private intake, lifecycle, evidence, review, or administrative information.

## Validation

Focused footer-navigation tests confirm that the canonical label appears, the target remains `/documents`, the shortened footer label is no longer used, existing footer links remain present, and private or unpublished intake-document data is not exposed.

The Public Document Library tests and full regression suite should continue to pass with no functional behaviour change.
