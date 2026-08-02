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
