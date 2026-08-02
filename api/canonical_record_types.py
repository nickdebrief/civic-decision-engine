"""Controlled semantic classifications for Canonical Records."""

from __future__ import annotations

from enum import Enum


class CanonicalRecordType(str, Enum):
    STRIKE = "strike"
    COMPLAINT = "complaint"
    INVESTIGATION = "investigation"
    DECISION = "decision"
    PROCEEDING = "proceeding"
    ADMINISTRATIVE_ACTION = "administrative_action"
    CLINICAL_EPISODE = "clinical_episode"
    MEDICAL_EVENT = "medical_event"
    TREATMENT_EPISODE = "treatment_episode"
    CARE_EPISODE = "care_episode"
    CLINICAL_RECORD = "clinical_record"
    PUBLIC_SUBMISSION = "public_submission"
    POLICY_EVENT = "policy_event"
    RESEARCH_RECORD = "research_record"


RECORD_TYPE_DEFINITIONS: tuple[tuple[CanonicalRecordType, str, str], ...] = (
    (CanonicalRecordType.STRIKE, "Strike", "Strike"),
    (CanonicalRecordType.COMPLAINT, "Complaint", "CMP"),
    (CanonicalRecordType.INVESTIGATION, "Investigation", "INV"),
    (CanonicalRecordType.DECISION, "Decision", "DEC"),
    (CanonicalRecordType.PROCEEDING, "Proceeding", "PRC"),
    (CanonicalRecordType.ADMINISTRATIVE_ACTION, "Administrative Action", "ADM"),
    (CanonicalRecordType.CLINICAL_EPISODE, "Clinical Episode", "CLE"),
    (CanonicalRecordType.MEDICAL_EVENT, "Medical Event", "MED"),
    (CanonicalRecordType.TREATMENT_EPISODE, "Treatment Episode", "TRT"),
    (CanonicalRecordType.CARE_EPISODE, "Care Episode", "CARE"),
    (CanonicalRecordType.CLINICAL_RECORD, "Clinical Record", "CLR"),
    (CanonicalRecordType.PUBLIC_SUBMISSION, "Public Submission", "SUB"),
    (CanonicalRecordType.POLICY_EVENT, "Policy Event", "POL"),
    (CanonicalRecordType.RESEARCH_RECORD, "Research Record", "RSR"),
)

RECORD_TYPE_LABELS: dict[str, str] = {
    record_type.value: label for record_type, label, _prefix in RECORD_TYPE_DEFINITIONS
}
RECORD_TYPE_PREFIXES: dict[str, str] = {
    record_type.value: prefix for record_type, _label, prefix in RECORD_TYPE_DEFINITIONS
}
DEFAULT_RECORD_TYPE = CanonicalRecordType.STRIKE.value


DOCUMENT_CATEGORY_RECORD_TYPE_RECOMMENDATIONS: dict[str, str] = {
    "evidence package": CanonicalRecordType.COMPLAINT.value,
    "complaint": CanonicalRecordType.COMPLAINT.value,
    "investigation material": CanonicalRecordType.INVESTIGATION.value,
    "decision": CanonicalRecordType.DECISION.value,
    "submission": CanonicalRecordType.PUBLIC_SUBMISSION.value,
    "proceeding": CanonicalRecordType.PROCEEDING.value,
    "research": CanonicalRecordType.RESEARCH_RECORD.value,
    "hospital admission": CanonicalRecordType.CLINICAL_EPISODE.value,
    "hospital admission / administrative record": (
        CanonicalRecordType.CLINICAL_EPISODE.value
    ),
    "admission form": CanonicalRecordType.CLINICAL_EPISODE.value,
    "consent form": CanonicalRecordType.CLINICAL_RECORD.value,
    "consent form / procedure consent": CanonicalRecordType.CLINICAL_RECORD.value,
    "operation record": CanonicalRecordType.TREATMENT_EPISODE.value,
    "operation record / procedure record": CanonicalRecordType.TREATMENT_EPISODE.value,
    "procedure record": CanonicalRecordType.TREATMENT_EPISODE.value,
    "pain intervention record": CanonicalRecordType.MEDICAL_EVENT.value,
    "pain intervention record / clinical procedure record": (
        CanonicalRecordType.MEDICAL_EVENT.value
    ),
    "clinical assessment": CanonicalRecordType.CLINICAL_RECORD.value,
    "medical report": CanonicalRecordType.CLINICAL_RECORD.value,
    "discharge summary": CanonicalRecordType.CARE_EPISODE.value,
    "post-operative instructions": CanonicalRecordType.CARE_EPISODE.value,
}


def recommended_record_type_for_document_category(category: object) -> str | None:
    """Return an explicit advisory recommendation for a document category."""

    normalized = str(category or "").strip().casefold()
    return DOCUMENT_CATEGORY_RECORD_TYPE_RECOMMENDATIONS.get(normalized)


def default_record_type_for_document_category(category: object) -> str:
    """Return the recommendation or preserve the established default."""

    return recommended_record_type_for_document_category(category) or DEFAULT_RECORD_TYPE
