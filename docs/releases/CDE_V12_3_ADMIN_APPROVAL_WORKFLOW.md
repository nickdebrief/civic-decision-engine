# CDE v12.3 — Admin Approval Workflow

## Objective

CDE v12.3 extends the authenticated Admin Document Intake workflow with an
explicit review lifecycle, contextual administrative actions, private notes,
and append-only status history. It reuses the existing admin login, signed
session cookie, intake storage, SHA-256 identifier, metadata sidecar, routes,
and visual conventions.

## Lifecycle States

- **Pending Intake:** initial private state after upload.
- **Under Review:** an administrator has begun reviewing the document.
- **Approved:** administrative review passed; the document remains private.
- **Published:** publication intent/status has been declared. In v12.3 this does
  not expose or attach the document publicly.
- **Rejected:** administrative review did not approve the document; it remains
  private.
- **Archived:** the document is retained privately outside the active workflow.

## Valid Transitions

| Previous state | Permitted next state |
| --- | --- |
| Pending Intake | Under Review |
| Under Review | Approved, Rejected |
| Approved | Published, Archived |
| Rejected | Archived |
| Published | Archived |
| Archived | None |

Any transition not listed above returns a conflict error and leaves the JSON
sidecar unchanged.

## Administrative Routes And Actions

- `GET /admin/document-intake` lists all intake documents and lifecycle states.
- `GET /admin/document-intake/{intake_id}` provides metadata, hash, storage
  path, private notes, status history, and contextual actions.
- `POST /api/admin/session/document-intake/{intake_id}/status` performs one
  valid lifecycle transition and accepts an optional transition note.
- `POST /api/admin/session/document-intake/{intake_id}/notes` updates private
  internal notes without changing lifecycle state.

Every route uses the existing admin-session authentication. No second admin
system, token, or login flow is introduced.

## Audit And Status History

New uploads record their initial Pending Intake event. Each successful
transition appends:

- previous status;
- new status;
- UTC timestamp;
- available admin role identifier; and
- optional transition note.

The complete history remains in the private metadata sidecar. Sidecar updates
use a temporary file and atomic replacement. Existing v12.2 sidecars without a
history are supported by recording their visible current state before the first
transition.

## Security Model

- All list, review, transition, and notes routes require the existing signed
  admin session.
- Pending, under-review, approved, rejected, archived, and published-status
  files remain beneath the private intake root.
- No document-content route or public download route is introduced.
- Notes and status history are visible only through authenticated admin pages.
- Invalid identifiers and transitions are rejected.
- Lifecycle changes do not touch SQLite records or attachment tables.

## Publication Boundary

Approval does not publish. The v12.3 **Published** state is a declared lifecycle
state only. It does not create a public record, modify a public record, insert a
record attachment, activate an evidence relationship, change a public manifest,
or serve a file publicly. Public exposure and record linking remain deferred to
a separately implemented stage.

## Limitations

CDE v12.3 does not perform publication, attachment activation, record creation,
content validation, OCR, malware analysis, evidence validation, truth
determination, classification, or threshold evaluation. It does not provide
named administrator identities because the current session contains only the
admin role. It records that role as the available actor identifier.

## Tests Run

Tests cover initial Pending Intake state, all valid transition branches,
rejection and archive handling, Published-to-Archived handling, invalid
transition rejection, unauthenticated denial, private note persistence,
status-history entries, management/review rendering, absence of public file
serving, and database/public-record immutability through Published status.
Existing intake, attachment upload, admin, and full regression suites remain
part of release validation.

## Preserved Behaviour

Approval does not automatically publish. No lifecycle action mutates a public
record. This stage changes no CREF methodology, CREF 3.1 specification, schema,
migration, canonical verification hash, attachment hash, classification
threshold, evidence relationship, existing record verification behavior, or
public API behavior.
