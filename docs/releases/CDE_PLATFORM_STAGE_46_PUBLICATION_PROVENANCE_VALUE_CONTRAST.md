# CDE Platform Stage 46 — Publication Provenance Value Contrast

## Purpose

CDE Platform Stage 46 improves the readability of the Publication Provenance
view. Recorded values are visually prominent while field labels and unavailable
states retain their established hierarchy.

## Presentation

Populated provenance values use the established CDE teal. Unavailable or
not-applicable values use a muted neutral and remain identifiable through their
placeholder text rather than colour alone. Technical identifiers, hashes, and
timestamps retain a monospace typeface.

The styling is scoped to the Publication Provenance key-value component. It
does not recolour unrelated tables, pathways, archive pages, or other public
views. A dedicated dark-mode palette preserves the same visual hierarchy.

## Accessibility

The recorded-value teal provides strong contrast against the white provenance
surface. Dark mode uses the existing light CDE teal against the dark provenance
surface. Unavailable values remain readable and subordinate, and no font size
or weight is reduced.

## Governance Boundary

This stage changes presentation only. Provenance values, labels, order,
calculations, lifecycle, hashing, verification, API output, access controls,
public URLs, and database structures remain unchanged. The evidence is made
clearer without changing the evidence or its governance meaning.
