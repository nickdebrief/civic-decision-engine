from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

# ============================================================
# Request Models
# ============================================================


class CivicCaseRequest(BaseModel):
    strike_reference: str
    case_title: str
    civic_domain: str | None = None
    decision_trigger: str | None = None
    recall_question: str | None = None
    case_description: str | None = None
    user_priority: str | None = None
    desired_outcome: str | None = None
    urgency: str | None = None
    institutions: list[str] = Field(default_factory=list)
    case_lifecycle: dict[str, Any] = Field(default_factory=dict)
    rules_or_procedures: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    actors: list[dict[str, Any]] = Field(default_factory=list)
    evidence_bundle: list[dict[str, Any]] = Field(default_factory=list)
    deadlines: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    escalation_paths: list[dict[str, Any]] = Field(default_factory=list)
    linked_cases: list[dict[str, Any]] = Field(default_factory=list)
    structural_insight: str | None = None
    personal_positioning: str | None = None
    decision_note: str | None = None
    learning_capture: str | None = None


class CasesRequest(BaseModel):
    cases: list[CivicCaseRequest]


# ============================================================
# Response Models
# ============================================================


class SignalsResponse(BaseModel):
    posture: str
    engagement: str
    escalation: str
    behaviour_index: int


class AssessmentResponse(BaseModel):
    label: str
    interpretation: str


class CivicResultResponse(BaseModel):
    system_reference: str
    title: str
    domain: str
    declared_purpose: str | None
    signals: SignalsResponse
    condition: str
    assessment: AssessmentResponse


class RunMetadataResponse(BaseModel):
    run_id: str
    generated_at: str
    mode: str
    case_count: int
    lineage: dict[str, Any]


class CivicRunResponse(BaseModel):
    run_metadata: RunMetadataResponse
    results: list[CivicResultResponse]


class TimelineResultResponse(BaseModel):
    run_sequence: list[str]
    case_sequence: list[str]
    behaviour_indices: list[int]
    conditions: list[str]
    progression: list[str]
    trajectory: str
    moment_of_change: dict[str, Any] | None
    interpretation: str


class TimelineRunResponse(BaseModel):
    run_metadata: RunMetadataResponse
    results: list[TimelineResultResponse]


class PatternResultResponse(BaseModel):
    dominant_conditions: list[dict[str, Any]]
    dominant_labels: list[dict[str, Any]]
    recurring_transitions: list[dict[str, Any]]
    pattern_summary: str
    pattern_interpretation: str
    system_state: str
    signals: list[str]


class PatternRunResponse(BaseModel):
    run_metadata: RunMetadataResponse
    results: list[PatternResultResponse]


class HealthResponse(BaseModel):
    status: str
    engine: str
    version: str
    modes: list[str]


class AdaptationResultResponse(BaseModel):
    case_sequence: list[str]
    behaviour_indices: list[int]
    progression: list[str]
    trajectory: str
    moment_of_change: dict[str, Any] | None
    interpretation: str


class AdaptationRunResponse(BaseModel):
    run_metadata: RunMetadataResponse
    results: list[AdaptationResultResponse]


# ============================================================
# Public Record Models
# ============================================================


class RecordPayload(BaseModel):
    reference: str
    record_type: str = "strike"
    generated_at: str

    trajectory: str = ""
    system_state: str = ""

    conditions: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)

    finding: str = ""

    report: dict[str, Any] = Field(default_factory=dict)

    language: str = "en"

    supersedes: str | None = None

    source_narrative: str | None = None


class RecordResponse(BaseModel):
    reference: str
    record_type: str = "strike"
    version: int
    verification_hash: str
    verify_url: str
    is_superseding: bool


# ── API Response Models ───────────────────────────────────────
class RecordMinimalResponse(BaseModel):
    reference: str
    record_type: str = "strike"
    finding: str
    trajectory: str
    conditions: list[str]
    system_state: str
    verification_hash: str
    version: int


class RecordFullResponse(BaseModel):
    reference: str
    record_type: str = "strike"
    finding: str
    trajectory: str
    conditions: list[str]
    system_state: str
    verification_hash: str
    version: int
    generated_at: str
    exported_at: str
    language: str
    supersedes: str | None
    generated_by: str
    version_history: list[dict[str, Any]]


class RecordIndexItem(BaseModel):
    reference: str
    record_type: str = "strike"
    trajectory: str
    conditions: list[str]
    system_state: str
    institution_type: str
    exported_at: str
    version: int


class RecordIndexResponse(BaseModel):
    total: int
    filters: dict[str, Any]
    records: list[RecordIndexItem]
