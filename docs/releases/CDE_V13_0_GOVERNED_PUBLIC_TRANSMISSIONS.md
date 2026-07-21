# CDE v13.0 — Governed Public Transmissions

## Purpose

CDE v13.0 introduces Public Transmissions as first-class governed public
objects.

Documents preserve content. Transmissions preserve context.

A Public Transmission preserves the public communication context in which one
or more independently governed public objects were communicated. It is not an
email system, messaging system, correspondence store, or object-storage surface.

A Transmission governs communication. It does not govern the objects communicated.

## Governance Philosophy

The Civic Decision Engine governs independently identifiable public objects.
Before v13.0, the public governance graph included Canonical Records, Published
Documents, Record-Document Associations, and Governed Public Collections.

v13.0 recognises that a communication can also be a public governed event. The
covering communication, such as `Please find attached...`, is distinct from the
documents or objects transmitted with it. Those attached objects retain their
own governed identities.

No object absorbs another.

## Object Model

The new governed object is `Public Transmission`.

Each Transmission has:

- stable public reference using the `TRM-YYYY-NNNN` pattern;
- title;
- summary;
- sender;
- recipient;
- transmission date;
- controlled communication method;
- subject;
- covering message;
- optional external reference;
- optional transmission identifier;
- administrative notes;
- lifecycle and publication state;
- created, updated, published, and archived metadata;
- independent history/provenance entries.

Controlled communication methods are:

- Email;
- Letter;
- Portal Upload;
- Secure Exchange;
- Court Filing;
- Publication;
- Other.

## Relationship Model

A Transmission can reference public governed objects through explicit
Transmission Attachment relationships.

Supported initial transmitted object types are:

- Published Document;
- Canonical Record;
- Record-Document Association;
- Governed Public Collection.

Each relationship has its own attachment reference, object type, object
reference, relationship label, optional public note, position, active state,
created metadata, and history through the parent Transmission pathway.

The transmitted object is never copied into the Transmission. Its original
reference, lifecycle, provenance, verification, public page, and SHA-256 remain
unchanged.

## Lifecycle

Public Transmissions use a governed lifecycle aligned with existing platform
patterns:

- Pending Intake;
- Review;
- Approved;
- Published;
- Archived.

Only Transmissions with `Published` status and public visibility appear on
public pages.

## Public Representation

The new Public Transmission Library is available at:

```text
/transmissions
```

Each public Transmission detail page is available at:

```text
/transmissions/{TRM-reference}
```

The public detail page displays:

- Transmission metadata;
- communication context;
- covering communication;
- included governed objects;
- links to each attached object's independent public page;
- public-safe Transmission publication provenance.

The page states that documents preserve content and transmissions preserve
context, and that attached objects remain independently governed.

## Administrative Workflow

The Administration Console now includes:

- Transmission Intake;
- Transmission Management.

Administrators can create a Transmission, review its metadata, move it through
the governed lifecycle, declare it public, and attach eligible public governed
objects.

Attachment submission is validated server-side. The administrator cannot use a
hidden field, raw object reference, or client-side filtering to expose an
ineligible object.

## Search and Discovery

Public Transmission Library search covers:

- Transmission reference;
- title;
- summary;
- sender;
- recipient;
- subject;
- covering message;
- communication method;
- external reference;
- transmission identifier;
- attached object references and public-safe searchable metadata.

The Public Archive Explorer includes Public Transmissions as a governed object
type and supports filtering by `type=public_transmission`.

## Traceability

The Public Traceability Map now includes a Transmission Traceability View.

Transmission relationships render as:

```text
Public Transmission
        |
        | communicates
        v
Governed public object
```

The Transmission is rendered as its own node. It does not own or absorb the
transmitted object, which remains independently navigable.

## Collections

Governed Public Collections may include Public Transmissions as members.

Collection membership does not make the collection the owner of the
Transmission and does not make the Transmission the owner of attached objects.
Collections organise public objects without absorbing identity.

## Future Extensibility

The relationship model is typed so future governed public objects can be added
without redesigning the Transmission table or weakening the existing object
boundaries.

Future v13.x work may add richer communication context, but v13.0 deliberately
does not implement email ingestion, mailbox integration, sending, reply
threading, notifications, or governed public transmissions for private objects.

## Preserved Behaviour

This release does not change:

- document identity;
- record identity;
- association identity;
- collection identity;
- publication semantics;
- SHA-256 semantics;
- duplicate intake detection;
- provenance rules;
- traceability eligibility;
- authorization;
- public eligibility;
- storage;
- original uploaded artefacts.

No existing governed object is modified to become a Transmission.

## Validation

Focused tests cover Transmission creation, lifecycle, controlled communication
methods, covering message rendering, transmitted-object relationships, public
visibility, public library search, Archive Explorer discovery, Traceability Map
Transmission nodes, Collection membership, administrative navigation, and
confirmation that existing governed object references and SHA-256 values are
not duplicated or changed.
