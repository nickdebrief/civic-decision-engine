# Railway Production Verification

This procedure verifies the Civic Decision Engine production deployment. It is
read-only and does not deploy, restart, relink, or modify Railway resources.

## 1. Establish Canonical Repository State

Run from the repository checkout:

```sh
git fetch origin
git switch main
git rev-parse HEAD
git rev-parse origin/main
git rev-list --left-right --count HEAD...origin/main
git status --short
```

Proceed only when local `main` equals `origin/main`, the ahead/behind count is
`0 0`, and the tracked worktree is clean. Do not assess deployment provenance
against divergent local history.

## 2. Identify the Production Target

Use explicit resource identifiers rather than Railway's current-directory
defaults:

```text
Project:     precious-gentleness
Project ID:  caaaade5-4fe4-4bfd-8a50-02bccdb6df6b
Environment: production
Environment ID: 108d53bc-2176-434c-968f-b165c7d6537d
Service:     civic-decision-engine
Service ID:  8b201df9-fd02-4c96-9257-7a89a750ff2c
```

Project discovery may be performed with `railway list --json`. The discovery
operation does not require repository linkage. Confirm the project by its
service and deployment provenance, not by a similar project name alone.

## 3. Inspect Deployment History

Use the read-only deployment listing with all three explicit selectors:

```sh
railway deployment list \
  --project caaaade5-4fe4-4bfd-8a50-02bccdb6df6b \
  --environment 108d53bc-2176-434c-968f-b165c7d6537d \
  --service 8b201df9-fd02-4c96-9257-7a89a750ff2c \
  --limit 20 --json
```

Record the latest successful deployment's Railway CLI deployment UUID,
status, source revision, creation/start time, environment, and service. The
principal check is whether its exact source revision equals canonical
`origin/main`; deployment ordering, timestamps, and titles do not establish
revision equivalence.

Railway CLI deployment UUIDs are distinct from numeric deployment identifiers
that may be supplied by Railway/GitHub evidence. Record both, when available,
without treating them as interchangeable.

## 4. Compare the Revision

Compare the deployment's exact `commitHash`/source revision with the SHA
reported by `git rev-parse origin/main`. Report:

```text
canonical Git SHA:
Railway deployment UUID:
deployment status:
deployment start timestamp:
project / environment / service:
revision match: yes/no
```

If the revisions differ, stop the verification and investigate the deployment
provenance. Do not redeploy or roll back as part of this procedure.

## 5. Inspect Bounded Logs

Retrieve logs for the exact deployment UUID, bounded to a small sample:

```sh
railway logs <DEPLOYMENT_UUID> \
  --project caaaade5-4fe4-4bfd-8a50-02bccdb6df6b \
  --environment 108d53bc-2176-434c-968f-b165c7d6537d \
  --service 8b201df9-fd02-4c96-9257-7a89a750ff2c \
  --lines 100
```

Check for normal application startup, healthy-running markers, and obvious
deployment or startup errors. Do not stream logs indefinitely during routine
verification. Never reproduce secrets, credentials, tokens, connection
strings, or private environment-variable values in a report; redact or omit
any sensitive material.

## 6. Record Provenance and Outcome

Record the canonical Git SHA, Railway CLI deployment UUID, status, timestamp,
project, environment, service, exact revision-match result, bounded-log
result, and whether any production mutation occurred. A successful deployment
status is not a substitute for comparing the source revision.

The current verified CLI example is:

```text
canonical Git revision: 92c83bc416017e23258347516ff2387d15fc666d
Railway CLI deployment UUID: 96eb0394-bb2a-4dff-8657-b802b264415f
status: SUCCESS
started: 2026-08-15T13:26:47.581Z
environment: production
service: civic-decision-engine
```

The CLI did not expose the numeric deployment identifier previously available
through other Railway/GitHub evidence. Any such numeric identifier must remain
a separate provenance field.

## 7. Preserve the Deployment Boundary

Routine verification must not run or invoke operations that change production
state. In particular, do not use:

- `railway up`, `railway redeploy`, or `railway down`;
- variable mutation commands;
- environment or service creation, deletion, or editing;
- database, volume, or domain mutation commands;
- SSH or agent commands;
- restart or integration-management operations;
- `railway link` unless a separately authorised workflow establishes that it is
  necessary.

Deployment is a separately authorised operation. Verification does not create
observations, associations, relationships, history, or other production data.

## Operational Notes

- Project discovery was possible with `railway list --json` without repository
  linkage.
- Deployment inspection was possible with explicit project, environment, and
  service selectors without `railway link`.
- Bounded logs were readable for an explicitly selected deployment without
  repository linkage.
- Routine CDE production verification therefore does not currently require
  `railway link`; avoiding unnecessary linkage reduces reliance on
  repository-local selection state.
- A later `railway status` attempt encountered a DNS-resolution failure after
  the read-only deployment and log queries had succeeded. It caused no
  mutation and must be treated as an operational/network failure, not as
  evidence of deployment failure, unless independently corroborated.
