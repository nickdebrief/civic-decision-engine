# Stage Numbering Policy

## Purpose

The Civic Decision Engine repository maintains two independent stage numbering sequences.

Although both use stage numbers, they describe different concepts and should never be interpreted as corresponding versions of one another.

## CREF Stage

The **CREF Stage** sequence documents the evolution of the Civic Record Exchange Framework.

It represents framework methodology, record lifecycle, governance, and specification development.

Examples include:

- Canonical Record lifecycle
- Provenance model
- Verification methodology
- Publication framework
- Governance principles

## CDE Platform Stage

The **CDE Platform Stage** sequence documents implementation milestones for the Civic Decision Engine software.

It represents engineering work, platform capabilities, user interface development, APIs, storage, search, workflow, and infrastructure.

Examples include:

- Semantic Search
- Condition Graph
- Mailbox Relationship Graph
- Workflow Engine
- Public Archive
- Administrative tooling

## Independence

The two sequences are intentionally independent.

For example:

- CREF Stage 38 does not imply CDE Platform Stage 38.
- CDE Platform Stage 40 does not imply CREF Stage 40.

Each sequence advances only when work within that domain progresses.

## Repository Guidance

When referring to stages in documentation, release notes, code comments, UI text, or commit messages:

- Always use **CREF Stage** for framework methodology.
- Always use **CDE Platform Stage** for software implementation.
- Avoid unqualified references such as "Stage 37" where ambiguity could arise.

This convention exists to ensure long-term clarity as the framework and platform evolve independently.
