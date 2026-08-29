"""Stage 78A read-only pathway projection tests.

Every fixture uses isolated SQLite databases and synthetic governed records.
No production data, external system or producer-module write path outside the
fixture setup is exercised.  The projection itself is proven read-only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import record_document_associations as associations
from api import record_governed_allegations as allegations
from api import record_governed_characterisations as characterisations
from api import record_governed_challenges as challenges
from api import record_governed_decision_authorities as authorities
from api import record_governed_determination_publications as publications
from api import record_governed_determinations as determinations
from api import record_governed_implementation_events as implementation_events
from api import record_governed_inferences as inferences
from api import record_governed_pathway as pathway
from api import record_governed_pathway_projection as projection
from api import record_governed_procedural_time as pt
from api import record_governed_remedies as remedies
from api import record_governed_responses as responses
from api import record_pattern_observations as observations

RECORD = "REC-78"
OTHER_RECORD = "REC-OTHER"

PROHIBITED_PHRASES = (
    "no notice was sent",
    "did not respond",
    "deadline was missed",
    "no opportunity to participate existed",
    "notice was received",
    "filing was late",
    "inadequate notice",
    "invalid deadline",
    "no allegation was made",
    "no response was given",
    "the allegation was false",
    "the response disproved it",
    "an inference was correct",
    "a characterisation was a finding",
    "no decision was made",
    "no reasons existed",
    "the authority had no jurisdiction",
    "decision was lawful",
    "decision was unlawful",
    "the decision was correct",
    "the challenge failed",
    "remained legally valid",
    "no remedy was provided",
    "implementation was complete",
    "proof of compliance",
    "non-compliance finding",
    "publication is endorsement",
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProjectionFixture:
    """Shared fixture helpers for Stage 78A projection tests."""

    FIXED_CREATED_AT = "2026-08-28T00:00:00Z"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def seed_records(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO records VALUES (?, '1', '2026-08-28T00:00:00Z')", (RECORD,)
        )
        conn.execute(
            "INSERT INTO records VALUES (?, '1', '2026-08-28T00:00:00Z')", (OTHER_RECORD,)
        )

    @classmethod
    def fresh_connection(cls) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cls.seed_records(conn)
        return conn

    def source(self, role: str = "notice_source") -> list[dict[str, str]]:
        return [{"source_type": "canonical_record", "source_id": RECORD, "binding_role": role}]

    def subject(self, record: str = RECORD, role: str = "notice_concerns") -> list[dict[str, str]]:
        return [{"object_type": "canonical_record", "object_id": record, "relationship_role": role}]

    def contract(self, kind: str = "notice") -> dict[str, object]:
        return {"epistemic_label": kind, "source_bound": True, "not_legal_effect": True}

    def notice(self, **overrides) -> dict:
        values = dict(
            notice_category="notice_issued",
            title_label="Notice",
            notice_description="A notice as represented",
            issuing_label="Institution",
            issuing_capacity="Registrar",
            intended_recipient="Participant",
            issue_date_or_period="2026-08-01",
            dispatch_method="recorded method",
            procedural_subject="Proceeding",
            rationale="Preserve the record",
            qualification=pt.NOTICE_BOUNDARY,
            limitations=pt.LIMITATIONS_BOUNDARY,
            qualification_contract=self.contract(),
            declaration=None,
            bindings=self.source(),
            subject_links=self.subject(),
            actor="admin",
            actor_role="administrator",
            idempotency_key="notice-1",
            created_at=self.FIXED_CREATED_AT,
        )
        values.update(overrides)
        with patch.object(pt.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return pt.create_notice(self.conn, **values)

    def deadline(self, **overrides) -> dict:
        values = dict(
            deadline_category="response_deadline",
            title_label="Response deadline",
            procedural_subject="Proceeding",
            trigger_event="Notice issued",
            trigger_date_or_period="2026-08-01",
            deadline_date_or_period="2026-08-15",
            date_precision="date",
            time_precision=None,
            time_zone="UTC",
            calculation_rule="source stated",
            counting_convention="calendar days",
            inclusivity="inclusive",
            conditions=None,
            affected_participant="Participant",
            rationale="Preserve the stated deadline",
            qualification=pt.DEADLINE_BOUNDARY,
            limitations=pt.LIMITATIONS_BOUNDARY,
            qualification_contract=self.contract("deadline"),
            bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "deadline_source"}],
            subject_links=self.subject(role="deadline_applies_to"),
            actor="admin",
            actor_role="administrator",
            idempotency_key="deadline-1",
            created_at=self.FIXED_CREATED_AT,
        )
        values.update(overrides)
        with patch.object(pt.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return pt.create_deadline(self.conn, **values)

    def event(self, parent_kind: str, parent_id: int, **overrides) -> dict:
        values = dict(
            event_category="extension_requested",
            actor_label="Participant",
            actor_capacity="Applicant",
            represented_date_or_period="2026-08-10",
            represented_value="request",
            rationale="Preserve request",
            qualification=pt.DEADLINE_BOUNDARY,
            limitations=pt.LIMITATIONS_BOUNDARY,
            declaration=None,
            bindings=self.source("extension_request_source"),
            actor="admin",
            actor_role="administrator",
            idempotency_key="event-1",
            created_at=self.FIXED_CREATED_AT,
        )
        values.update(overrides)
        with patch.object(pt.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return pt.record_event(self.conn, parent_kind=parent_kind, parent_id=parent_id, **values)

    def calculation(self, deadline_id: int, **overrides) -> dict:
        values = dict(
            calculation_mode="calendar_days_after_explicit_trigger",
            trigger_input="2026-08-01",
            interval_days=14,
            inclusivity="inclusive",
            calculated_as_of="2026-08-15T12:00:00Z",
            time_zone="UTC",
            requested_by="admin",
            idempotency_key="calc-1",
        )
        values.update(overrides)
        return pt.calculate_deadline(self.conn, deadline_id=deadline_id, **values)

    def pathway_link(self, **overrides) -> dict:
        observation = self.observation(key=overrides.pop("observation_key", "stage72-observation"), status="accepted")
        values = dict(
            source_object_kind="canonical_record",
            source_object_id=RECORD,
            target_object_kind="accepted_pattern_observation",
            target_object_id=str(observation["id"]),
            relationship_type="evidence_to_observation",
            rationale="Preserve the represented connection.",
            reliance_status="not_represented",
            reliance_description=None,
            reliance_declaration={"acknowledged": True, "status": "not_represented"},
            contestation_status="not_represented",
            contestation_representation=None,
            limitations=pathway.LIMITATIONS_BOUNDARY,
            bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "relationship_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key="stage72-1",
        )
        values.update(overrides)
        with patch.object(pathway.allegations, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return pathway.create_pathway_link(self.conn, **values)

    def raw_pathway_link(self, *, source_kind: str, source_id: str, target_kind: str, target_id: str,
                          relationship_type: str = "evidence_to_observation",
                          reliance_status: str = "considered", idempotency_key: str = "raw-link-1") -> int:
        pathway.ensure_pathway_tables(self.conn)
        cursor = self.conn.execute(
            "INSERT INTO record_governed_pathway_links "
            "(idempotency_key,schema_version,authoring_mode,source_object_kind,source_object_id,"
            "target_object_kind,target_object_id,relationship_type,rationale,reliance_status,"
            "reliance_description,reliance_declaration_json,contestation_status,"
            "contestation_representation,limitations,qualification_contract_json,status,"
            "created_by,created_by_role,created_at,request_payload_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                idempotency_key, pathway.SCHEMA_VERSION, "human_recorded", source_kind, source_id,
                target_kind, target_id, relationship_type, "Preserve the represented connection.",
                reliance_status, "Described reliance.", "{}", "not_represented", None,
                pathway.LIMITATIONS_BOUNDARY, "{}", "recorded", "admin", "administrator",
                "2026-08-28T00:00:00Z", "{}",
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def project(self, reference: str = RECORD, **kwargs) -> dict:
        return projection.project_pathway(self.conn, reference, **kwargs)

    def _ensure_associations(self) -> None:
        associations.ensure_association_tables(self.conn)
        if self.conn.execute("SELECT 1 FROM record_document_associations WHERE id=6201").fetchone():
            return
        self.conn.executemany(
            """INSERT INTO record_document_associations
               (id, public_reference, record_reference, document_id,
                relationship_type, public_label, is_active, is_public,
                created_at, created_by, updated_at, updated_by)
               VALUES (?, ?, ?, ?, 'supporting_document', 'Supporting document',
                       1, 1, ?, 'admin', ?, 'admin')""",
            [
                (6201, "ASSOC-78A-1", RECORD, "doc-1", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"),
                (6202, "ASSOC-78A-2", RECORD, "doc-2", "2026-08-02T00:00:00Z", "2026-08-02T00:00:00Z"),
                (6203, "ASSOC-78A-O1", OTHER_RECORD, "doc-3", "2026-08-03T00:00:00Z", "2026-08-03T00:00:00Z"),
                (6204, "ASSOC-78A-O2", OTHER_RECORD, "doc-4", "2026-08-04T00:00:00Z", "2026-08-04T00:00:00Z"),
            ],
        )
        self.conn.commit()

    def observation(self, record: str = RECORD, key: str = "obs-1", status: str | None = None) -> dict:
        self._ensure_associations()
        item = observations.create_candidate_observation(
            self.conn,
            record_reference=record,
            relationship_type="supporting_document",
            actor="admin",
            actor_role="administrator",
            rationale="Record repeated governed relationship as observation only.",
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )
        if status and status != "candidate":
            item = observations.review_observation(
                self.conn,
                item["id"],
                status=status,
                actor="reviewer",
                actor_role="administrator",
                rationale="Review observation status only.",
                reviewed_at="2026-08-28T01:00:00Z",
            )
        return item

    def inference(self, *, record: str = RECORD, key: str = "inf-1", status: str | None = None) -> dict:
        item = inferences.create_inference(
            self.conn,
            inference_type="procedural",
            proposition="A sequence may support a procedural inference.",
            rationale="Preserve qualified inference only.",
            qualification="Qualified inference; not evidence, fact or determination.",
            qualification_contract={
                "epistemic_label": "inference",
                "source_basis_present": True,
                "alternatives_possible": True,
                "not_evidence": True,
                "not_determination": True,
                "limitations": "Contrary sources and alternatives remain possible.",
            },
            bindings=[
                {"source_type": "canonical_record", "source_id": record, "binding_role": "primary_support"},
                {"source_type": "canonical_record", "source_id": record, "binding_role": "contrary_evidence"},
            ],
            actor="author",
            actor_role="administrator",
            author_declaration={"acknowledged": True},
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )
        if status:
            item = inferences.review_inference(
                self.conn,
                item["id"],
                status=status,
                rationale="Review inference boundary only.",
                qualification_assessment={
                    "within_stage63_boundary": True,
                    "qualification_adequate": True,
                    "no_prohibited_class_asserted": True,
                },
                prohibited_class_assessment={
                    "within_stage63_boundary": True,
                    "qualification_adequate": True,
                    "no_prohibited_class_asserted": True,
                },
                contrary_evidence_note="Contrary material remains visible.",
                actor="reviewer",
                actor_role="administrator",
                reviewed_at="2026-08-28T01:00:00Z",
                idempotency_key=f"{key}-review",
            )
        return item

    def allegation(self, *, record: str = RECORD, key: str = "alg-1", status: str | None = None) -> dict:
        item = allegations.create_allegation(
            self.conn,
            allegation_category="reported_conduct",
            allegation_text="The source reported delayed handling.",
            representation_mode="faithful_paraphrase",
            representation_contract={"human_verified": True, "faithful_representation": True},
            attributed_source_label="Reporting source",
            attribution_context="Written source represented in the governed record.",
            subject_label="Administrative unit",
            alleged_period="2026-08",
            made_or_recorded_at="2026-08-12T00:00:00Z",
            rationale="Preserve allegation without deciding truth.",
            qualification="Attributed allegation only.",
            limitations="The allegation may remain disputed or unresolved.",
            qualification_contract={
                "epistemic_label": "allegation",
                "attribution_present": True,
                "source_basis_present": True,
                "not_evidence": True,
                "not_observation": True,
                "not_inference": True,
                "not_determination": True,
                "not_confirmation": True,
                "alternatives_possible": True,
                "limitations": "The allegation may remain disputed or unresolved.",
            },
            bindings=[{"source_type": "canonical_record", "source_id": record, "binding_role": "attribution_source"}],
            actor="author",
            actor_role="administrator",
            author_declaration={"acknowledged": True},
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )
        if status and status in allegations.REVIEW_DISPOSITIONS:
            item = allegations.review_allegation(
                self.conn,
                item["id"],
                disposition=status,
                rationale="Review attribution and representation only.",
                boundary_declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                reviewed_at="2026-08-28T01:00:00Z",
                idempotency_key=f"{key}-review",
            )
        return item

    def response(self, *, allegation_id: int | None = None, record: str = RECORD,
                 key: str = "rsp-1", category: str = "substantive_response") -> dict:
        if allegation_id is None:
            allegation_id = int(self.allegation()["id"])
        rep = {"human_verified": True, "faithful_representation": True}
        if category == "express_declination":
            rep["express_declination_source"] = True
        return responses.create_response(
            self.conn,
            allegation_id=allegation_id,
            response_category=category,
            response_text="The respondent provided a bounded response.",
            representation_mode="faithful_paraphrase",
            representation_contract=rep,
            attributed_respondent_label="Respondent organisation",
            attribution_context="Governed response source.",
            subject_label="Administrative unit",
            respondent_capacity="representative",
            response_period=None,
            recorded_at="2026-08-18",
            notice_details=None,
            rationale="Preserve response without resolving the allegation.",
            qualification="Response only; not resolution.",
            limitations="A response may coexist with the allegation.",
            qualification_contract={
                "epistemic_label": "response",
                "attribution_present": True,
                "source_basis_present": True,
                "not_evidence": True,
                "not_observation": True,
                "not_inference": True,
                "not_determination": True,
                "not_confirmation": True,
                "not_resolution": True,
                "not_admission": True,
                "alternatives_possible": True,
                "limitations": "A response may coexist with the allegation.",
            },
            bindings=[{"source_type": "canonical_record", "source_id": record, "binding_role": "response_source"}],
            recorder_declaration={"acknowledged": True},
            actor="author",
            actor_role="administrator",
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )

    def review_response(self, response_id: int, *, status: str, key: str) -> dict:
        return responses.review_response(
            self.conn,
            response_id,
            disposition=status,
            rationale="Review response attribution only.",
            boundary_declaration={"acknowledged": True},
            actor="reviewer",
            actor_role="administrator",
            reviewed_at="2026-08-28T01:00:00Z",
            idempotency_key=key,
        )

    def withdraw_response(self, response_id: int, *, key: str) -> dict:
        return responses.withdraw_response(
            self.conn,
            response_id,
            withdrawal_type="attributed_respondent_withdrawal",
            rationale="Withdrawal preserved as represented.",
            withdrawal_bindings=[
                {"source_type": "canonical_record", "source_id": RECORD, "binding_role": "withdrawal_source"}
            ],
            actor="reviewer",
            actor_role="administrator",
            occurred_at="2026-08-28T02:00:00Z",
            idempotency_key=key,
        )

    def supersede_response(self, response_id: int, replacement_response_id: int, *, key: str) -> dict:
        return responses.supersede_response(
            self.conn,
            response_id,
            replacement_response_id=replacement_response_id,
            rationale="Replacement response preserves later representation.",
            actor="reviewer",
            actor_role="administrator",
            occurred_at="2026-08-28T02:00:00Z",
            idempotency_key=key,
        )

    def characterisation(self, *, primary_kind: str = "canonical_record", primary_id: str = RECORD,
                         key: str = "char-1", status: str | None = None,
                         references: list[dict[str, str]] | None = None) -> dict:
        item = characterisations.create_characterisation(
            self.conn,
            term_code="procedural_obstruction",
            vocabulary_version=characterisations.VOCABULARY_VERSION,
            representation_mode="faithful_paraphrase",
            represented_wording="The source used procedural obstruction language.",
            attribution_kind="identified_institution",
            attributed_label="Reporting source",
            attribution_source_type=None,
            attribution_source_id=None,
            external_source_description=None,
            epistemic_basis="proposed_human_characterisation",
            rationale="Preserve terminology without making a finding.",
            limitations=characterisations.QUALIFICATION,
            jurisdictional_context=None,
            primary_object_kind=primary_kind,
            primary_object_id=primary_id,
            bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "supporting_source"}],
            references=references or [],
            actor="author",
            actor_role="administrator",
            declaration={"acknowledged": True},
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )
        if status == "withdrawn":
            item = characterisations.withdraw_characterisation(
                self.conn,
                identifier=item["id"],
                rationale="Withdrawn as represented.",
                declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                idempotency_key=f"{key}-withdraw",
            )
        elif status == "reviewed_as_qualified_representation":
            item = characterisations.propose_characterisation(
                self.conn,
                identifier=item["id"],
                rationale="Proposed for review as represented.",
                declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                idempotency_key=f"{key}-propose",
            )
            item = characterisations.review_characterisation(
                self.conn,
                identifier=item["id"],
                outcome=status,
                rationale="Review representation only.",
                declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                idempotency_key=f"{key}-review",
            )
        return item

    def authority_contract(self) -> dict[str, object]:
        return {
            "epistemic_label": "authority",
            "source_basis_present": True,
            "not_conferral": True,
            "not_appointment_validation": True,
            "not_jurisdiction": True,
            "not_lawfulness": True,
            "not_determination": True,
            "alternatives_possible": True,
        }

    def determination_contract(self) -> dict[str, object]:
        return {
            "epistemic_label": "determination",
            "source_basis_present": True,
            "not_validation": True,
            "not_jurisdiction": True,
            "not_lawfulness": True,
            "not_correctness": True,
            "not_enforceability": True,
            "not_finality": True,
        }

    def challenge_contract(self) -> dict[str, object]:
        return {
            "epistemic_label": "challenge_proceeding",
            "source_basis_present": True,
            "target_determination_present": True,
            "not_suspension": True,
            "not_reversal": True,
            "not_legal_effect": True,
        }

    def mandate_payload(self, *, key_suffix: str = "1", **overrides) -> dict[str, object]:
        values = dict(
            mandate_basis_category="governance_instrument",
            title_label=f"Review mandate {key_suffix}",
            subject_matter_scope="governed records",
            procedural_scope="decision recording",
            territorial_organisational_scope="CDE",
            affected_class="canonical record",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
            express_limitations="No legal validation is established.",
            conditions_prerequisites="Source-backed representation only.",
            delegation_status="not_delegated",
            rationale="Preserve the represented mandate.",
            qualification="Source-backed mandate representation.",
            limitations="Mandate record does not prove jurisdiction or legality.",
            created_at=self.FIXED_CREATED_AT,
        )
        values.update(overrides)
        return values

    def authority(self, *, record: str = RECORD, key: str = "auth-1",
                  review: bool = True, mandate_overrides: dict | None = None,
                  holder_label: str = "Review office") -> dict:
        item = authorities.create_authority(
            self.conn,
            holder_kind="office",
            holder_label=holder_label,
            institution_context="Civic institution",
            office_role_capacity="Administrative review office",
            named_holder=None,
            holder_effective_period="2026-01-01/2026-12-31",
            attribution_context="Source-backed authority representation.",
            rationale="Preserve authority representation only.",
            qualification="Authority record only.",
            limitations="Authority is not legally validated by this record.",
            qualification_contract=self.authority_contract(),
            recorder_declaration={"acknowledged": True},
            bindings=[{"source_type": "canonical_record", "source_id": record, "binding_role": "authority_basis_source"}],
            mandate=self.mandate_payload(key_suffix=key, **(mandate_overrides or {})),
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
            mandate_idempotency_key=f"{key}-mandate",
            created_at=self.FIXED_CREATED_AT,
        )
        if review:
            item = authorities.review_authority(
                self.conn,
                authority_id=item["id"],
                mandate_id=None,
                disposition="accepted_as_source_backed_authority_record",
                rationale="Accept as source-backed authority record only.",
                boundary_declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                reviewed_at="2026-08-28T01:00:00Z",
                idempotency_key=f"{key}-review",
            )
            item = authorities.review_authority(
                self.conn,
                authority_id=item["id"],
                mandate_id=item["mandates"][0]["id"],
                disposition="accepted_as_source_backed_authority_record",
                rationale="Accept as source-backed mandate record only.",
                boundary_declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                reviewed_at="2026-08-28T01:01:00Z",
                idempotency_key=f"{key}-mandate-review",
            )
        return item

    def determination(self, *, record: str = RECORD, key: str = "det-1",
                      authority_item: dict | None = None,
                      governed_objects: list[dict[str, object]] | None = None,
                      reasons: str = "Reasons as represented by the source.",
                      reasons_status: str = "reasons_recorded",
                      decision_date: str | None = "2026-06-01",
                      category: str = "merits_determination") -> dict:
        authority_item = authority_item or self.authority(record=record, key=f"{key}-authority")
        authority_id = authority_item["id"]
        mandate_id = authority_item["mandates"][0]["id"]
        authority_decl = {"acknowledged": True}
        if reasons_status == "no_reasons_recorded_in_source":
            authority_decl["no_reasons_acknowledged"] = True
        return determinations.create_determination(
            self.conn,
            determination_category=category,
            title_label="Recorded determination",
            formal_outcome="Outcome as represented by source.",
            representation_mode="faithful_paraphrase",
            issues_determined="Issue as represented.",
            reasons=reasons,
            reasons_status=reasons_status,
            decision_date_or_period=decision_date,
            recorded_date="2026-06-02",
            affected_subject_or_class="Canonical record subject",
            finality_description="Finality as represented only.",
            implementation_or_remedy=None,
            qualification="Source-bound determination record.",
            limitations="Correctness and legal effect are not established.",
            qualification_contract=self.determination_contract(),
            authority_id=authority_id,
            mandate_id=mandate_id,
            authority_mandate_declaration=authority_decl,
            scope_declaration={"acknowledged": True},
            representation_declaration={"acknowledged": True, "mode": "faithful_paraphrase"},
            recorder_declaration={"acknowledged": True},
            bindings=[{"source_type": "canonical_record", "source_id": record, "binding_role": "determination_source"}],
            governed_objects=governed_objects or [],
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
            linking_declaration={"acknowledged": True},
        )

    def effect_event(self, determination_id: int, *, key: str = "effect-1",
                     event_type: str = "appeal_recorded") -> dict:
        return determinations.record_effect_event(
            self.conn,
            determination_id=determination_id,
            event_type=event_type,
            represented_date_or_period="2026-07-01",
            rationale="Effect event is source-recorded only.",
            qualification="Effect event does not determine legal effect.",
            effect_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "effect_event_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
            occurred_at="2026-08-28T02:00:00Z",
        )

    def challenge(self, *, determination_id: int | None = None,
                  authority_item: dict | None = None, record: str = RECORD,
                  key: str = "challenge-1") -> dict:
        if determination_id is None:
            determination_id = int(self.determination(key=f"{key}-det")["id"])
        authority_item = authority_item or self.authority(key=f"{key}-authority")
        return challenges.create_challenge(
            self.conn,
            challenge_form="appeal",
            title_label="Recorded challenge",
            target_determination_id=determination_id,
            applicant_label="Applicant",
            applicant_kind="natural_person",
            applicant_capacity="participant",
            reviewing_forum_label="Review forum",
            reviewing_authority_id=authority_item["id"],
            reviewing_mandate_id=authority_item["mandates"][0]["id"],
            grounds="Grounds as represented.",
            filing_date_or_period="2026-06-05",
            recorded_date="2026-06-06",
            affected_subject_or_proceeding="Proceeding as represented.",
            procedural_status_at_creation="filed_as_recorded",
            rationale="Preserve challenge without changing the determination.",
            limitations="Challenge does not invalidate, suspend, reverse or alter legal effect.",
            qualification_contract=self.challenge_contract(),
            recorder_declaration={"acknowledged": True},
            bindings=[{"source_type": "canonical_record", "source_id": record, "binding_role": "initiation_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )

    def challenge_event(self, challenge_id: int, *, key: str = "challenge-event-1",
                        event_type: str = "permission_requested") -> dict:
        return challenges.record_event(
            self.conn,
            challenge_id=challenge_id,
            event_type=event_type,
            event_description="Challenge event as represented.",
            event_date_or_period="2026-06-10",
            rationale="Preserve challenge event only.",
            event_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "procedural_event_source"}],
            boundary_declaration={"acknowledged": True},
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
        )

    def accepted_determination(self, *, record: str = RECORD, key: str = "accepted-det",
                               category: str = "merits_determination") -> dict:
        item = self.determination(record=record, key=key, category=category)
        return determinations.review_determination(
            self.conn,
            determination_id=item["id"],
            disposition="accepted_as_attributed_determination_record",
            rationale="Accept the attributed determination record only.",
            boundary_declaration={"acknowledged": True},
            actor="reviewer",
            actor_role="administrator",
            idempotency_key=f"{key}-review",
            reviewed_at="2026-08-28T01:00:00Z",
        )

    def remedy(self, *, determination_id: int | None = None, key: str = "remedy-1",
               category: str = "record_correction", status: str | None = None,
               performance_period: str | None = "2026-09-01/2026-09-30") -> dict:
        if determination_id is None:
            determination_id = int(self.accepted_determination(key=f"{key}-det")["id"])
        item = remedies.create_remedy(
            self.conn,
            remedy_category=category,
            direction_type="no_direction" if category == "no_remedy_directed" else "mandatory_direction",
            title_label="Recorded remedy",
            remedy_text="" if category == "no_remedy_directed" else "The source represents a directed remedy.",
            representation_mode="faithful_paraphrase",
            beneficiary_or_affected_party=None,
            obligated_party=None,
            amount=None,
            currency=None,
            performance_period_or_deadline=performance_period if category != "no_remedy_directed" else None,
            conditions_prerequisites="Condition as represented." if category != "no_remedy_directed" else None,
            scope="Remedy scope as represented." if category != "no_remedy_directed" else None,
            limitations=remedies.LIMITATIONS_BOUNDARY,
            implementation_description=None,
            rationale="Preserve remedy without deciding implementation.",
            qualification=remedies.QUALIFICATION_BOUNDARY,
            determination_id=determination_id,
            qualification_contract={
                "epistemic_label": "remedy_or_direction",
                "determination_link_present": True,
                "source_basis_present": True,
                "not_implementation": True,
                "not_compliance": True,
                "not_enforcement": True,
                "not_legal_effect": True,
            },
            author_declaration={"acknowledged": True},
            representation_declaration={"acknowledged": True},
            no_remedy_declaration={"acknowledged": True} if category == "no_remedy_directed" else None,
            bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "direction_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )
        if status:
            item = remedies.review_remedy(
                self.conn,
                remedy_id=item["id"],
                disposition=status,
                rationale="Review remedy representation only.",
                boundary_declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                idempotency_key=f"{key}-review",
                reviewed_at="2026-08-28T01:00:00Z",
            )
        return item

    def implementation_event(self, *, remedy_id: int | None = None, key: str = "implementation-1",
                             category: str = "implementation_reported",
                             status: str | None = None,
                             governed_objects: list[dict[str, object]] | None = None) -> dict:
        if remedy_id is None:
            remedy_id = int(self.remedy(key=f"{key}-remedy")["id"])
        basis = {
            "compliance_evidence_submitted": "documentary_submission",
            "verification_performed": "independent_verification_record",
            "implementation_completed_as_formally_determined": "formal_determination",
        }.get(category, "attributed_report")
        bindings = [{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "event_source"}]
        if category == "verification_performed":
            bindings.append({"source_type": "canonical_record", "source_id": RECORD, "binding_role": "verification_source"})
        if category == "deadline_extension_recorded":
            bindings.append({"source_type": "canonical_record", "source_id": RECORD, "binding_role": "extension_source"})
        item = implementation_events.create_implementation_event(
            self.conn,
            event_category=category,
            epistemic_basis=basis,
            title_label="Implementation event",
            event_description="A source represents an implementation or compliance event.",
            representation_mode="faithful_paraphrase",
            attributed_participant="Institution",
            represented_capacity="Respondent",
            represented_event_date_or_period="2026-10-01",
            recorded_date="2026-10-02",
            represented_amount_quantity_extent=None,
            represented_deadline_or_extension="Extended date as represented." if category == "deadline_extension_recorded" else None,
            verification_method="Document review" if category == "verification_performed" else None,
            verification_conclusion="verification_inconclusive" if category == "verification_performed" else None,
            rationale="Preserve event without deciding compliance.",
            qualification=implementation_events.QUALIFICATION_BOUNDARY,
            limitations=implementation_events.LIMITATIONS_BOUNDARY,
            qualification_contract={
                "epistemic_label": "implementation_or_compliance_event",
                "remedy_link_present": True,
                "source_basis_present": True,
                "not_implementation_verified": True,
                "not_compliance_status": True,
                "not_breach_finding": True,
                "not_legal_effect": True,
            },
            author_declaration={"acknowledged": True},
            representation_declaration={"acknowledged": True},
            conditional_declaration={"acknowledged": True, "category": category}
            if category in implementation_events.CONDITIONAL_DECLARATION_BOUNDARIES
            else None,
            remedy_id=remedy_id,
            bindings=bindings,
            governed_objects=governed_objects,
            actor="admin",
            actor_role="administrator",
            idempotency_key=key,
            created_at=self.FIXED_CREATED_AT,
        )
        if status:
            item = implementation_events.review_implementation_event(
                self.conn,
                event_id=item["id"],
                disposition=status,
                rationale="Review event representation only.",
                boundary_declaration={"acknowledged": True},
                actor="reviewer",
                actor_role="administrator",
                idempotency_key=f"{key}-review",
                reviewed_at="2026-08-28T01:00:00Z",
            )
        return item

    def publication(self, *, determination_id: int | None = None, key: str = "publication-1",
                    publish: bool = False) -> dict:
        if determination_id is None:
            determination_id = int(self.accepted_determination(key=f"{key}-det")["id"])
        publications.ensure_publication_tables(self.conn)
        with patch.object(publications, "utc_now", return_value=self.FIXED_CREATED_AT):
            item = publications.create_publication(
                self.conn,
                determination_id=determination_id,
                representation_mode="approved_summary",
                public_title="Determination publication",
                public_representation="A bounded public representation.",
                authority_representation="Authority as represented.",
                mandate_representation="Mandate as represented.",
                reasons_status="reasons_abridged_or_redacted",
                challenge_warning_status="no_linked_challenge_shown_in_snapshot",
                challenge_warning_text=publications.NO_LINKED_CHALLENGE_TEXT,
                current_effect_status="effect_uncertain",
                current_effect_rationale="Effect uncertain as represented.",
                effect_as_of="2026-10-15",
                supersession_representation="No supersession represented in this snapshot.",
                limitations="Publication does not establish endorsement or correctness.",
                redaction_notice="Redaction status preserved.",
                actor="admin",
                actor_role="administrator",
                idempotency_key=key,
            )
            if publish:
                common = {"publication_id": item["id"], "supporting_sources": [], "reviewer_role": "administrator"}
                item = publications.review_eligibility(self.conn, **common, status="eligible_for_review", rationale="Eligibility review only.", representation={"acknowledged": True, "human_recorded": True, "boundary": "eligibility_is_not_approval"}, reviewer=f"{key}-eligibility", idempotency_key=f"{key}-eligibility")
                item = publications.review_privacy(self.conn, **common, status="cleared_for_publication", rationale="Privacy review recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "privacy_is_not_clearance_of_all_risk"}, reviewer=f"{key}-privacy", idempotency_key=f"{key}-privacy")
                item = publications.review_redaction(self.conn, **common, status="cleared_for_publication", rationale="Redaction review recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "redaction_is_not_completeness"}, reviewer=f"{key}-redaction", idempotency_key=f"{key}-redaction")
                item = publications.inspect_authority(self.conn, **common, status="recorded_with_qualification", rationale="Authority inspected as represented.", representation={"acknowledged": True, "human_recorded": True, "boundary": "authority_is_not_legally_validated", "representation": "Authority as represented."}, reviewer=f"{key}-authority", idempotency_key=f"{key}-authority")
                item = publications.inspect_mandate(self.conn, **common, status="recorded_with_qualification", rationale="Mandate inspected as represented.", representation={"acknowledged": True, "human_recorded": True, "boundary": "mandate_is_not_legally_validated", "representation": "Mandate as represented."}, reviewer=f"{key}-mandate", idempotency_key=f"{key}-mandate")
                item = publications.record_publication_context(self.conn, **common, status="recorded", rationale="Publication context recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "publication_context_is_not_legal_effect", "reasons_status": "reasons_abridged_or_redacted", "challenge_warning_status": "no_linked_challenge_shown_in_snapshot", "challenge_warning_text": publications.NO_LINKED_CHALLENGE_TEXT, "current_effect_status": "effect_uncertain", "current_effect_rationale": "Effect uncertain as represented.", "effect_as_of": "2026-10-15", "supersession_representation": "No supersession represented in this snapshot.", "limitations": "Publication does not establish endorsement or correctness.", "redaction_notice": "Redaction status preserved."}, reviewer=f"{key}-context", idempotency_key=f"{key}-context")
                item = publications.approve_publication(self.conn, publication_id=item["id"], rationale="Approval recorded.", actor=f"{key}-approver", actor_role="administrator", idempotency_key=f"{key}-approve")
                item = publications.publish_publication(self.conn, publication_id=item["id"], rationale="Publication recorded.", actor=f"{key}-publisher", actor_role="administrator", idempotency_key=f"{key}-publish")
        return item

    @staticmethod
    def kinds(result: dict) -> list[str]:
        return [row["object_kind"] for row in result["rows"]]

    @staticmethod
    def rows_of(result: dict, kind: str) -> list[dict]:
        return [row for row in result["rows"] if row["object_kind"] == kind]

    @staticmethod
    def gap_codes(result: dict) -> set[str]:
        return {gap["gap_code"] for gap in result["gaps"]}


class Stage78APathwayProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = ProjectionFixture.fresh_connection()
        self.fixture = ProjectionFixture(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    # 1. Exact canonical-record root.
    def test_exact_canonical_record_root(self) -> None:
        result = self.fixture.project()
        self.assertEqual(result["projection_contract"], "stage78.pathway_projection.v1")
        self.assertEqual(result["record_reference"], RECORD)
        self.assertEqual(result["scope"]["root_object_kind"], "canonical_record")

    # 2. Unknown canonical record.
    def test_unknown_canonical_record_is_a_bounded_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_record_not_found"):
            self.fixture.project(reference="REC-MISSING")

    # 3. One linked notice.
    def test_one_linked_notice_projects_with_verbatim_category(self) -> None:
        notice = self.fixture.notice()
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_id"], str(notice["id"]))
        self.assertEqual(rows[0]["category"], "notice_issued")
        self.assertEqual(rows[0]["display_label"], "Notice issued · Notice")
        self.assertEqual(rows[0]["ownership_path"], "stage71.object_link(notice_concerns->canonical_record)")
        self.assertEqual(rows[0]["represented_time"], "2026-08-01")

    # 4. One linked deadline.
    def test_one_linked_deadline_projects(self) -> None:
        deadline = self.fixture.deadline()
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "procedural_deadline")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_id"], str(deadline["id"]))
        self.assertEqual(rows[0]["category"], "response_deadline")

    # 5. Evidenced receipt.
    def test_evidenced_receipt_is_a_distinct_category(self) -> None:
        self.fixture.notice(
            notice_category="notice_received_as_evidenced",
            bindings=self.fixture.source("receipt_source"),
            declaration={"acknowledged": True, "category": "notice_received_as_evidenced"},
        )
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual(rows[0]["category"], "notice_received_as_evidenced")
        self.assertEqual(rows[0]["display_label"], "Notice received as evidenced · Notice")
        self.assertNotIn("no_evidenced_receipt_notice_in_scope", self.fixture.gap_codes(result))

    # 6. Notice issued without evidenced receipt.
    def test_notice_issued_without_evidenced_receipt_never_becomes_receipt(self) -> None:
        self.fixture.notice()
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual(rows[0]["category"], "notice_issued")
        self.assertNotEqual(rows[0]["category"], "notice_received_as_evidenced")
        self.assertIn("no_evidenced_receipt_notice_in_scope", self.fixture.gap_codes(result))

    # 7. Receipt disputed.
    def test_receipt_disputed_remains_disputed(self) -> None:
        self.fixture.notice(
            notice_category="receipt_disputed",
            idempotency_key="notice-dispute",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_notice")[0]
        self.assertEqual(row["category"], "receipt_disputed")
        self.assertEqual(row["display_label"], "Receipt disputed · Notice")
        self.assertEqual(row["contestation"]["status"], "disputed_as_recorded")
        self.assertEqual(row["contestation"]["representation"], "receipt_disputed")

    # 8. Notice adequacy disputed must not become inadequate notice.
    def test_notice_adequacy_disputed_is_not_an_adverse_conclusion(self) -> None:
        self.fixture.notice(
            notice_category="notice_adequacy_disputed",
            idempotency_key="notice-adequacy",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_notice")[0]
        self.assertEqual(row["category"], "notice_adequacy_disputed")
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("inadequate notice", serialised)

    # 9. Extension event.
    def test_extension_event_is_append_only_child_row(self) -> None:
        deadline = self.fixture.deadline()
        self.fixture.event(
            "deadline",
            deadline["id"],
            event_category="extension_granted",
            represented_value="2026-08-20",
            bindings=self.fixture.source("extension_grant_source"),
            declaration={"acknowledged": True, "category": "extension_granted"},
        )
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "procedural_time_event")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "extension_granted")
        self.assertEqual(rows[0]["parent_kind"], "deadline")
        self.assertEqual(rows[0]["parent_id"], str(deadline["id"]))
        self.assertEqual(rows[0]["status"], "recorded")
        self.assertEqual(rows[0]["represented_time"], "2026-08-10")
        self.assertTrue(rows[0]["ownership_path"].startswith("stage71.parent(deadline)"))

    # 10. Deadline disputed.
    def test_deadline_disputed_event_remains_a_dispute(self) -> None:
        deadline = self.fixture.deadline()
        self.fixture.event(
            "deadline",
            deadline["id"],
            event_category="deadline_disputed",
            represented_value=None,
            bindings=self.fixture.source("dispute_source"),
            idempotency_key="event-dispute",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_time_event")[0]
        self.assertEqual(row["category"], "deadline_disputed")
        self.assertEqual(row["contestation"]["status"], "disputed_as_recorded")
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("invalid deadline", serialised)

    # 11. Deadline calculation.
    def test_deadline_calculation_projects_result_category_only(self) -> None:
        deadline = self.fixture.deadline()
        self.fixture.calculation(deadline["id"])
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "deadline_calculation")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "deadline_reached_as_calculated")
        self.assertIsNone(rows[0]["status"])
        self.assertEqual(rows[0]["chronology_basis"], "calculated_deadline")
        self.assertEqual(rows[0]["chronology_lower_bound"], "2026-08-15")
        self.assertEqual(rows[0]["limitations"], pt.CALCULATION_BOUNDARY)
        self.assertNotIn("no_governed_deadline_calculation", self.fixture.gap_codes(result))

    # 12. Late-filing allegation stays an allegation.
    def test_late_filing_alleged_stays_an_allegation(self) -> None:
        allegation = self.fixture.allegation(key="stage71-event-allegation")
        deadline = self.fixture.deadline()
        self.fixture.event(
            "deadline",
            deadline["id"],
            event_category="late_filing_alleged",
            represented_value="alleged late filing",
            bindings=self.fixture.source("determination_source"),
            subject_links=[
                {"object_type": "canonical_record", "object_id": RECORD, "relationship_role": "deadline_applies_to"},
                {"object_type": "governed_allegation", "object_id": str(allegation["id"]), "relationship_role": "dispute_concerns"},
            ],
            declaration={"acknowledged": True, "category": "late_filing_alleged"},
            idempotency_key="event-late",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_time_event")[0]
        self.assertEqual(row["category"], "late_filing_alleged")
        self.assertEqual(row["display_label"], "Late filing alleged · Participant")
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("filing was late", serialised)

    # 13. Formal late-filing determination link identifies without restating.
    def test_formal_determination_link_identifies_determination_only(self) -> None:
        determination = self.fixture.determination(key="stage71-formal-determination")
        determinations.review_determination(
            self.conn,
            determination_id=determination["id"],
            disposition="accepted_as_attributed_determination_record",
            rationale="Accept as attributed determination record only.",
            boundary_declaration={"acknowledged": True},
            actor="reviewer",
            actor_role="administrator",
            idempotency_key="stage71-formal-determination-review",
        )
        self.conn.execute(
            "UPDATE record_governed_determinations SET status='accepted_as_attributed_determination_record' WHERE id=?",
            (determination["id"],),
        )
        self.conn.commit()
        deadline = self.fixture.deadline()
        self.fixture.event(
            "deadline",
            deadline["id"],
            event_category="formal_late_filing_determination_linked",
            represented_value="determination linked",
            bindings=self.fixture.source("determination_source"),
            subject_links=[
                {"object_type": "canonical_record", "object_id": RECORD, "relationship_role": "deadline_applies_to"},
                {"object_type": "governed_determination", "object_id": str(determination["id"]), "relationship_role": "determination_addresses"},
            ],
            declaration={"acknowledged": True, "category": "formal_late_filing_determination_linked"},
            idempotency_key="event-formal",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_time_event")[0]
        self.assertEqual(row["category"], "formal_late_filing_determination_linked")
        self.assertIn(
            {
                "object_type": "governed_determination",
                "object_id": str(determination["id"]),
                "object_governed_identity": f"governed_determination:{determination['id']}",
                "relationship_role": "determination_addresses",
            },
            row["object_links"],
        )
        self.assertEqual(len(self.fixture.rows_of(result, "procedural_time_event")), 1)

    # 14. Direct Stage 72 root pathway link.
    def test_direct_stage72_root_pathway_link_is_included(self) -> None:
        self.fixture.pathway_link()
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "pathway_link")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "evidence_to_observation")
        self.assertEqual(rows[0]["ownership_path"], "stage72.endpoint(canonical_record=root)")
        self.assertEqual(rows[0]["reliance"], {"status": "not_represented", "description": None})
        self.assertEqual(rows[0]["chronology_basis"], "recording_time_only")

    # 15. Stage 72 link between two independently in-scope objects.
    def test_stage72_link_between_two_in_scope_stage71_objects(self) -> None:
        notice = self.fixture.notice()
        deadline = self.fixture.deadline()
        pathway.ensure_pathway_tables(self.conn)
        self.conn.execute(
            "INSERT INTO record_governed_pathway_bindings "
            "(pathway_link_id,source_type,source_id,binding_role) VALUES (1,'canonical_record',?,"
            "'relationship_source')",
            (RECORD,),
        )
        link_id = self.fixture.raw_pathway_link(
            source_kind="procedural_notice",
            source_id=str(notice["id"]),
            target_kind="procedural_deadline",
            target_id=str(deadline["id"]),
        )
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "pathway_link")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_id"], str(link_id))
        self.assertEqual(rows[0]["ownership_path"], "stage72.both_endpoints_in_stage78a_scope")

    # 16. Cross-record notice excluded.
    def test_cross_record_notice_is_excluded(self) -> None:
        self.fixture.notice(
            subject_links=self.fixture.subject(OTHER_RECORD),
            idempotency_key="notice-other",
        )
        result = self.fixture.project(RECORD)
        self.assertEqual(self.fixture.rows_of(result, "procedural_notice"), [])
        self.assertIn("no_governed_notice_linked", self.fixture.gap_codes(result))

    # 17. Cross-record deadline excluded.
    def test_cross_record_deadline_is_excluded(self) -> None:
        self.fixture.deadline(
            subject_links=self.fixture.subject(OTHER_RECORD, "deadline_applies_to"),
            bindings=[{"source_type": "canonical_record", "source_id": OTHER_RECORD, "binding_role": "deadline_source"}],
            idempotency_key="deadline-other",
        )
        result = self.fixture.project(RECORD)
        self.assertEqual(self.fixture.rows_of(result, "procedural_deadline"), [])
        self.assertIn("no_governed_deadline_linked", self.fixture.gap_codes(result))

    # 18. Pathway edge must not pull an unrelated object into scope.
    def test_pathway_edge_does_not_pull_unrelated_object_into_scope(self) -> None:
        notice = self.fixture.notice()
        self.fixture.raw_pathway_link(
            source_kind="procedural_notice",
            source_id=str(notice["id"]),
            target_kind="governed_remedy",
            target_id="999",
        )
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "pathway_link"), [])
        self.assertEqual(
            result["coverage"]["pathway_link_exclusion_reasons"],
            [{"reason": "endpoint_out_of_scope", "count": 1}],
        )
        self.assertNotIn("governed_remedy", {row["object_kind"] for row in result["rows"]})

    # 19. Superseded object retained as history.
    def test_superseded_object_is_retained_as_history(self) -> None:
        first = self.fixture.deadline()
        second = self.fixture.deadline(idempotency_key="deadline-2", title_label="Corrected deadline")
        pt.supersede_procedural_time(
            self.conn,
            target_kind="deadline",
            target_id=first["id"],
            replacement_kind="deadline",
            replacement_id=second["id"],
            rationale="Correction",
            actor="admin",
            actor_role="administrator",
            idempotency_key="sup-1",
        )
        result = self.fixture.project()
        deadlines = {row["object_id"]: row for row in self.fixture.rows_of(result, "procedural_deadline")}
        self.assertEqual(len(deadlines), 2)
        self.assertEqual(deadlines[str(first["id"])]["status"], "superseded")
        self.assertTrue(deadlines[str(first["id"])]["supersession"]["superseded"])
        self.assertEqual(
            deadlines[str(first["id"])]["supersession"]["replacement"]["replacement_governed_digest"],
            second["idempotency_key"],
        )
        self.assertEqual(deadlines[str(second["id"])]["status"], "recorded")

    # 20. Merely recorded object labelled verbatim.
    def test_merely_recorded_object_is_labelled_verbatim(self) -> None:
        self.fixture.notice()
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_notice")[0]
        self.assertEqual(row["status"], "recorded")
        self.assertNotEqual(row["status"], "accepted_procedural_record")
        pt.review_procedural_time(
            self.conn,
            target_kind="notice",
            target_id=int(row["object_id"]),
            disposition="accepted_as_source_bound_procedural_record",
            rationale="Preserve representation",
            boundary_declaration={"acknowledged": True},
            actor="admin",
            actor_role="administrator",
            idempotency_key="review-1",
        )
        reviewed = self.fixture.project()
        reviewed_row = self.fixture.rows_of(reviewed, "procedural_notice")[0]
        self.assertEqual(reviewed_row["status"], "accepted_procedural_record")
        self.assertEqual(len(reviewed_row["supersession"]["review_history"]), 1)

    # 21. Exact-date ordering.
    def test_exact_date_ordering_is_deterministic(self) -> None:
        self.fixture.notice(issue_date_or_period="2026-08-05", idempotency_key="notice-later")
        self.fixture.notice(issue_date_or_period="2026-08-01", idempotency_key="notice-earlier")
        result = self.fixture.project()
        notices = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual([row["represented_time"] for row in notices], ["2026-08-01", "2026-08-05"])
        self.assertTrue(all(row["chronology_precision"] == "exact_date" for row in notices))
        self.assertEqual(
            [row["ordering_relation"] for row in notices], ["determinate", "determinate"]
        )

    # 22. Month/year precision.
    def test_month_and_year_precision_become_intervals(self) -> None:
        # The Stage 71 producer only accepts exact dates, timestamps and explicit
        # periods, so degraded precision values are represented here by setting
        # the stored column directly.  The projection must derive interval
        # bounds without rewriting the source value.
        month = self.fixture.notice(idempotency_key="notice-month")
        year = self.fixture.notice(issue_date_or_period=None, idempotency_key="notice-year")
        self.conn.execute(
            "UPDATE record_governed_procedural_notices SET issue_date_or_period='2026-08' WHERE id=?",
            (month["id"],),
        )
        self.conn.execute(
            "UPDATE record_governed_procedural_notices SET issue_date_or_period='2026' WHERE id=?",
            (year["id"],),
        )
        self.conn.commit()
        result = self.fixture.project()
        notices = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual(
            sorted(row["represented_time"] for row in notices), ["2026", "2026-08"]
        )
        month = next(row for row in notices if row["represented_time"] == "2026-08")
        year = next(row for row in notices if row["represented_time"] == "2026")
        self.assertEqual(month["chronology_precision"], "month")
        self.assertEqual(month["chronology_lower_bound"], "2026-08-01")
        self.assertEqual(month["chronology_upper_bound"], "2026-08-31")
        self.assertEqual(year["chronology_precision"], "year")
        self.assertEqual(year["chronology_lower_bound"], "2026-01-01")
        self.assertEqual(year["chronology_upper_bound"], "2026-12-31")
        self.assertLess(year["chronology_lower_bound"], month["chronology_lower_bound"])

    # 23. Overlapping periods marked indeterminate.
    def test_overlapping_periods_are_marked_indeterminate(self) -> None:
        self.fixture.notice(issue_date_or_period="2026-08-01/2026-08-20", idempotency_key="notice-a")
        self.fixture.notice(issue_date_or_period="2026-08-10/2026-08-30", idempotency_key="notice-b")
        result = self.fixture.project()
        notices = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual(len(notices), 2)
        for row in notices:
            self.assertEqual(row["chronology_precision"], "period")
            self.assertEqual(row["ordering_relation"], "indeterminate")
        self.assertEqual(
            [row["chronology_lower_bound"] for row in notices], ["2026-08-01", "2026-08-10"]
        )

    # 24. Missing represented date uses recording-time label only.
    def test_missing_represented_date_uses_recording_time_label_only(self) -> None:
        self.fixture.notice(issue_date_or_period=None, idempotency_key="notice-undated")
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "procedural_notice")[0]
        self.assertIsNone(row["represented_time"])
        self.assertEqual(row["chronology_basis"], "unavailable")
        self.assertEqual(row["chronology_precision"], "unavailable")
        self.assertIsNone(row["chronology_lower_bound"])
        self.assertIsNone(row["chronology_upper_bound"])
        self.assertEqual(row["ordering_relation"], "indeterminate")
        serialised = json.dumps(row, ensure_ascii=False).casefold()
        self.assertNotIn("occurred at", serialised)

    # 25. Same-time deterministic tie.
    def test_same_time_rows_keep_deterministic_presentation_order(self) -> None:
        self.fixture.notice(issue_date_or_period="2026-08-01", idempotency_key="notice-aaa")
        deadline = self.fixture.deadline(deadline_date_or_period="2026-08-01", idempotency_key="deadline-zzz")
        result = self.fixture.project()
        dated = [row for row in result["rows"] if row["chronology_lower_bound"] == "2026-08-01"]
        self.assertEqual(len(dated), 2)
        self.assertEqual(dated[0]["object_kind"], "procedural_notice")
        self.assertEqual(dated[1]["object_kind"], "procedural_deadline")
        self.assertEqual(dated[1]["object_id"], str(deadline["id"]))
        self.assertEqual({row["ordering_relation"] for row in dated}, {"indeterminate"})
        again = self.fixture.project()
        self.assertEqual(
            [row["object_id"] for row in again["rows"]], [row["object_id"] for row in result["rows"]]
        )

    # 26. Sparse physical IDs.
    def test_sparse_physical_ids_do_not_affect_ordering(self) -> None:
        self.fixture.notice(issue_date_or_period="2026-08-01", idempotency_key="notice-1")
        self.fixture.notice(issue_date_or_period="2026-08-02", idempotency_key="notice-2")
        self.fixture.notice(issue_date_or_period="2026-08-03", idempotency_key="notice-3")
        self.conn.execute("DELETE FROM record_governed_procedural_notices WHERE id=2")
        self.conn.commit()
        result = self.fixture.project()
        notices = self.fixture.rows_of(result, "procedural_notice")
        self.assertEqual([row["object_id"] for row in notices], ["1", "3"])
        self.assertEqual(
            [row["represented_time"] for row in notices], ["2026-08-01", "2026-08-03"]
        )

    # 27. Different insertion order, identical projection digest.
    def test_different_insertion_order_yields_identical_digest(self) -> None:
        def build(order: str) -> dict:
            conn = ProjectionFixture.fresh_connection()
            fixture = ProjectionFixture(conn)
            if order == "notices-first":
                fixture.notice(issue_date_or_period="2026-08-01", idempotency_key="notice-a")
                fixture.notice(issue_date_or_period="2026-08-02", idempotency_key="notice-b")
                fixture.deadline(idempotency_key="deadline-a")
            else:
                fixture.deadline(idempotency_key="deadline-a")
                fixture.notice(issue_date_or_period="2026-08-02", idempotency_key="notice-b")
                fixture.notice(issue_date_or_period="2026-08-01", idempotency_key="notice-a")
            result = fixture.project()
            conn.close()
            return result

        first = build("notices-first")
        second = build("deadline-first")
        self.assertEqual(first["projection_digest"], second["projection_digest"])
        self.assertEqual(
            [row["represented_time"] for row in first["rows"]],
            [row["represented_time"] for row in second["rows"]],
        )

    def test_pathway_endpoint_physical_ids_do_not_affect_digest(self) -> None:
        def build(order: str) -> dict:
            conn = ProjectionFixture.fresh_connection()
            fixture = ProjectionFixture(conn)
            if order == "notice-first":
                notice = fixture.notice(idempotency_key="notice-stable")
                deadline = fixture.deadline(idempotency_key="deadline-stable")
            else:
                fixture.notice(idempotency_key="notice-placeholder")
                fixture.conn.execute("DELETE FROM record_governed_procedural_notices WHERE id=1")
                fixture.conn.commit()
                deadline = fixture.deadline(idempotency_key="deadline-stable")
                notice = fixture.notice(idempotency_key="notice-stable")
            fixture.raw_pathway_link(
                source_kind="procedural_notice",
                source_id=str(notice["id"]),
                target_kind="procedural_deadline",
                target_id=str(deadline["id"]),
                idempotency_key="pathway-stable",
            )
            result = fixture.project()
            conn.close()
            return result

        first = build("notice-first")
        second = build("deadline-first")
        self.assertNotEqual(
            self.fixture.rows_of(first, "pathway_link")[0]["object_links"],
            self.fixture.rows_of(second, "pathway_link")[0]["object_links"],
        )
        self.assertEqual(first["projection_digest"], second["projection_digest"])

    def test_event_parent_governed_identity_changes_digest(self) -> None:
        first_deadline = self.fixture.deadline(idempotency_key="deadline-parent-a")
        second_deadline = self.fixture.deadline(idempotency_key="deadline-parent-b")
        self.fixture.event(
            "deadline",
            first_deadline["id"],
            event_category="extension_granted",
            represented_value="2026-08-20",
            bindings=self.fixture.source("extension_grant_source"),
            declaration={"acknowledged": True, "category": "extension_granted"},
            idempotency_key="event-parent",
        )
        before = self.fixture.project()
        self.conn.execute(
            "UPDATE record_governed_procedural_time_events SET parent_id=? WHERE id=1",
            (second_deadline["id"],),
        )
        self.conn.commit()
        after = self.fixture.project()
        self.assertNotEqual(before["projection_digest"], after["projection_digest"])
        event = self.fixture.rows_of(after, "procedural_time_event")[0]
        self.assertEqual(event["parent_governed_identity"], "deadline:deadline-parent-b")

    # 28. Changed category changes digest.
    def test_changed_category_changes_digest(self) -> None:
        self.fixture.notice()
        before = self.fixture.project()
        self.conn.execute(
            "UPDATE record_governed_procedural_notices SET notice_category='notice_dispatched' WHERE id=1"
        )
        self.conn.commit()
        after = self.fixture.project()
        self.assertNotEqual(before["projection_digest"], after["projection_digest"])
        self.assertEqual(
            self.fixture.rows_of(after, "procedural_notice")[0]["category"], "notice_dispatched"
        )

    # 29. Changed status/review changes digest.
    def test_changed_review_changes_status_and_digest(self) -> None:
        notice = self.fixture.notice()
        before = self.fixture.project()
        pt.review_procedural_time(
            self.conn,
            target_kind="notice",
            target_id=notice["id"],
            disposition="accepted_as_source_bound_procedural_record",
            rationale="Preserve representation",
            boundary_declaration={"acknowledged": True},
            actor="admin",
            actor_role="administrator",
            idempotency_key="review-1",
        )
        after = self.fixture.project()
        self.assertNotEqual(before["projection_digest"], after["projection_digest"])
        self.assertEqual(
            self.fixture.rows_of(after, "procedural_notice")[0]["status"],
            "accepted_procedural_record",
        )

    # 30. Changed event or calculation changes digest.
    def test_changed_event_changes_digest(self) -> None:
        deadline = self.fixture.deadline()
        before = self.fixture.project()
        self.fixture.event(
            "deadline",
            deadline["id"],
            event_category="extension_requested",
            bindings=self.fixture.source("extension_request_source"),
            idempotency_key="event-2",
        )
        after = self.fixture.project()
        self.assertNotEqual(before["projection_digest"], after["projection_digest"])
        self.assertEqual(len(self.fixture.rows_of(after, "procedural_time_event")), 1)

    # 31. Missing notice gap phrased within scope.
    def test_missing_notice_gap_is_phrased_within_scope(self) -> None:
        result = self.fixture.project()
        gap = next(gap for gap in result["gaps"] if gap["gap_code"] == "no_governed_notice_linked")
        self.assertEqual(gap["scope_root"], RECORD)
        self.assertEqual(gap["object_category"], "procedural_notice")
        self.assertIn("object_link", gap["binding_mechanism"])
        self.assertIn("within the Stage 78A scope", gap["statement"])
        self.assertIn("No governed notice record was found", gap["statement"])

    # 32. Missing receipt-evidence gap phrased within scope.
    def test_missing_receipt_evidence_gap_is_phrased_within_scope(self) -> None:
        self.fixture.notice()
        result = self.fixture.project()
        gap = next(
            gap for gap in result["gaps"] if gap["gap_code"] == "no_evidenced_receipt_notice_in_scope"
        )
        self.assertEqual(gap["lifecycle_filters"], "notice_category=notice_received_as_evidenced")
        self.assertIn("No evidenced-receipt notice was found within this projection scope", gap["statement"])

    # 33. No prohibited non-occurrence statement.
    def test_no_prohibited_non_occurrence_statement(self) -> None:
        self.fixture.notice()
        self.fixture.deadline()
        result = self.fixture.project()
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        for phrase in PROHIBITED_PHRASES:
            self.assertNotIn(phrase, serialised)

    # 34. Reopen determinism.
    def test_reopen_determinism_with_file_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage78a.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            ProjectionFixture.seed_records(conn)
            fixture = ProjectionFixture(conn)
            fixture.notice()
            fixture.deadline()
            conn.commit()
            conn.close()
            first = projection.project_pathway(path, RECORD)
            second = projection.project_pathway(str(path), RECORD)
            self.assertEqual(first["projection_digest"], second["projection_digest"])

    # 35. Schema absent.
    def test_schema_absent_is_a_bounded_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.db"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "governed_pathway_projection_records_table_absent"):
                projection.project_pathway(path, RECORD)

    # 36. Partial Stage 71 schema.
    def test_partial_stage71_schema_is_a_bounded_error(self) -> None:
        self.conn.execute(
            "CREATE TABLE record_governed_procedural_notices (id INTEGER PRIMARY KEY, status TEXT)"
        )
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_stage71_schema_incomplete"):
            self.fixture.project()

    # 37. Partial Stage 72 schema.
    def test_partial_stage72_schema_is_a_bounded_error(self) -> None:
        self.conn.execute(
            "CREATE TABLE record_governed_pathway_links (id INTEGER PRIMARY KEY, status TEXT)"
        )
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_stage72_schema_incomplete"):
            self.fixture.project()

    # 38. Repeated projection remains non-mutating.
    def test_repeated_projection_remains_non_mutating(self) -> None:
        self.fixture.notice()
        self.fixture.deadline()
        self.fixture.pathway_link()
        snapshot_before = self._snapshot()
        first = self.fixture.project()
        second = self.fixture.project()
        self.assertEqual(first["projection_digest"], second["projection_digest"])
        self.assertEqual(snapshot_before, self._snapshot())

    def test_projection_performs_no_ddl_or_writes_on_connection(self) -> None:
        self.fixture.notice()
        self.fixture.deadline()
        schema_before = {
            row[0] for row in self.conn.execute("SELECT name FROM sqlite_master").fetchall()
        }
        counts_before = self._table_counts()
        self.fixture.project()
        schema_after = {
            row[0] for row in self.conn.execute("SELECT name FROM sqlite_master").fetchall()
        }
        self.assertEqual(schema_before, schema_after)
        self.assertEqual(counts_before, self._table_counts())
        self.assertNotIn("record_governed_pathway_projection", schema_after)

    def test_file_database_bytes_unchanged_and_pragma_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readonly.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            ProjectionFixture.seed_records(conn)
            fixture = ProjectionFixture(conn)
            fixture.notice()
            conn.commit()
            conn.close()
            digest_before = _file_sha256(path)
            projection.project_pathway(path, RECORD)
            self.assertEqual(digest_before, _file_sha256(path))
            check = sqlite3.connect(path)
            self.assertEqual(check.execute("PRAGMA query_only").fetchone()[0], 0)
            check.close()

    def test_empty_stage71_and_stage72_schemas_project_with_gaps_only(self) -> None:
        result = self.fixture.project()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["coverage"]["stage71_schema_present"], False)
        self.assertEqual(result["coverage"]["stage72_schema_present"], False)
        self.assertIn("no_governed_notice_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_deadline_linked", self.fixture.gap_codes(result))

    def test_cross_record_pathway_endpoint_is_excluded(self) -> None:
        self.fixture.raw_pathway_link(
            source_kind="canonical_record",
            source_id=RECORD,
            target_kind="canonical_record",
            target_id=OTHER_RECORD,
        )
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "pathway_link"), [])
        self.assertEqual(
            result["coverage"]["pathway_link_exclusion_reasons"],
            [{"reason": "cross_record_endpoint", "count": 1}],
        )

    def test_pathway_reliance_statuses_remain_distinct(self) -> None:
        self.fixture.pathway_link(
            reliance_status="expressly_relied_upon",
            reliance_description="Expressly relied upon in the stated reasons.",
            reliance_declaration={"acknowledged": True, "status": "expressly_relied_upon"},
            idempotency_key="stage72-relied",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "pathway_link")[0]
        self.assertEqual(row["reliance"]["status"], "expressly_relied_upon")
        self.assertNotEqual(row["reliance"]["status"], "considered")
        self.assertNotEqual(row["reliance"]["status"], "not_represented")

    def test_as_of_is_returned_when_supplied_and_excluded_from_digest(self) -> None:
        self.fixture.notice()
        without_as_of = self.fixture.project()
        with_as_of = self.fixture.project(as_of="2026-08-28T12:00:00Z")
        self.assertNotIn("generated_as_of", without_as_of)
        self.assertEqual(with_as_of["generated_as_of"], "2026-08-28T12:00:00Z")
        self.assertEqual(without_as_of["projection_digest"], with_as_of["projection_digest"])

    def test_blank_record_reference_is_a_bounded_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_record_reference_required"):
            projection.project_pathway(self.conn, "  ")

    def test_padded_record_reference_is_not_normalized_into_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_record_not_found"):
            projection.project_pathway(self.conn, f" {RECORD} ")

    def test_missing_database_file_is_a_bounded_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_database_unavailable"):
            projection.project_pathway("/nonexistent/stage78a.db", RECORD)

    def test_rows_use_the_closed_row_contract(self) -> None:
        self.fixture.notice()
        self.fixture.deadline()
        deadline = self.fixture.deadline(idempotency_key="deadline-2")
        self.fixture.event("deadline", deadline["id"])
        self.fixture.calculation(deadline["id"])
        self.fixture.pathway_link()
        result = self.fixture.project()
        expected = {
            "object_kind", "object_id", "parent_kind", "parent_id", "category", "status",
            "parent_governed_identity", "represented_time", "recorded_at",
            "chronology_basis", "chronology_precision", "chronology_lower_bound",
            "chronology_upper_bound", "ordering_relation", "ownership_path",
            "source_bindings", "object_links", "contestation", "supersession",
            "governed_digest", "display_label", "limitations", "reliance",
            "epistemic_label", "attribution", "representation_mode",
            "review_state", "contrary_sources", "does_not_establish",
        }
        self.assertTrue(result["rows"])
        for row in result["rows"]:
            self.assertEqual(set(row), expected)

    def test_stage78_projection_version_and_new_gap_rows(self) -> None:
        observations.ensure_observation_tables(self.conn)
        inferences.ensure_inference_tables(self.conn)
        allegations.ensure_allegation_tables(self.conn)
        responses.ensure_response_tables(self.conn)
        characterisations.ensure_characterisation_tables(self.conn)
        result = self.fixture.project()
        self.assertEqual(result["projection_version"], "78a2b2")
        self.assertEqual(result["coverage"]["stage62_schema_present"], True)
        self.assertEqual(result["coverage"]["stage63_schema_present"], True)
        self.assertEqual(result["coverage"]["stage64_schema_present"], True)
        self.assertEqual(result["coverage"]["stage65_schema_present"], True)
        self.assertEqual(result["coverage"]["stage74_schema_present"], True)
        self.assertIn("no_governed_observation_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_inference_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_allegation_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_response_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_characterisation_linked", self.fixture.gap_codes(result))
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        for phrase in PROHIBITED_PHRASES:
            self.assertNotIn(phrase, serialised)

    def test_stage78a2a_observations_are_scoped_statused_and_not_promoted(self) -> None:
        accepted = self.fixture.observation(key="obs-accepted", status="accepted")
        self.fixture.observation(key="obs-candidate")
        self.fixture.observation(key="obs-deferred", status="deferred")
        self.fixture.observation(key="obs-rejected", status="rejected")
        self.fixture.observation(record=OTHER_RECORD, key="obs-other", status="accepted")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_observation")
        self.assertEqual({row["status"] for row in rows}, {"accepted", "candidate", "deferred", "rejected"})
        self.assertEqual({row["epistemic_label"] for row in rows}, {"observation"})
        self.assertEqual(result["coverage"]["observations_in_scope"], 4)
        self.assertIn(str(accepted["id"]), {row["object_id"] for row in rows})
        self.assertNotIn("5", {row["object_id"] for row in rows})
        for row in rows:
            self.assertTrue(row["does_not_establish"]["does_not_establish_inference"])
            self.assertTrue(row["does_not_establish"]["does_not_establish_evidence"])
            self.assertTrue(row["does_not_establish"]["does_not_establish_finding"])
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("observation is evidence", serialised)
        self.assertNotIn("finding", " ".join(row["epistemic_label"] for row in rows))

    def test_stage78a2a_inferences_preserve_binding_contrary_sources_and_supersession(self) -> None:
        original = self.fixture.inference(key="inf-original", status="accepted_as_inference")
        replacement = self.fixture.inference(key="inf-replacement", status="accepted_as_inference")
        inferences.supersede_inference(
            self.conn,
            original["id"],
            replacement_inference_id=replacement["id"],
            rationale="Later inference preserves history.",
            evidence_references=[],
            actor="reviewer",
            actor_role="administrator",
            occurred_at="2026-08-28T03:00:00Z",
            idempotency_key="inf-supersede",
        )
        self.fixture.inference(record=OTHER_RECORD, key="inf-other", status="accepted_as_inference")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_inference")
        self.assertEqual(len(rows), 2)
        statuses = {row["object_id"]: row["status"] for row in rows}
        self.assertEqual(statuses[str(original["id"])], "superseded")
        self.assertEqual(statuses[str(replacement["id"])], "accepted_as_inference")
        original_row = next(row for row in rows if row["object_id"] == str(original["id"]))
        self.assertEqual(original_row["supersession"]["replacement"]["replacement_governed_identity"], f"governed_inference:{replacement['idempotency_key']}")
        self.assertEqual(original_row["contrary_sources"][0]["binding_role"], "contrary_evidence")
        for row in rows:
            self.assertEqual(row["epistemic_label"], "inference")
            self.assertTrue(row["does_not_establish"]["does_not_establish_fact"])
            self.assertTrue(row["does_not_establish"]["does_not_establish_determination"])
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("proof of", serialised)
        self.assertNotIn("intent", serialised)

    def test_stage78a2a_inference_wrong_binding_is_excluded(self) -> None:
        self.fixture.inference(record=OTHER_RECORD, key="inf-unscoped", status="accepted_as_inference")
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "governed_inference"), [])
        self.assertIn("no_governed_inference_linked", self.fixture.gap_codes(result))

    def test_stage78a2a_allegations_preserve_attribution_status_and_not_finding(self) -> None:
        self.fixture.allegation(key="alg-recorded")
        accepted = self.fixture.allegation(key="alg-accepted", status="accepted_as_attributed_allegation")
        self.fixture.allegation(key="alg-correction", status="requires_attribution_correction")
        withdrawn = self.fixture.allegation(key="alg-withdrawn")
        allegations.withdraw_allegation(
            self.conn,
            withdrawn["id"],
            withdrawal_type="attributed_source_withdrawal",
            rationale="Withdrawn as represented.",
            withdrawal_bindings=[
                {"source_type": "canonical_record", "source_id": RECORD, "binding_role": "withdrawal_source"}
            ],
            actor="reviewer",
            actor_role="administrator",
            occurred_at="2026-08-28T03:00:00Z",
            idempotency_key="alg-withdraw",
        )
        self.fixture.allegation(record=OTHER_RECORD, key="alg-other", status="accepted_as_attributed_allegation")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_allegation")
        self.assertEqual(len(rows), 4)
        statuses = {row["status"] for row in rows}
        self.assertIn("recorded", statuses)
        self.assertIn("accepted_as_attributed_allegation", statuses)
        self.assertIn("requires_attribution_correction", statuses)
        self.assertIn("withdrawn", statuses)
        row = next(item for item in rows if item["object_id"] == str(accepted["id"]))
        self.assertEqual(row["representation_mode"], "faithful_paraphrase")
        self.assertEqual(row["attribution"]["attributed_source_label"], "Reporting source")
        self.assertTrue(row["does_not_establish"]["does_not_establish_truth"])
        self.assertTrue(row["does_not_establish"]["does_not_establish_finding"])
        self.assertEqual(row["contestation"]["status"], "attributed_proposition_only")
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("finding", " ".join(row["epistemic_label"] for row in rows))
        self.assertNotIn("corroboration", serialised)

    def test_stage78a2a_response_scope_declination_and_non_resolution(self) -> None:
        scoped_allegation = self.fixture.allegation(key="alg-response", status="accepted_as_attributed_allegation")
        self.fixture.response(allegation_id=scoped_allegation["id"], key="rsp-main")
        self.fixture.response(allegation_id=scoped_allegation["id"], key="rsp-decline", category="express_declination")
        other_allegation = self.fixture.allegation(record=OTHER_RECORD, key="alg-other-response")
        self.fixture.response(allegation_id=other_allegation["id"], record=RECORD, key="rsp-misowned")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_response")
        self.assertEqual({row["category"] for row in rows}, {"substantive_response", "express_declination"})
        self.assertEqual(result["coverage"]["responses_in_scope"], 2)
        decline = next(row for row in rows if row["category"] == "express_declination")
        self.assertEqual(decline["epistemic_label"], "response")
        self.assertTrue(decline["does_not_establish"]["does_not_resolve_allegation"])
        self.assertNotEqual(decline["category"], "non_response")
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("disproved", serialised)
        self.assertNotIn("resolved the allegation", serialised)

    def test_stage78a2a_response_withdrawal_and_supersession_remain_visible(self) -> None:
        allegation = self.fixture.allegation(key="alg-response-history")
        original = self.fixture.response(allegation_id=allegation["id"], key="rsp-original")
        replacement = self.fixture.response(allegation_id=allegation["id"], key="rsp-replacement")
        self.fixture.supersede_response(original["id"], replacement["id"], key="rsp-supersede")
        withdrawn = self.fixture.response(allegation_id=allegation["id"], key="rsp-withdrawn")
        self.fixture.withdraw_response(withdrawn["id"], key="rsp-withdraw")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_response")
        statuses = {row["object_id"]: row["status"] for row in rows}
        self.assertEqual(statuses[str(original["id"])], "superseded")
        self.assertEqual(statuses[str(withdrawn["id"])], "withdrawn")
        original_row = next(row for row in rows if row["object_id"] == str(original["id"]))
        self.assertTrue(original_row["supersession"]["superseded"])
        withdrawn_row = next(row for row in rows if row["object_id"] == str(withdrawn["id"]))
        self.assertTrue(withdrawn_row["supersession"]["withdrawn"])

    def test_stage78a2a_characterisations_scope_status_and_not_finding(self) -> None:
        scoped_allegation = self.fixture.allegation(key="alg-char")
        self.fixture.characterisation(key="char-root")
        self.fixture.characterisation(
            primary_kind="governed_allegation",
            primary_id=str(scoped_allegation["id"]),
            key="char-allegation",
            status="reviewed_as_qualified_representation",
        )
        self.fixture.characterisation(primary_kind="canonical_record", primary_id=OTHER_RECORD, key="char-other")
        withdrawn = self.fixture.characterisation(key="char-withdrawn", status="withdrawn")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_characterisation")
        self.assertEqual(len(rows), 3)
        statuses = {row["object_id"]: row["status"] for row in rows}
        self.assertEqual(statuses[str(withdrawn["id"])], "withdrawn")
        self.assertIn("reviewed_as_qualified_representation", set(statuses.values()))
        for row in rows:
            self.assertEqual(row["epistemic_label"], "characterisation")
            self.assertTrue(row["does_not_establish"]["does_not_establish_finding"])
            self.assertTrue(row["does_not_establish"]["does_not_establish_determination"])
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("characterisation was a finding", serialised)

    def test_stage78a2a_cross_record_intermediary_blocks_downstream_leakage(self) -> None:
        other_allegation = self.fixture.allegation(record=OTHER_RECORD, key="alg-cross")
        self.fixture.response(allegation_id=other_allegation["id"], record=RECORD, key="rsp-cross")
        self.fixture.characterisation(
            primary_kind="governed_response",
            primary_id="1",
            key="char-cross-response",
        )
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "governed_response"), [])
        self.assertEqual(self.fixture.rows_of(result, "governed_characterisation"), [])

    def test_stage78a2a_stage72_links_can_connect_new_scoped_objects(self) -> None:
        allegation = self.fixture.allegation(key="alg-link")
        response = self.fixture.response(allegation_id=allegation["id"], key="rsp-link")
        link_id = self.fixture.raw_pathway_link(
            source_kind="governed_allegation",
            source_id=str(allegation["id"]),
            target_kind="governed_response",
            target_id=str(response["id"]),
            relationship_type="allegation_to_response",
            idempotency_key="raw-a2a-link",
        )
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "pathway_link")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_id"], str(link_id))
        self.assertEqual(rows[0]["ownership_path"], "stage72.both_endpoints_in_stage78a_scope")

    def test_stage78a2a_chronology_preserves_indeterminate_proposition_time(self) -> None:
        self.fixture.observation(key="obs-time", status="accepted")
        self.fixture.inference(key="inf-time", status="accepted_as_inference")
        self.fixture.allegation(key="alg-time")
        self.fixture.response(allegation_id=1, key="rsp-time")
        self.fixture.characterisation(key="char-time")
        result = self.fixture.project()
        by_kind = {row["object_kind"]: row for row in result["rows"] if row["object_kind"].startswith("governed_")}
        self.assertEqual(by_kind["governed_observation"]["chronology_basis"], "unavailable")
        self.assertEqual(by_kind["governed_inference"]["chronology_basis"], "unavailable")
        self.assertEqual(by_kind["governed_characterisation"]["chronology_basis"], "unavailable")
        self.assertEqual(by_kind["governed_allegation"]["chronology_precision"], "month")
        self.assertEqual(by_kind["governed_response"]["chronology_basis"], "represented_date")
        self.assertEqual(by_kind["governed_response"]["chronology_precision"], "exact_date")
        self.assertEqual(by_kind["governed_observation"]["recorded_at"], ProjectionFixture.FIXED_CREATED_AT)

    def test_stage78a2a_status_binding_and_supersession_mutations_change_digest(self) -> None:
        inference = self.fixture.inference(key="inf-digest", status="accepted_as_inference")
        baseline = self.fixture.project()["projection_digest"]
        self.conn.execute(
            "UPDATE record_governed_inference_reviews SET status='rejected_as_inference' WHERE inference_id=?",
            (inference["id"],),
        )
        self.conn.commit()
        status_changed = self.fixture.project()["projection_digest"]
        self.assertNotEqual(baseline, status_changed)
        self.conn.execute(
            "UPDATE record_governed_inference_bindings SET source_id=? WHERE inference_id=? AND binding_role='primary_support'",
            (OTHER_RECORD, inference["id"]),
        )
        self.conn.commit()
        binding_changed = self.fixture.project()["projection_digest"]
        self.assertNotEqual(status_changed, binding_changed)
        self.conn.execute(
            "UPDATE record_governed_inference_bindings SET source_id=? WHERE inference_id=?",
            (OTHER_RECORD, inference["id"]),
        )
        self.conn.commit()
        self.assertEqual(self.fixture.rows_of(self.fixture.project(), "governed_inference"), [])

    def test_stage78a2a_withdrawal_changes_projection_digest(self) -> None:
        allegation = self.fixture.allegation(key="alg-digest")
        baseline = self.fixture.project()["projection_digest"]
        allegations.withdraw_allegation(
            self.conn,
            allegation["id"],
            withdrawal_type="attributed_source_withdrawal",
            rationale="Withdrawal preserved as represented.",
            withdrawal_bindings=[
                {"source_type": "canonical_record", "source_id": RECORD, "binding_role": "withdrawal_source"}
            ],
            actor="reviewer",
            actor_role="administrator",
            occurred_at="2026-08-28T03:00:00Z",
            idempotency_key="alg-digest-withdraw",
        )
        self.assertNotEqual(baseline, self.fixture.project()["projection_digest"])

    def test_stage78a2a_duplicate_bindings_do_not_duplicate_projected_rows(self) -> None:
        allegation = self.fixture.allegation(key="alg-dedupe")
        self.conn.execute(
            "INSERT INTO record_governed_allegation_bindings "
            "(allegation_id,source_type,source_id,binding_role,source_version,source_timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (allegation["id"], "canonical_record", RECORD, "contextual_source", "1", "2026-08-28T00:00:00Z"),
        )
        self.conn.commit()
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_allegation")
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["source_bindings"]), 2)

    def test_stage78a2a_equivalent_physical_ids_and_insertion_order_are_digest_stable(self) -> None:
        def build(order: list[str]) -> dict:
            conn = ProjectionFixture.fresh_connection()
            fixture = ProjectionFixture(conn)
            try:
                items = {
                    "observation": lambda: fixture.observation(key="stable-observation", status="accepted"),
                    "inference": lambda: fixture.inference(key="stable-inference", status="accepted_as_inference"),
                    "allegation": lambda: fixture.allegation(key="stable-allegation"),
                    "characterisation": lambda: fixture.characterisation(key="stable-characterisation"),
                }
                for name in order:
                    items[name]()
                result = fixture.project()
                return {
                    "digest": result["projection_digest"],
                    "payload": [
                        (row["object_kind"], row["governed_digest"], row["status"])
                        for row in result["rows"]
                    ],
                }
            finally:
                conn.close()

        first = build(["observation", "inference", "allegation", "characterisation"])
        second = build(["allegation", "characterisation", "observation", "inference"])
        self.assertEqual(first, second)

    def test_stage78a2a_repeated_projection_is_identical_and_non_mutating(self) -> None:
        self.fixture.observation(key="obs-repeat", status="accepted")
        self.fixture.inference(key="inf-repeat", status="accepted_as_inference")
        self.fixture.allegation(key="alg-repeat")
        self.fixture.characterisation(key="char-repeat")
        before = self._snapshot()
        first = self.fixture.project()
        second = self.fixture.project()
        self.assertEqual(first, second)
        self.assertEqual(before, self._snapshot())

    def test_stage78a2a_schema_partial_errors_are_bounded(self) -> None:
        cases = [
            ("record_pattern_observations", "governed_pathway_projection_stage62_schema_incomplete"),
            ("record_governed_inferences", "governed_pathway_projection_stage63_schema_incomplete"),
            ("record_governed_allegations", "governed_pathway_projection_stage64_schema_incomplete"),
            ("record_governed_responses", "governed_pathway_projection_stage65_schema_incomplete"),
            ("record_governed_characterisations", "governed_pathway_projection_stage74_schema_incomplete"),
        ]
        for table, error in cases:
            with self.subTest(table=table):
                conn = ProjectionFixture.fresh_connection()
                try:
                    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
                    with self.assertRaisesRegex(ValueError, error):
                        ProjectionFixture(conn).project()
                finally:
                    conn.close()

    # Internal helpers -------------------------------------------------

    def _snapshot(self) -> dict:
        return {
            "schema": sorted(row[0] for row in self.conn.execute("SELECT name FROM sqlite_master").fetchall()),
            "counts": self._table_counts(),
        }

    def _table_counts(self) -> dict:
        counts = {}
        for name in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            counts[name[0]] = self.conn.execute(f"SELECT COUNT(*) FROM {name[0]}").fetchone()[0]
        return counts


class Stage78A2B1AuthorityDeterminationChallengeProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = ProjectionFixture.fresh_connection()
        self.fixture = ProjectionFixture(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _snapshot(self) -> dict[str, int]:
        return {
            row[0]: self.conn.execute(f"SELECT COUNT(*) FROM {row[0]}").fetchone()[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    def test_stage78a2b1_projection_version_and_absent_family_availability(self) -> None:
        result = self.fixture.project()
        self.assertEqual(result["projection_version"], "78a2b2")
        self.assertFalse(result["coverage"]["stage66_schema_present"])
        self.assertFalse(result["coverage"]["stage67_schema_present"])
        self.assertFalse(result["coverage"]["stage68_schema_present"])
        self.assertEqual(result["coverage"].get("decision_authorities_in_scope"), 0)
        self.assertNotIn("no_governed_determination_linked", self.fixture.gap_codes(result))

    def test_direct_authority_and_mandate_project_without_legal_validity(self) -> None:
        item = self.fixture.authority()
        result = self.fixture.project()
        authority_rows = self.fixture.rows_of(result, "decision_authority")
        mandate_rows = self.fixture.rows_of(result, "decision_mandate")
        self.assertEqual(len(authority_rows), 1)
        self.assertEqual(len(mandate_rows), 1)
        self.assertEqual(authority_rows[0]["object_id"], str(item["id"]))
        self.assertEqual(authority_rows[0]["status"], "accepted_as_source_backed_authority_record")
        self.assertEqual(mandate_rows[0]["status"], "accepted_as_source_backed_authority_record")
        self.assertEqual(authority_rows[0]["ownership_path"], "stage66.authority_binding(canonical_record)")
        self.assertEqual(mandate_rows[0]["ownership_path"], "stage66.mandate_binding(canonical_record)")
        self.assertTrue(authority_rows[0]["does_not_establish"]["does_not_establish_jurisdiction"])
        self.assertTrue(mandate_rows[0]["does_not_establish"]["does_not_establish_lawfulness"])
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        for phrase in ("the authority had no jurisdiction", "decision was lawful", "decision was unlawful"):
            self.assertNotIn(phrase, serialised)

    def test_cross_record_authority_and_mandate_are_excluded(self) -> None:
        self.fixture.authority(record=OTHER_RECORD, key="other-authority")
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "decision_authority"), [])
        self.assertEqual(self.fixture.rows_of(result, "decision_mandate"), [])
        self.assertEqual(result["coverage"]["decision_authorities_in_scope"], 0)
        self.assertIn("no_governed_decision_authority_linked", self.fixture.gap_codes(result))

    def test_authority_status_supersession_and_cessation_history_are_visible(self) -> None:
        first = self.fixture.authority(key="authority-first")
        replacement = self.fixture.authority(key="authority-replacement", holder_label="Replacement office")
        authorities.supersede_authority_record(
            self.conn,
            object_type="authority",
            object_id=first["id"],
            replacement_id=replacement["id"],
            rationale="Later source-backed replacement.",
            actor="admin",
            actor_role="administrator",
            occurred_at="2026-08-28T03:00:00Z",
            idempotency_key="authority-supersession",
        )
        ceased = self.fixture.authority(key="authority-ceased", holder_label="Ceased office")
        authorities.cease_authority_record(
            self.conn,
            object_type="authority",
            object_id=ceased["id"],
            cessation_type="expiry_recorded",
            cessation_date_or_period="2026-12-31",
            rationale="Cessation as represented.",
            cessation_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "cessation_source"}],
            actor="admin",
            actor_role="administrator",
            occurred_at="2026-08-28T04:00:00Z",
            idempotency_key="authority-cessation",
        )
        rows = self.fixture.rows_of(self.fixture.project(), "decision_authority")
        by_id = {row["object_id"]: row for row in rows}
        self.assertEqual(by_id[str(first["id"])]["status"], "superseded")
        self.assertTrue(by_id[str(first["id"])]["supersession"]["superseded"])
        self.assertEqual(by_id[str(ceased["id"])]["status"], "ceased")
        self.assertTrue(by_id[str(ceased["id"])]["supersession"]["ceased"])

    def test_delegated_mandate_preserves_scope_without_inventing_validity(self) -> None:
        parent = self.fixture.authority(key="parent-authority")
        child = self.fixture.authority(key="child-authority", holder_label="Child office")
        delegated = authorities.create_mandate(
            self.conn,
            authority_id=child["id"],
            **self.fixture.mandate_payload(
                key_suffix="delegated",
                mandate_basis_category="delegation_instrument",
                delegation_status="delegated",
                delegating_authority_id=parent["id"],
                delegating_mandate_id=parent["mandates"][0]["id"],
            ),
            qualification_contract=self.fixture.authority_contract(),
            recorder_declaration={"acknowledged": True},
            delegation_source_declaration={"acknowledged": True},
            bindings=[
                {"source_type": "canonical_record", "source_id": RECORD, "binding_role": "authority_basis_source"},
                {"source_type": "canonical_record", "source_id": RECORD, "binding_role": "delegation_source"},
            ],
            actor="admin",
            actor_role="administrator",
            idempotency_key="delegated-mandate",
        )
        result = self.fixture.project()
        row = next(row for row in self.fixture.rows_of(result, "decision_mandate") if row["object_id"] == str(delegated["id"]))
        self.assertEqual(row["category"], "delegation_instrument")
        self.assertEqual(row["attribution"]["delegation_status"], "delegated")
        self.assertEqual(
            row["attribution"]["delegating_authority_identity"],
            f"decision_authority:{parent['idempotency_key']}",
        )
        self.assertTrue(row["does_not_establish"]["does_not_establish_jurisdiction"])

    def test_scoped_determination_projects_category_status_reasons_and_dates(self) -> None:
        det = self.fixture.determination()
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_determination")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["object_id"], str(det["id"]))
        self.assertEqual(row["category"], "merits_determination")
        self.assertEqual(row["status"], "recorded")
        self.assertEqual(row["represented_time"], "2026-06-01")
        self.assertEqual(row["recorded_at"], "2026-06-02")
        self.assertEqual(row["limitations"]["reasons_status"], "reasons_recorded")
        self.assertEqual(result["coverage"]["determination_reasons_recorded"], 1)
        self.assertTrue(row["does_not_establish"]["does_not_establish_cde_endorsement"])

    def test_no_reasons_recorded_gap_does_not_synthesise_reasons(self) -> None:
        self.fixture.determination(
            key="det-no-reasons",
            reasons="",
            reasons_status="no_reasons_recorded_in_source",
        )
        result = self.fixture.project()
        row = self.fixture.rows_of(result, "governed_determination")[0]
        self.assertEqual(row["limitations"]["reasons"], "")
        self.assertEqual(row["limitations"]["reasons_status"], "no_reasons_recorded_in_source")
        self.assertIn("no_governed_determination_reasons", self.fixture.gap_codes(result))
        self.assertNotIn("no reasons existed", json.dumps(result, ensure_ascii=False).casefold())

    def test_determination_object_roles_preserve_a2a_epistemic_boundaries(self) -> None:
        obs = self.fixture.observation(key="det-obs", status="accepted")
        inf = self.fixture.inference(key="det-inf", status="accepted_as_inference")
        alg = self.fixture.allegation(key="det-alg")
        rsp = self.fixture.response(allegation_id=alg["id"], key="det-rsp")
        self.fixture.determination(
            key="det-objects",
            governed_objects=[
                {"object_type": "accepted_pattern_observation", "object_id": obs["id"], "relationship_role": "observation_considered"},
                {"object_type": "governed_inference", "object_id": inf["id"], "relationship_role": "inference_considered"},
                {"object_type": "governed_allegation", "object_id": alg["id"], "relationship_role": "allegation_considered"},
                {"object_type": "governed_response", "object_id": rsp["id"], "relationship_role": "response_considered"},
            ],
        )
        result = self.fixture.project()
        det_row = self.fixture.rows_of(result, "governed_determination")[0]
        roles = {link["relationship_role"] for link in det_row["object_links"]}
        self.assertIn("observation_considered", roles)
        self.assertIn("inference_considered", roles)
        self.assertIn("allegation_considered", roles)
        self.assertIn("response_considered", roles)
        self.assertEqual(self.fixture.rows_of(result, "governed_allegation")[0]["epistemic_label"], "allegation")
        self.assertEqual(det_row["reliance"]["status"], "unavailable")

    def test_cross_record_determination_and_authority_link_scope_are_excluded(self) -> None:
        scoped_authority = self.fixture.authority(key="scoped-authority")
        self.fixture.determination(record=OTHER_RECORD, key="other-det", authority_item=scoped_authority)
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "governed_determination"), [])
        self.assertEqual(result["coverage"]["determinations_in_scope"], 0)
        self.assertIn("no_governed_determination_linked", self.fixture.gap_codes(result))

    def test_determination_effect_event_preserves_effect_without_legal_conclusion(self) -> None:
        det = self.fixture.determination(key="det-effect")
        self.fixture.effect_event(det["id"])
        result = self.fixture.project()
        effect = self.fixture.rows_of(result, "determination_effect_event")[0]
        self.assertEqual(effect["category"], "appeal_recorded")
        self.assertEqual(effect["represented_time"], "2026-07-01")
        self.assertTrue(effect["does_not_establish"]["does_not_alter_legal_effect_without_source"])

    def test_implementation_effect_is_projected_without_completion_conclusion(self) -> None:
        det = self.fixture.determination(
            key="det-implementation-boundary",
            category="remedial_determination",
        )
        determinations.record_effect_event(
            self.conn,
            determination_id=det["id"],
            event_type="implementation_recorded",
            represented_date_or_period="2026-07-01",
            rationale="Implementation event is source-recorded only.",
            qualification="Implementation remains bounded as an effect event.",
            effect_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "effect_event_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key="implementation-effect",
        )
        result = self.fixture.project()
        effect = self.fixture.rows_of(result, "determination_effect_event")[0]
        self.assertEqual(effect["category"], "implementation_recorded")
        self.assertTrue(effect["does_not_establish"]["does_not_alter_legal_effect_without_source"])
        row = self.fixture.rows_of(result, "governed_determination")[0]
        self.assertNotIn("implementation_or_remedy", row["limitations"])
        self.assertEqual(result["coverage"]["determination_effect_events_in_scope"], 1)

    def test_superseded_determination_history_remains_visible(self) -> None:
        first = self.fixture.determination(key="det-first")
        replacement = self.fixture.determination(key="det-replacement")
        determinations.supersede_determination(
            self.conn,
            determination_id=first["id"],
            replacement_determination_id=replacement["id"],
            rationale="Later source record.",
            actor="admin",
            actor_role="administrator",
            occurred_at="2026-08-28T05:00:00Z",
            idempotency_key="det-supersession",
        )
        rows = self.fixture.rows_of(self.fixture.project(), "governed_determination")
        first_row = next(row for row in rows if row["object_id"] == str(first["id"]))
        self.assertEqual(first_row["status"], "superseded")
        self.assertTrue(first_row["supersession"]["superseded"])

    def test_scoped_challenge_projects_events_outcomes_and_does_not_invalidate_target(self) -> None:
        det = self.fixture.determination(key="challenge-target")
        challenge = self.fixture.challenge(determination_id=det["id"], key="challenge-main")
        self.fixture.challenge_event(challenge["id"])
        challenges.record_outcome(
            self.conn,
            challenge_id=challenge["id"],
            outcome_type="dismissed_as_recorded",
            outcome_text="Outcome as represented.",
            outcome_date_or_period="2026-07-05",
            outcome_source={"source_type": "canonical_record", "source_id": RECORD},
            outcome_determination_id=None,
            rationale="Outcome does not alter target determination.",
            boundary_declaration={"acknowledged": True},
            actor="admin",
            actor_role="administrator",
            idempotency_key="challenge-outcome",
        )
        result = self.fixture.project()
        challenge_row = self.fixture.rows_of(result, "governed_challenge")[0]
        event_row = self.fixture.rows_of(result, "challenge_event")[0]
        outcome_row = self.fixture.rows_of(result, "challenge_outcome")[0]
        self.assertEqual(challenge_row["parent_governed_identity"], f"governed_determination:{det['idempotency_key']}")
        self.assertEqual(event_row["category"], "permission_requested")
        self.assertEqual(outcome_row["category"], "dismissed_as_recorded")
        self.assertTrue(challenge_row["does_not_establish"]["does_not_invalidate_determination"])
        self.assertEqual(self.fixture.rows_of(result, "governed_determination")[0]["status"], "recorded")
        self.assertNotIn("the challenge failed", json.dumps(result, ensure_ascii=False).casefold())

    def test_challenge_to_other_record_and_authority_link_alone_are_excluded(self) -> None:
        scoped_authority = self.fixture.authority(key="challenge-scoped-authority")
        other_det = self.fixture.determination(record=OTHER_RECORD, key="challenge-other-det")
        self.fixture.challenge(
            determination_id=other_det["id"],
            authority_item=scoped_authority,
            record=OTHER_RECORD,
            key="challenge-other",
        )
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "governed_challenge"), [])
        self.assertIn("no_governed_challenge_linked", self.fixture.gap_codes(result))

    def test_challenge_supersession_history_remains_visible(self) -> None:
        det = self.fixture.determination(key="challenge-sup-target")
        first = self.fixture.challenge(determination_id=det["id"], key="challenge-first")
        replacement = self.fixture.challenge(determination_id=det["id"], key="challenge-replacement")
        challenges.supersede_challenge(
            self.conn,
            challenge_id=first["id"],
            replacement_challenge_id=replacement["id"],
            rationale="Replacement challenge record.",
            actor="admin",
            actor_role="administrator",
            idempotency_key="challenge-supersession",
        )
        row = next(row for row in self.fixture.rows_of(self.fixture.project(), "governed_challenge") if row["object_id"] == str(first["id"]))
        self.assertEqual(row["status"], "superseded")
        self.assertTrue(row["supersession"]["superseded"])

    def test_duplicate_links_do_not_duplicate_projected_rows(self) -> None:
        det = self.fixture.determination(key="duplicate-det")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO record_governed_determination_bindings "
                "(determination_id, source_type, source_id, binding_role) VALUES (?, 'canonical_record', ?, 'determination_source')",
                (det["id"], RECORD),
            )
        self.conn.rollback()
        result = self.fixture.project()
        self.assertEqual(len(self.fixture.rows_of(result, "governed_determination")), 1)

    def test_partial_stage66_67_68_schemas_fail_closed(self) -> None:
        cases = [
            ("record_governed_decision_authorities", "governed_pathway_projection_stage66_schema_incomplete"),
            ("record_governed_determinations", "governed_pathway_projection_stage67_schema_incomplete"),
            ("record_governed_challenge_proceedings", "governed_pathway_projection_stage68_schema_incomplete"),
        ]
        for table, error in cases:
            with self.subTest(table=table):
                conn = ProjectionFixture.fresh_connection()
                try:
                    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
                    with self.assertRaisesRegex(ValueError, error):
                        ProjectionFixture(conn).project()
                finally:
                    conn.close()

    def test_a2b1_digest_changes_with_governed_mutations_but_not_projection_replay(self) -> None:
        det = self.fixture.determination(key="digest-det")
        first = self.fixture.project()
        second = self.fixture.project()
        self.assertEqual(first, second)
        determinations.record_effect_event(
            self.conn,
            determination_id=det["id"],
            event_type="appeal_recorded",
            represented_date_or_period="2026-07-01",
            rationale="Digest-sensitive effect event.",
            qualification="Effect event only.",
            effect_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "effect_event_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key="digest-effect",
        )
        changed = self.fixture.project()
        self.assertNotEqual(first["projection_digest"], changed["projection_digest"])
        self.assertEqual(self._snapshot(), self._snapshot())

    def test_physical_insertion_order_and_sparse_ids_are_digest_stable(self) -> None:
        def build(with_noise: bool) -> dict:
            conn = ProjectionFixture.fresh_connection()
            fixture = ProjectionFixture(conn)
            try:
                if with_noise:
                    fixture.authority(record=OTHER_RECORD, key="noise-authority")
                    fixture.determination(record=OTHER_RECORD, key="noise-determination")
                authority_item = fixture.authority(key="stable-authority")
                det = fixture.determination(key="stable-determination", authority_item=authority_item)
                fixture.challenge(determination_id=det["id"], authority_item=authority_item, key="stable-challenge")
                result = fixture.project()
                return {
                    "digest": result["projection_digest"],
                    "payload": [(row["object_kind"], row["governed_digest"], row["status"]) for row in result["rows"]],
                }
            finally:
                conn.close()

        self.assertEqual(
            build(False),
            build(True),
        )

    def test_unknown_and_padded_record_references_remain_bounded_and_read_only(self) -> None:
        before = self._snapshot()
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_record_not_found"):
            self.fixture.project(reference="REC-MISSING")
        with self.assertRaisesRegex(ValueError, "governed_pathway_projection_record_not_found"):
            self.fixture.project(reference=f" {RECORD} ")
        self.assertEqual(before, self._snapshot())

    def test_a1_a2a_rows_and_prohibited_conclusions_remain_preserved(self) -> None:
        self.fixture.notice()
        self.fixture.deadline()
        self.fixture.observation(key="preserve-obs", status="accepted")
        self.fixture.inference(key="preserve-inf", status="accepted_as_inference")
        alg = self.fixture.allegation(key="preserve-alg")
        self.fixture.response(allegation_id=alg["id"], key="preserve-rsp", category="express_declination")
        self.fixture.characterisation(key="preserve-char")
        self.fixture.determination(key="preserve-det")
        result = self.fixture.project()
        kinds = set(self.fixture.kinds(result))
        for kind in (
            "procedural_notice",
            "procedural_deadline",
            "governed_observation",
            "governed_inference",
            "governed_allegation",
            "governed_response",
            "governed_characterisation",
            "governed_determination",
        ):
            self.assertIn(kind, kinds)
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        for phrase in PROHIBITED_PHRASES:
            self.assertNotIn(phrase, serialised)


class Stage78A2B2CompletionProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = ProjectionFixture.fresh_connection()
        self.fixture = ProjectionFixture(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _snapshot(self) -> dict[str, int]:
        return {
            row[0]: self.conn.execute(f"SELECT COUNT(*) FROM {row[0]}").fetchone()[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    def test_stage78a2b2_projection_version_and_absent_families_are_unavailable(self) -> None:
        result = self.fixture.project()
        self.assertEqual(result["projection_version"], "78a2b2")
        self.assertFalse(result["coverage"]["stage69_schema_present"])
        self.assertFalse(result["coverage"]["stage70_schema_present"])
        self.assertFalse(result["coverage"]["stage73_schema_present"])
        self.assertEqual(result["coverage"]["remedies_in_scope"], 0)
        self.assertNotIn("no_governed_remedy_linked", self.fixture.gap_codes(result))
        self.assertNotIn("no_governed_determination_publication_linked", self.fixture.gap_codes(result))

    def test_remedy_projects_from_scoped_determination_without_implementation_conclusion(self) -> None:
        det = self.fixture.accepted_determination(key="remedy-det", category="remedial_determination")
        remedy = self.fixture.remedy(determination_id=det["id"], key="remedy-main", status="accepted_as_represented_direction")
        other_det = self.fixture.accepted_determination(record=OTHER_RECORD, key="other-remedy-det")
        self.fixture.remedy(determination_id=other_det["id"], key="remedy-other")
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "governed_remedy")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["object_id"], str(remedy["id"]))
        self.assertEqual(row["parent_governed_identity"], f"governed_determination:{det['idempotency_key']}")
        self.assertEqual(row["status"], "accepted_as_represented_direction")
        self.assertEqual(row["ownership_path"], "stage69.remedy_determination_link(scoped_determination)")
        self.assertTrue(row["does_not_establish"]["does_not_establish_implementation"])
        self.assertTrue(row["does_not_establish"]["does_not_establish_compliance"])
        self.assertEqual(result["coverage"]["remedies_in_scope"], 1)
        self.assertNotIn("no remedy was provided", json.dumps(result, ensure_ascii=False).casefold())

    def test_remedy_supersession_history_and_no_remedy_category_remain_visible(self) -> None:
        det = self.fixture.accepted_determination(key="remedy-history-det", category="remedial_determination")
        first = self.fixture.remedy(determination_id=det["id"], key="remedy-first")
        replacement = self.fixture.remedy(determination_id=det["id"], key="remedy-replacement")
        remedies.supersede_remedy(
            self.conn,
            remedy_id=first["id"],
            replacement_remedy_id=replacement["id"],
            rationale="Replacement direction as represented.",
            actor="admin",
            actor_role="administrator",
            idempotency_key="remedy-supersession",
        )
        no_remedy = self.fixture.remedy(determination_id=det["id"], key="remedy-none", category="no_remedy_directed")
        rows = self.fixture.rows_of(self.fixture.project(), "governed_remedy")
        by_id = {row["object_id"]: row for row in rows}
        self.assertEqual(by_id[str(first["id"])]["status"], "superseded")
        self.assertTrue(by_id[str(first["id"])]["supersession"]["superseded"])
        self.assertEqual(by_id[str(no_remedy["id"])]["category"], "no_remedy_directed")

    def test_implementation_compliance_and_verification_events_preserve_epistemic_boundaries(self) -> None:
        remedy = self.fixture.remedy(key="event-remedy", status="accepted_as_represented_direction")
        categories = [
            "implementation_reported",
            "compliance_evidence_submitted",
            "non_compliance_alleged",
            "verification_performed",
        ]
        allegation = self.fixture.allegation(key="event-non-compliance-allegation")
        for category in categories:
            objects = None
            if category == "non_compliance_alleged":
                objects = [{"object_type": "governed_allegation", "object_id": allegation["id"], "relationship_role": "allegation_context"}]
            self.fixture.implementation_event(
                remedy_id=remedy["id"],
                key=f"event-{category}",
                category=category,
                governed_objects=objects,
            )
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "implementation_event")
        self.assertEqual({row["category"] for row in rows}, set(categories))
        self.assertEqual(result["coverage"]["implementation_events_in_scope"], 4)
        self.assertEqual(result["coverage"]["verification_events_in_scope"], 1)
        verification = next(row for row in rows if row["category"] == "verification_performed")
        self.assertEqual(verification["limitations"]["verification_conclusion"], "verification_inconclusive")
        for row in rows:
            self.assertTrue(row["does_not_establish"]["does_not_establish_compliance"])
            self.assertTrue(row["does_not_establish"]["does_not_establish_completion"])
        serialised = json.dumps(result, ensure_ascii=False).casefold()
        for phrase in ("implementation was complete", "proof of compliance", "non-compliance finding"):
            self.assertNotIn(phrase, serialised)

    def test_formal_completion_requires_distinct_linked_determination(self) -> None:
        remedy = self.fixture.remedy(key="formal-remedy", status="accepted_as_represented_direction")
        completion = self.fixture.accepted_determination(key="formal-completion-det", category="status_determination")
        event = self.fixture.implementation_event(
            remedy_id=remedy["id"],
            key="formal-completion-event",
            category="implementation_completed_as_formally_determined",
            governed_objects=[
                {
                    "object_type": "governed_determination",
                    "object_id": completion["id"],
                    "relationship_role": "formal_completion_determination",
                }
            ],
        )
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "formal_completion_determination")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_id"], str(completion["id"]))
        self.assertEqual(rows[0]["parent_id"], str(event["id"]))
        self.assertEqual(rows[0]["ownership_path"], "stage70.object_link(formal_completion_determination)+scoped_remedy")
        self.assertTrue(rows[0]["does_not_establish"]["does_not_establish_completion"])
        self.assertEqual(result["coverage"]["formal_completion_determinations_in_scope"], 1)

    def test_misowned_intermediate_blocks_implementation_and_formal_completion_leakage(self) -> None:
        other_det = self.fixture.accepted_determination(record=OTHER_RECORD, key="misowned-det")
        other_remedy = self.fixture.remedy(determination_id=other_det["id"], key="misowned-remedy")
        completion = self.fixture.accepted_determination(key="misowned-completion")
        self.fixture.implementation_event(
            remedy_id=other_remedy["id"],
            key="misowned-implementation",
            category="implementation_completed_as_formally_determined",
            governed_objects=[
                {
                    "object_type": "governed_determination",
                    "object_id": completion["id"],
                    "relationship_role": "formal_completion_determination",
                }
            ],
        )
        result = self.fixture.project()
        self.assertEqual(self.fixture.rows_of(result, "governed_remedy"), [])
        self.assertEqual(self.fixture.rows_of(result, "implementation_event"), [])
        self.assertEqual(self.fixture.rows_of(result, "formal_completion_determination"), [])

    def test_publication_projects_from_scoped_determination_without_endorsement(self) -> None:
        det = self.fixture.accepted_determination(key="publication-det")
        publication = self.fixture.publication(determination_id=det["id"], key="publication-main", publish=True)
        other_det = self.fixture.accepted_determination(record=OTHER_RECORD, key="publication-other-det")
        self.fixture.publication(determination_id=other_det["id"], key="publication-other", publish=True)
        result = self.fixture.project()
        rows = self.fixture.rows_of(result, "determination_publication")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["object_id"], str(publication["id"]))
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["parent_governed_identity"], f"governed_determination:{det['idempotency_key']}")
        self.assertEqual(row["limitations"]["privacy_status"], "cleared_for_publication")
        self.assertEqual(row["limitations"]["redaction_status"], "cleared_for_publication")
        self.assertTrue(row["does_not_establish"]["does_not_establish_endorsement"])
        self.assertEqual(result["coverage"]["determination_publications_in_scope"], 1)
        self.assertNotIn("publication is endorsement", json.dumps(result, ensure_ascii=False).casefold())

    def test_stage67_implementation_effect_is_now_in_completion_scope(self) -> None:
        det = self.fixture.determination(
            key="det-implementation-boundary",
            category="remedial_determination",
        )
        determinations.record_effect_event(
            self.conn,
            determination_id=det["id"],
            event_type="implementation_recorded",
            represented_date_or_period="2026-07-01",
            rationale="Implementation event is source-recorded only.",
            qualification="Implementation remains bounded as an effect event.",
            effect_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "effect_event_source"}],
            actor="admin",
            actor_role="administrator",
            idempotency_key="implementation-effect",
        )
        result = self.fixture.project()
        effect = self.fixture.rows_of(result, "determination_effect_event")[0]
        self.assertEqual(effect["category"], "implementation_recorded")
        self.assertTrue(effect["does_not_establish"]["does_not_alter_legal_effect_without_source"])

    def test_stage69_70_73_present_empty_families_emit_scoped_gaps(self) -> None:
        remedies.ensure_remedy_tables(self.conn)
        implementation_events.ensure_implementation_event_tables(self.conn)
        publications.ensure_publication_tables(self.conn)
        self.fixture.accepted_determination(key="gap-det")
        result = self.fixture.project()
        self.assertIn("no_governed_remedy_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_implementation_event_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_verification_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_formal_completion_determination_linked", self.fixture.gap_codes(result))
        self.assertIn("no_governed_determination_publication_linked", self.fixture.gap_codes(result))
        for gap in result["gaps"]:
            self.assertNotIn("no remedy was provided", gap["statement"].casefold())

    def test_partial_stage69_70_73_schemas_fail_closed(self) -> None:
        cases = [
            ("record_governed_remedies", "governed_pathway_projection_stage69_schema_incomplete"),
            ("record_governed_implementation_events", "governed_pathway_projection_stage70_schema_incomplete"),
            ("record_governed_determination_publications", "governed_pathway_projection_stage73_schema_incomplete"),
        ]
        for table, error in cases:
            with self.subTest(table=table):
                conn = ProjectionFixture.fresh_connection()
                try:
                    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
                    with self.assertRaisesRegex(ValueError, error):
                        ProjectionFixture(conn).project()
                finally:
                    conn.close()

    def test_duplicates_physical_ids_and_insertion_order_do_not_change_completion_digest(self) -> None:
        def build(with_noise: bool) -> dict:
            conn = ProjectionFixture.fresh_connection()
            fixture = ProjectionFixture(conn)
            try:
                if with_noise:
                    other_det = fixture.accepted_determination(record=OTHER_RECORD, key="noise-det")
                    other_remedy = fixture.remedy(determination_id=other_det["id"], key="noise-remedy")
                    fixture.implementation_event(remedy_id=other_remedy["id"], key="noise-event")
                    fixture.publication(determination_id=other_det["id"], key="noise-publication")
                det = fixture.accepted_determination(key="stable-det", category="remedial_determination")
                remedy = fixture.remedy(determination_id=det["id"], key="stable-remedy", status="accepted_as_represented_direction")
                fixture.implementation_event(remedy_id=remedy["id"], key="stable-event", category="verification_performed")
                fixture.publication(determination_id=det["id"], key="stable-publication", publish=True)
                result = fixture.project()
                return {
                    "digest": result["projection_digest"],
                    "payload": [(row["object_kind"], row["governed_digest"], row["status"]) for row in result["rows"]],
                }
            finally:
                conn.close()

        self.assertEqual(build(False), build(True))

    def test_downstream_source_status_and_link_mutations_change_digest(self) -> None:
        det = self.fixture.accepted_determination(key="mutation-det", category="remedial_determination")
        remedy = self.fixture.remedy(determination_id=det["id"], key="mutation-remedy")
        event = self.fixture.implementation_event(remedy_id=remedy["id"], key="mutation-event")
        publication = self.fixture.publication(determination_id=det["id"], key="mutation-publication")
        baseline = self.fixture.project()["projection_digest"]
        self.conn.execute(
            "UPDATE record_governed_remedies SET remedy_category='disclosure' WHERE id=?",
            (remedy["id"],),
        )
        self.conn.commit()
        remedy_changed = self.fixture.project()["projection_digest"]
        self.assertNotEqual(baseline, remedy_changed)
        self.conn.execute(
            "UPDATE record_governed_implementation_events SET event_category='partial_implementation_reported' WHERE id=?",
            (event["id"],),
        )
        self.conn.commit()
        event_changed = self.fixture.project()["projection_digest"]
        self.assertNotEqual(remedy_changed, event_changed)
        self.conn.execute(
            "UPDATE record_governed_determination_publications SET privacy_status='review_required' WHERE id=?",
            (publication["id"],),
        )
        self.conn.commit()
        self.assertNotEqual(event_changed, self.fixture.project()["projection_digest"])

    def test_repeated_completion_projection_is_identical_read_only_and_keeps_a1_a2a_a2b1_rows(self) -> None:
        self.fixture.notice()
        self.fixture.deadline()
        self.fixture.observation(key="completion-obs", status="accepted")
        self.fixture.inference(key="completion-inf", status="accepted_as_inference")
        allegation = self.fixture.allegation(key="completion-alg")
        self.fixture.response(allegation_id=allegation["id"], key="completion-rsp")
        self.fixture.characterisation(key="completion-char")
        det = self.fixture.accepted_determination(key="completion-det", category="remedial_determination")
        challenge = self.fixture.challenge(determination_id=det["id"], key="completion-challenge")
        self.fixture.challenge_event(challenge["id"], key="completion-challenge-event")
        remedy = self.fixture.remedy(determination_id=det["id"], key="completion-remedy")
        self.fixture.implementation_event(remedy_id=remedy["id"], key="completion-event")
        self.fixture.publication(determination_id=det["id"], key="completion-publication")
        before = self._snapshot()
        first = self.fixture.project()
        second = self.fixture.project()
        self.assertEqual(first, second)
        self.assertEqual(before, self._snapshot())
        kinds = set(self.fixture.kinds(first))
        for kind in (
            "procedural_notice",
            "procedural_deadline",
            "governed_observation",
            "governed_inference",
            "governed_allegation",
            "governed_response",
            "governed_characterisation",
            "decision_authority",
            "decision_mandate",
            "governed_determination",
            "governed_challenge",
            "governed_remedy",
            "implementation_event",
            "determination_publication",
        ):
            self.assertIn(kind, kinds)
        serialised = json.dumps(first, ensure_ascii=False).casefold()
        for phrase in PROHIBITED_PHRASES:
            self.assertNotIn(phrase, serialised)


if __name__ == "__main__":
    unittest.main()
