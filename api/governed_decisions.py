"""Passive application-layer views of accountable decision evidence.

This module deliberately contains no lifecycle, authorization, reconciliation,
confirmation, eligibility, persistence, or subject-mutation behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


PUBLISHED_DOCUMENT_SUBJECT_TYPE = "published_document"
PUBLISHED_DOCUMENT_DECISION_EVIDENCE_TYPE = "published_document_lifecycle_decision"


@dataclass(frozen=True)
class GovernedSubjectReference:
    """Opaque identity for a domain-owned governed subject."""

    subject_type: str
    subject_id: str

    def __post_init__(self) -> None:
        if not str(self.subject_type).strip():
            raise ValueError("governed_subject_type_required")
        if not str(self.subject_id).strip():
            raise ValueError("governed_subject_id_required")


@dataclass(frozen=True)
class GovernedEvidenceReference:
    """Opaque pointer to evidence owned and interpreted by a domain."""

    reference_type: str
    reference_id: str

    def __post_init__(self) -> None:
        if not str(self.reference_type).strip():
            raise ValueError("governed_evidence_reference_type_required")
        if not str(self.reference_id).strip():
            raise ValueError("governed_evidence_reference_id_required")


@dataclass(frozen=True)
class GovernedDecision:
    """Immutable, domain-neutral accountability evidence.

    Optional state fields describe a domain result when one exists.  They do
    not validate or authorize a transition.
    """

    decision_id: str
    subject: GovernedSubjectReference
    actor: str
    actor_role: str
    decided_at: str
    decision_type: str | None = None
    previous_state: str | None = None
    resulting_state: str | None = None
    rationale: str | None = None
    evidence_references: tuple[GovernedEvidenceReference, ...] = ()
    context_reference: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "actor", "actor_role", "decided_at"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"governed_decision_{field_name}_required")
        if not isinstance(self.subject, GovernedSubjectReference):
            raise TypeError("governed_decision_subject_invalid")
        if not isinstance(self.evidence_references, tuple) or not all(
            isinstance(reference, GovernedEvidenceReference)
            for reference in self.evidence_references
        ):
            raise TypeError("governed_decision_evidence_references_invalid")

    def as_dict(self) -> dict[str, Any]:
        """Return a deterministic inspection/serialization shape."""

        return asdict(self)


def adapt_published_document_decision(
    event: Mapping[str, Any],
) -> GovernedDecision:
    """Adapt one existing Stage 56/58 event without reading or writing storage."""

    decision_key = str(event.get("decision_key") or "").strip()
    intake_id = str(event.get("intake_id") or "").strip()
    evidence = (
        GovernedEvidenceReference(
            reference_type=PUBLISHED_DOCUMENT_DECISION_EVIDENCE_TYPE,
            reference_id=decision_key,
        ),
    )
    episode_id = str(event.get("episode_id") or "").strip() or None
    return GovernedDecision(
        decision_id=decision_key,
        subject=GovernedSubjectReference(
            subject_type=PUBLISHED_DOCUMENT_SUBJECT_TYPE,
            subject_id=intake_id,
        ),
        actor=str(event.get("actor") or ""),
        actor_role=str(event.get("actor_role") or ""),
        decided_at=str(event.get("decided_at") or ""),
        previous_state=event.get("previous_status"),
        resulting_state=event.get("new_status"),
        rationale=event.get("rationale"),
        evidence_references=evidence,
        context_reference=episode_id,
        idempotency_key=decision_key,
    )
