"""Stage 78 read-only governed pathway projection for one canonical record.

This module projects Stage 71 governed procedural-time objects and Stage 72
governed pathway links, plus the Stage 62/63/64/65/74 attributed-proposition
chain, into one deterministic, read-only projection rooted at a single
canonical record.  It creates no schema, initialises no tables, writes no rows,
and never infers receipt, lateness, adequacy, waiver, reliance, completeness,
participation, truth, disproof, finding or legal effect from any record.

Provenance boundaries are preserved verbatim: notice issuance never becomes
receipt, a disputed category never becomes an adverse conclusion, a calculated
expiry never becomes a lateness determination, and an allegation never becomes
a finding.  Only governed status and category vocabulary are surfaced, and the
producer's own derived-status logic is reused unchanged so the projection can
never disagree with the governed source state.

Physical insertion order is never presented as substantive chronology.  Rows
are ordered by represented-time intervals with explicit precision, a fixed
object-kind rank, and the governed content digest.  Rows whose represented
time is unavailable are ordered last and labelled ``recording_time_only``.

The projection digest is SHA-256 over canonical JSON of the governed payload.
It intentionally excludes surrogate row identifiers (``object_id`` /
``parent_id``) and any caller-supplied ``as_of`` value, so equivalent governed
states produce the same digest regardless of table insertion order, while any
change to governed content, status, category, represented time, ownership,
bindings, contestation, supersession, calculation or pathway reliance changes
the digest.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_allegations as allegations
from api import record_governed_characterisations as characterisations
from api import record_governed_challenges as challenges
from api import record_governed_decision_authorities as authorities
from api import record_governed_determination_publications as publications
from api import record_governed_determinations as determinations
from api import record_governed_implementation_events as implementation_events
from api import record_governed_inferences as inferences
from api import record_governed_pathway as pathway
from api import record_governed_procedural_time as procedural
from api import record_governed_remedies as remedies
from api import record_governed_responses as responses

PROJECTION_CONTRACT = "stage78.pathway_projection.v1"
PROJECTION_VERSION = "78a2b2"

STAGE71_TABLES = (
    "record_governed_procedural_notices",
    "record_governed_procedural_deadlines",
    "record_governed_procedural_time_bindings",
    "record_governed_procedural_time_object_links",
    "record_governed_procedural_time_events",
    "record_governed_deadline_calculations",
    "record_governed_procedural_time_reviews",
    "record_governed_procedural_time_supersessions",
)
STAGE72_TABLES = (
    "record_governed_pathway_links",
    "record_governed_pathway_bindings",
    "record_governed_pathway_reviews",
    "record_governed_pathway_supersessions",
)
STAGE62_TABLES = (
    "record_pattern_observations",
    "record_pattern_observation_bindings",
    "record_pattern_observation_reviews",
)
STAGE63_TABLES = (
    "record_governed_inferences",
    "record_governed_inference_bindings",
    "record_governed_inference_reviews",
    "record_governed_inference_supersessions",
)
STAGE64_TABLES = (
    "record_governed_allegations",
    "record_governed_allegation_bindings",
    "record_governed_allegation_reviews",
    "record_governed_allegation_supersessions",
    "record_governed_allegation_withdrawals",
)
STAGE65_TABLES = (
    "record_governed_responses",
    "record_governed_response_allegation_links",
    "record_governed_response_bindings",
    "record_governed_response_reviews",
    "record_governed_response_supersessions",
    "record_governed_response_withdrawals",
)
STAGE74_TABLES = (
    "record_governed_characterisations",
    "record_governed_characterisation_bindings",
    "record_governed_characterisation_references",
    "record_governed_characterisation_events",
)
STAGE66_TABLES = (
    "record_governed_decision_authorities",
    "record_governed_decision_authority_mandates",
    "record_governed_decision_authority_bindings",
    "record_governed_decision_authority_reviews",
    "record_governed_decision_authority_supersessions",
    "record_governed_decision_authority_cessations",
)
STAGE67_TABLES = (
    "record_governed_determinations",
    "record_governed_determination_authority_links",
    "record_governed_determination_bindings",
    "record_governed_determination_governed_object_links",
    "record_governed_determination_reviews",
    "record_governed_determination_supersessions",
    "record_governed_determination_effect_events",
)
STAGE68_TABLES = (
    "record_governed_challenge_proceedings",
    "record_governed_challenge_determination_links",
    "record_governed_challenge_authority_links",
    "record_governed_challenge_bindings",
    "record_governed_challenge_events",
    "record_governed_challenge_reviews",
    "record_governed_challenge_supersessions",
    "record_governed_challenge_outcomes",
)
STAGE69_TABLES = (
    "record_governed_remedies",
    "record_governed_remedy_determination_links",
    "record_governed_remedy_bindings",
    "record_governed_remedy_reviews",
    "record_governed_remedy_supersessions",
)
STAGE70_TABLES = (
    "record_governed_implementation_events",
    "record_governed_implementation_event_remedy_links",
    "record_governed_implementation_event_bindings",
    "record_governed_implementation_event_object_links",
    "record_governed_implementation_event_reviews",
    "record_governed_implementation_event_supersessions",
)
STAGE73_TABLES = (
    "record_governed_determination_publications",
    "record_governed_determination_publication_reviews",
    "record_governed_determination_publication_events",
    "record_governed_determination_publication_supersessions",
)

OBJECT_KIND_AUTHORITY = "decision_authority"
OBJECT_KIND_MANDATE = "decision_mandate"
OBJECT_KIND_DETERMINATION = "governed_determination"
OBJECT_KIND_DETERMINATION_EFFECT = "determination_effect_event"
OBJECT_KIND_CHALLENGE = "governed_challenge"
OBJECT_KIND_CHALLENGE_EVENT = "challenge_event"
OBJECT_KIND_CHALLENGE_OUTCOME = "challenge_outcome"
OBJECT_KIND_REMEDY = "governed_remedy"
OBJECT_KIND_IMPLEMENTATION_EVENT = "implementation_event"
OBJECT_KIND_FORMAL_COMPLETION = "formal_completion_determination"
OBJECT_KIND_DETERMINATION_PUBLICATION = "determination_publication"
OBJECT_KIND_OBSERVATION = "governed_observation"
OBJECT_KIND_INFERENCE = "governed_inference"
OBJECT_KIND_ALLEGATION = "governed_allegation"
OBJECT_KIND_RESPONSE = "governed_response"
OBJECT_KIND_CHARACTERISATION = "governed_characterisation"
OBJECT_KIND_NOTICE = "procedural_notice"
OBJECT_KIND_DEADLINE = "procedural_deadline"
OBJECT_KIND_EVENT = "procedural_time_event"
OBJECT_KIND_CALCULATION = "deadline_calculation"
OBJECT_KIND_PATHWAY_LINK = "pathway_link"

KIND_RANK = {
    OBJECT_KIND_OBSERVATION: 0,
    OBJECT_KIND_INFERENCE: 1,
    OBJECT_KIND_ALLEGATION: 2,
    OBJECT_KIND_RESPONSE: 3,
    OBJECT_KIND_CHARACTERISATION: 4,
    OBJECT_KIND_AUTHORITY: 5,
    OBJECT_KIND_MANDATE: 6,
    OBJECT_KIND_DETERMINATION: 7,
    OBJECT_KIND_DETERMINATION_EFFECT: 8,
    OBJECT_KIND_CHALLENGE: 9,
    OBJECT_KIND_CHALLENGE_EVENT: 10,
    OBJECT_KIND_CHALLENGE_OUTCOME: 11,
    OBJECT_KIND_REMEDY: 12,
    OBJECT_KIND_IMPLEMENTATION_EVENT: 13,
    OBJECT_KIND_FORMAL_COMPLETION: 14,
    OBJECT_KIND_DETERMINATION_PUBLICATION: 15,
    OBJECT_KIND_NOTICE: 16,
    OBJECT_KIND_DEADLINE: 17,
    OBJECT_KIND_EVENT: 18,
    OBJECT_KIND_CALCULATION: 19,
    OBJECT_KIND_PATHWAY_LINK: 20,
}

PRECISION_RANK = {
    "timestamp": 0,
    "exact_date": 0,
    "period": 0,
    "month": 1,
    "year": 2,
    "recording_time": 3,
    "unavailable": 4,
}

_STAGE71_ENDPOINT_KINDS = {
    OBJECT_KIND_NOTICE,
    OBJECT_KIND_DEADLINE,
    OBJECT_KIND_EVENT,
    OBJECT_KIND_CALCULATION,
}
_A2A_ENDPOINT_KINDS = {
    OBJECT_KIND_OBSERVATION,
    OBJECT_KIND_INFERENCE,
    OBJECT_KIND_ALLEGATION,
    OBJECT_KIND_RESPONSE,
    OBJECT_KIND_CHARACTERISATION,
}
_A2B1_ENDPOINT_KINDS = {
    OBJECT_KIND_AUTHORITY,
    OBJECT_KIND_MANDATE,
    OBJECT_KIND_DETERMINATION,
    OBJECT_KIND_CHALLENGE,
}
_A2B2_ENDPOINT_KINDS = {
    OBJECT_KIND_REMEDY,
    OBJECT_KIND_IMPLEMENTATION_EVENT,
    OBJECT_KIND_FORMAL_COMPLETION,
    OBJECT_KIND_DETERMINATION_PUBLICATION,
}

_DISPUTE_CATEGORIES = {
    "receipt_disputed",
    "notice_adequacy_disputed",
    "deadline_disputed",
    "trigger_disputed",
}

CATEGORY_LABELS = {
    "repeated_relationship_type": "Repeated relationship type",
    "procedural": "Procedural inference",
    "contextual": "Contextual inference",
    "reported_conduct": "Reported conduct",
    "reported_omission": "Reported omission",
    "reported_statement": "Reported statement",
    "reported_condition": "Reported condition",
    "reported_responsibility": "Reported responsibility",
    "substantive_response": "Substantive response",
    "partial_response": "Partial response",
    "contextual_response": "Contextual response",
    "procedural_objection": "Procedural objection",
    "request_for_particulars": "Request for particulars",
    "correction_of_attribution": "Correction of attribution",
    "express_declination": "Express declination",
    "notice_issued": "Notice issued",
    "notice_dispatched": "Notice dispatched",
    "notice_made_available": "Notice made available",
    "notice_received_as_evidenced": "Notice received as evidenced",
    "receipt_disputed": "Receipt disputed",
    "notice_adequacy_disputed": "Notice adequacy disputed",
    "response_deadline": "Response deadline",
    "appeal_deadline": "Appeal deadline",
    "review_application_deadline": "Review application deadline",
    "submission_deadline": "Submission deadline",
    "compliance_deadline": "Compliance deadline",
    "procedural_hearing_deadline": "Procedural hearing deadline",
    "other_stated_procedural_deadline": "Other stated procedural deadline",
    "extension_requested": "Extension requested",
    "extension_granted": "Extension granted",
    "extension_refused_as_represented": "Extension refused as represented",
    "deadline_corrected": "Deadline corrected",
    "deadline_disputed": "Deadline disputed",
    "trigger_disputed": "Trigger disputed",
    "calculation_recorded": "Calculation recorded",
    "calculated_expiry_recorded": "Calculated expiry recorded",
    "late_filing_alleged": "Late filing alleged",
    "formal_late_filing_determination_linked": "Formal late-filing determination linked",
    "deadline_not_reached_as_calculated": "Deadline not reached as calculated",
    "deadline_reached_as_calculated": "Deadline reached as calculated",
    "deadline_passed_as_calculated": "Deadline passed as calculated",
    "calculation_not_supported": "Calculation not supported",
    "evidence_to_observation": "Evidence to observation",
    "evidence_to_inference": "Evidence to inference",
    "evidence_to_allegation": "Evidence to allegation",
    "allegation_to_response": "Allegation to response",
    "authority_to_determination": "Authority to determination",
    "mandate_to_determination": "Mandate to determination",
    "observation_to_determination": "Observation to determination",
    "inference_to_determination": "Inference to determination",
    "allegation_to_determination": "Allegation to determination",
    "response_to_determination": "Response to determination",
    "determination_to_challenge": "Determination to challenge",
    "determination_to_remedy": "Determination to remedy",
    "remedy_to_implementation": "Remedy to implementation",
    "statutory_instrument": "Statutory instrument",
    "regulatory_instrument": "Regulatory instrument",
    "appointment_instrument": "Appointment instrument",
    "delegation_instrument": "Delegation instrument",
    "governance_instrument": "Governance instrument",
    "court_or_tribunal_order": "Court or tribunal order",
    "contractual_instrument": "Contractual instrument",
    "other_formal_instrument": "Other formal instrument",
    "procedural_determination": "Procedural determination",
    "jurisdictional_determination": "Jurisdictional determination",
    "evidential_determination": "Evidential determination",
    "merits_determination": "Merits determination",
    "remedial_determination": "Remedial determination",
    "administrative_disposition": "Administrative disposition",
    "status_determination": "Status determination",
    "appeal_recorded": "Appeal recorded",
    "review_proceeding_recorded": "Review proceeding recorded",
    "variation_recorded": "Variation recorded",
    "stay_recorded": "Stay recorded",
    "revocation_recorded": "Revocation recorded",
    "set_aside_recorded": "Set aside recorded",
    "implementation_recorded": "Implementation recorded",
    "replacement_recorded": "Replacement recorded",
    "appeal": "Appeal",
    "internal_review": "Internal review",
    "administrative_review": "Administrative review",
    "statutory_review": "Statutory review",
    "judicial_review_application": "Judicial review application",
    "reconsideration_request": "Reconsideration request",
    "filing_recorded": "Filing recorded",
    "acknowledgement_recorded": "Acknowledgement recorded",
    "permission_requested": "Permission requested",
    "permission_granted_as_recorded": "Permission granted as recorded",
    "permission_refused_as_recorded": "Permission refused as recorded",
    "admissibility_accepted_as_recorded": "Admissibility accepted as recorded",
    "inadmissibility_recorded": "Inadmissibility recorded",
    "submissions_invited": "Submissions invited",
    "hearing_scheduled": "Hearing scheduled",
    "review_commenced_as_recorded": "Review commenced as recorded",
    "withdrawal_recorded": "Withdrawal recorded",
    "discontinuance_recorded": "Discontinuance recorded",
    "outcome_recorded": "Outcome recorded",
    "closure_recorded": "Closure recorded",
    "allowed_as_recorded": "Allowed as recorded",
    "dismissed_as_recorded": "Dismissed as recorded",
    "varied_as_recorded": "Varied as recorded",
    "remitted_as_recorded": "Remitted as recorded",
    "set_aside_as_recorded": "Set aside as recorded",
    "withdrawn_as_recorded": "Withdrawn as recorded",
    "discontinued_as_recorded": "Discontinued as recorded",
    "other_outcome_as_recorded": "Other outcome as recorded",
    "payment_or_compensation": "Payment or compensation",
    "reconsideration": "Reconsideration",
    "record_correction": "Record correction",
    "disclosure": "Disclosure",
    "cessation_of_conduct": "Cessation of conduct",
    "procedural_rehearing": "Procedural rehearing",
    "institutional_action": "Institutional action",
    "declaratory_relief": "Declaratory relief",
    "no_remedy_directed": "No remedy directed",
    "implementation_reported": "Implementation reported",
    "partial_implementation_reported": "Partial implementation reported",
    "implementation_disputed": "Implementation disputed",
    "deadline_extension_recorded": "Deadline extension recorded",
    "compliance_evidence_submitted": "Compliance evidence submitted",
    "non_compliance_alleged": "Non-compliance alleged",
    "verification_performed": "Verification performed",
    "implementation_completed_as_formally_determined": "Implementation completed as formally determined",
    "published": "Published",
    "approved_for_publication": "Approved for publication",
    "withdrawn_from_publication": "Withdrawn from publication",
}

_HIGH_BOUND = "9999-12-31"
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")

GAP_STATEMENTS = {
    "no_governed_observation_linked": "No governed observation record was found linked within this canonical-record scope.",
    "no_governed_inference_linked": "No governed inference record was found linked within this canonical-record scope.",
    "no_governed_allegation_linked": "No governed allegation record was found linked within this canonical-record scope.",
    "no_governed_response_linked": "No governed response record was found linked within this canonical-record scope.",
    "no_governed_characterisation_linked": "No governed characterisation record was found linked within this canonical-record scope.",
    "no_governed_decision_authority_linked": "Governed decision authority is unavailable within this projection schema.",
    "no_governed_mandate_linked": "Governed mandate authority is unavailable within this projection schema.",
    "no_governed_determination_linked": "No governed determination record was found linked within this canonical-record scope.",
    "no_governed_determination_reasons": "No governed reasons were recorded in the linked determination source.",
    "no_governed_challenge_linked": "Governed challenge authority is unavailable within this projection schema.",
    "no_governed_remedy_linked": "No governed remedy record was found linked within this Canonical Record scope.",
    "no_governed_implementation_event_linked": "No governed implementation or compliance event was found linked within this Canonical Record scope.",
    "no_governed_verification_linked": "No governed verification event was found linked within this Canonical Record scope.",
    "no_governed_formal_completion_determination_linked": "No governed formal-completion determination was found linked within this Canonical Record scope.",
    "no_governed_determination_publication_linked": "No governed determination-publication record was found linked within this Canonical Record scope.",
    "no_governed_notice_linked": "No governed notice record was found linked to this canonical record within the Stage 78A scope.",
    "no_evidenced_receipt_notice_in_scope": "No evidenced-receipt notice was found within this projection scope.",
    "no_governed_deadline_linked": "No governed deadline record was found linked to this canonical record within the Stage 78A scope.",
    "no_governed_deadline_calculation": "No governed deadline calculation was found for this included deadline.",
    "no_governed_pathway_link_in_scope": "No governed pathway link was found within this projection scope.",
}

__all__ = ["PROJECTION_CONTRACT", "PROJECTION_VERSION", "project_pathway"]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _schema_state(conn: sqlite3.Connection, tables: tuple[str, ...]) -> tuple[bool, bool]:
    present = [name for name in tables if _table_exists(conn, name)]
    return bool(present), len(present) == len(tables)


def _is_exact_date(text: str) -> bool:
    if len(text) != 10:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _is_timestamp(text: str) -> bool:
    if len(text) <= 10:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _parse_interval(value: Any) -> tuple[str, str, str | None, str | None]:
    """Derive ordering bounds from a represented value without inventing time.

    Returns ``(chronology_basis, chronology_precision, lower, upper)``.  Where
    the represented value cannot be parsed into authoritative bounds, no bounds
    are invented and the basis reports ``unavailable``.
    """

    if value in (None, ""):
        return ("unavailable", "unavailable", None, None)
    text = str(value).strip()
    if "/" in text:
        parts = [part.strip() for part in text.split("/", 1)]
        if len(parts) == 2 and all(
            _is_exact_date(part) or _is_timestamp(part) for part in parts
        ):
            lower, upper = parts[0][:10], parts[1][:10]
            if lower <= upper:
                return ("represented_period", "period", lower, upper)
        return ("unavailable", "unavailable", None, None)
    if _is_timestamp(text):
        return ("represented_timestamp", "timestamp", text[:10], text[:10])
    if _is_exact_date(text):
        return ("represented_date", "exact_date", text, text)
    month = _MONTH_RE.match(text)
    if month:
        year, mon = int(month.group(1)), int(month.group(2))
        if 1 <= mon <= 12:
            last = monthrange(year, mon)[1]
            return ("represented_date", "month", f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}")
    year = _YEAR_RE.match(text)
    if year:
        y = int(year.group(1))
        return ("represented_date", "year", f"{y:04d}-01-01", f"{y:04d}-12-31")
    return ("unavailable", "unavailable", None, None)


def _recording_only(recorded_at: Any) -> tuple[str, str, str | None, str | None]:
    return ("recording_time_only", "recording_time", None, None)


def _binding_view(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "binding_role": row["binding_role"],
        "source_version": row["source_version"],
        "source_timestamp": row["source_timestamp"],
    }


def _logical_identity(conn: sqlite3.Connection | None, kind: str, ident: Any) -> str | None:
    if kind == "canonical_record":
        return f"canonical_record:{ident}"
    table_by_kind = {
        "accepted_pattern_observation": "record_pattern_observations",
        OBJECT_KIND_OBSERVATION: "record_pattern_observations",
        "notice": "record_governed_procedural_notices",
        OBJECT_KIND_NOTICE: "record_governed_procedural_notices",
        "deadline": "record_governed_procedural_deadlines",
        OBJECT_KIND_DEADLINE: "record_governed_procedural_deadlines",
        "event": "record_governed_procedural_time_events",
        OBJECT_KIND_EVENT: "record_governed_procedural_time_events",
        "calculation": "record_governed_deadline_calculations",
        OBJECT_KIND_CALCULATION: "record_governed_deadline_calculations",
        OBJECT_KIND_INFERENCE: "record_governed_inferences",
        OBJECT_KIND_ALLEGATION: "record_governed_allegations",
        OBJECT_KIND_RESPONSE: "record_governed_responses",
        OBJECT_KIND_CHARACTERISATION: "record_governed_characterisations",
        OBJECT_KIND_PATHWAY_LINK: "record_governed_pathway_links",
        OBJECT_KIND_AUTHORITY: "record_governed_decision_authorities",
        "decision_authority": "record_governed_decision_authorities",
        OBJECT_KIND_MANDATE: "record_governed_decision_authority_mandates",
        "decision_mandate": "record_governed_decision_authority_mandates",
        OBJECT_KIND_DETERMINATION: "record_governed_determinations",
        "governed_determination": "record_governed_determinations",
        OBJECT_KIND_CHALLENGE: "record_governed_challenge_proceedings",
        "governed_challenge": "record_governed_challenge_proceedings",
        OBJECT_KIND_REMEDY: "record_governed_remedies",
        "governed_remedy": "record_governed_remedies",
        OBJECT_KIND_IMPLEMENTATION_EVENT: "record_governed_implementation_events",
        "implementation_event": "record_governed_implementation_events",
        OBJECT_KIND_FORMAL_COMPLETION: "record_governed_determinations",
        OBJECT_KIND_DETERMINATION_PUBLICATION: "record_governed_determination_publications",
        "determination_publication": "record_governed_determination_publications",
    }
    table = table_by_kind.get(kind)
    if conn is None or table is None:
        return f"{kind}:{ident}"
    found = conn.execute(f"SELECT idempotency_key FROM {table} WHERE id=?", (ident,)).fetchone()
    if found is None:
        return f"{kind}:{ident}"
    return f"{kind}:{found['idempotency_key']}"


def _link_view(row: Mapping[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    object_type = row["object_type"]
    object_id = row["object_id"]
    return {
        "object_type": object_type,
        "object_id": object_id,
        "object_governed_identity": _logical_identity(conn, str(object_type), object_id),
        "relationship_role": row["relationship_role"],
    }


def _label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _contestation(category: str) -> dict[str, Any]:
    if category in _DISPUTE_CATEGORIES:
        return {"status": "disputed_as_recorded", "representation": category}
    return {"status": "not_represented", "representation": None}


def _no_establishment(epistemic_label: str) -> dict[str, Any]:
    return {
        "epistemic_label": epistemic_label,
        "does_not_establish_truth": True,
        "does_not_establish_evidence": True,
        "does_not_establish_inference": True,
        "does_not_establish_fact": True,
        "does_not_establish_proof": True,
        "does_not_establish_finding": True,
        "does_not_establish_determination": True,
        "does_not_establish_legal_effect": True,
    }


def _record_review_state(reviews: list[Mapping[str, Any]], status_key: str = "status") -> dict[str, Any]:
    return {
        "review_count": len(reviews),
        "latest_review": None if not reviews else str(reviews[-1].get(status_key)),
        "history": [dict(item) for item in reviews],
    }


def _empty_supersession() -> dict[str, Any]:
    return {
        "superseded": False,
        "replacement": None,
        "review_history": [],
        "supersession_history": [],
    }


def _stage71_history(conn: sqlite3.Connection, kind: str, ident: int) -> dict[str, Any]:
    reviews = [
        {
            "disposition": row["disposition"],
            "reviewer": row["reviewer"],
            "reviewed_at": row["reviewed_at"],
            "idempotency_key": row["idempotency_key"],
        }
        for row in conn.execute(
            "SELECT disposition, reviewer, reviewed_at, idempotency_key "
            "FROM record_governed_procedural_time_reviews "
            "WHERE target_kind=? AND target_id=?",
            (kind, ident),
        ).fetchall()
    ]
    reviews.sort(key=lambda item: (str(item["reviewed_at"] or ""), str(item["idempotency_key"])))
    history = []
    for row in conn.execute(
        "SELECT replacement_kind, replacement_id, occurred_at, idempotency_key "
        "FROM record_governed_procedural_time_supersessions "
        "WHERE target_kind=? AND target_id=?",
        (kind, ident),
    ).fetchall():
        table = (
            "record_governed_procedural_notices"
            if row["replacement_kind"] == "notice"
            else "record_governed_procedural_deadlines"
        )
        replacement = conn.execute(
            f"SELECT idempotency_key FROM {table} WHERE id=?", (row["replacement_id"],)
        ).fetchone()
        history.append(
            {
                "replacement_object_kind": row["replacement_kind"],
                "replacement_governed_digest": replacement[0] if replacement else None,
                "occurred_at": row["occurred_at"],
                "idempotency_key": row["idempotency_key"],
            }
        )
    history.sort(key=lambda item: (str(item["occurred_at"] or ""), str(item["idempotency_key"])))
    superseded = bool(history)
    replacement = history[-1] if superseded else None
    return {
        "superseded": superseded,
        "replacement": replacement,
        "review_history": reviews,
        "supersession_history": history,
    }


def _stage72_history(conn: sqlite3.Connection, link_id: int) -> dict[str, Any]:
    reviews = [
        {
            "disposition": row["disposition"],
            "reviewer": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"],
            "idempotency_key": row["idempotency_key"],
        }
        for row in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_at, idempotency_key "
            "FROM record_governed_pathway_reviews WHERE pathway_link_id=?",
            (link_id,),
        ).fetchall()
    ]
    reviews.sort(key=lambda item: (str(item["reviewed_at"] or ""), str(item["idempotency_key"])))
    history = []
    for row in conn.execute(
        "SELECT replacement_link_id, occurred_at, idempotency_key "
        "FROM record_governed_pathway_supersessions WHERE pathway_link_id=?",
        (link_id,),
    ).fetchall():
        replacement = conn.execute(
            "SELECT idempotency_key FROM record_governed_pathway_links WHERE id=?",
            (row["replacement_link_id"],),
        ).fetchone()
        history.append(
            {
                "replacement_object_kind": "pathway_link",
                "replacement_governed_digest": replacement[0] if replacement else None,
                "occurred_at": row["occurred_at"],
                "idempotency_key": row["idempotency_key"],
            }
        )
    history.sort(key=lambda item: (str(item["occurred_at"] or ""), str(item["idempotency_key"])))
    superseded = bool(history)
    return {
        "superseded": superseded,
        "replacement": history[-1] if superseded else None,
        "review_history": reviews,
        "supersession_history": history,
    }


def _base_row(
    *,
    object_kind: str,
    object_id: Any,
    parent_kind: str | None,
    parent_id: Any,
    parent_governed_identity: str | None,
    category: str,
    status: str | None,
    represented_time: str | None,
    recorded_at: Any,
    chronology: tuple[str, str, str | None, str | None],
    ownership_path: str,
    source_bindings: list[dict[str, Any]],
    object_links: list[dict[str, Any]],
    contestation: dict[str, Any],
    supersession: dict[str, Any],
    governed_digest: str,
    display_label: str,
    limitations: Any,
    reliance: dict[str, Any] | None,
    epistemic_label: str | None = None,
    attribution: dict[str, Any] | None = None,
    representation_mode: str | None = None,
    review_state: dict[str, Any] | None = None,
    contrary_sources: list[dict[str, Any]] | None = None,
    does_not_establish: dict[str, Any] | None = None,
) -> dict[str, Any]:
    basis, precision, lower, upper = chronology
    return {
        "object_kind": object_kind,
        "object_id": str(object_id),
        "parent_kind": parent_kind,
        "parent_id": None if parent_id is None else str(parent_id),
        "parent_governed_identity": parent_governed_identity,
        "category": category,
        "status": status,
        "represented_time": represented_time,
        "recorded_at": str(recorded_at) if recorded_at is not None else None,
        "chronology_basis": basis,
        "chronology_precision": precision,
        "chronology_lower_bound": lower,
        "chronology_upper_bound": upper,
        "ordering_relation": "determinate",
        "ownership_path": ownership_path,
        "source_bindings": source_bindings,
        "object_links": object_links,
        "contestation": contestation,
        "supersession": supersession,
        "governed_digest": governed_digest,
        "display_label": display_label,
        "limitations": limitations,
        "reliance": reliance,
        "epistemic_label": epistemic_label,
        "attribution": attribution,
        "representation_mode": representation_mode,
        "review_state": review_state,
        "contrary_sources": contrary_sources or [],
        "does_not_establish": does_not_establish,
    }


def _notice_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    return _base_row(
        object_kind=OBJECT_KIND_NOTICE,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["notice_category"]),
        status=procedural._status(conn, "notice", ident, str(row["status"])),
        represented_time=row["issue_date_or_period"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["issue_date_or_period"]),
        ownership_path="stage71.object_link(notice_concerns->canonical_record)",
        source_bindings=[
            _binding_view(item)
            for item in conn.execute(
                "SELECT * FROM record_governed_procedural_time_bindings "
                "WHERE record_kind='notice' AND record_id=? "
                "ORDER BY source_type, source_id, binding_role",
                (ident,),
            ).fetchall()
        ],
        object_links=[
            _link_view(item)
            for item in conn.execute(
                "SELECT * FROM record_governed_procedural_time_object_links "
                "WHERE record_kind='notice' AND record_id=? "
                "ORDER BY object_type, object_id, relationship_role",
                (ident,),
            ).fetchall()
        ],
        contestation=_contestation(str(row["notice_category"])),
        supersession=_stage71_history(conn, "notice", ident),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['notice_category']))} · {row['title_label']}",
        limitations=row["limitations"],
        reliance=None,
    )


def _deadline_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    return _base_row(
        object_kind=OBJECT_KIND_DEADLINE,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["deadline_category"]),
        status=procedural._status(conn, "deadline", ident, str(row["status"])),
        represented_time=row["deadline_date_or_period"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["deadline_date_or_period"]),
        ownership_path="stage71.object_link(deadline_applies_to->canonical_record)",
        source_bindings=[
            _binding_view(item)
            for item in conn.execute(
                "SELECT * FROM record_governed_procedural_time_bindings "
                "WHERE record_kind='deadline' AND record_id=? "
                "ORDER BY source_type, source_id, binding_role",
                (ident,),
            ).fetchall()
        ],
        object_links=[
            _link_view(item)
            for item in conn.execute(
                "SELECT * FROM record_governed_procedural_time_object_links "
                "WHERE record_kind='deadline' AND record_id=? "
                "ORDER BY object_type, object_id, relationship_role",
                (ident,),
            ).fetchall()
        ],
        contestation=_contestation(str(row["deadline_category"])),
        supersession=_stage71_history(conn, "deadline", ident),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['deadline_category']))} · {row['title_label']}",
        limitations=row["limitations"],
        reliance=None,
    )


def _event_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    parent_kind = str(row["parent_kind"])
    links: list[dict[str, Any]] = []
    try:
        payload = json.loads(row["request_payload_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict) and isinstance(payload.get("subject_links"), list):
        links = [
            _link_view(item)
            for item in payload["subject_links"]
            if isinstance(item, Mapping) and {"object_type", "object_id", "relationship_role"} <= set(item)
        ]
    links.sort(key=lambda item: (item["object_type"], str(item["object_id"]), item["relationship_role"]))
    ownership = (
        "stage71.parent(notice)+stage71.object_link(notice_concerns->canonical_record)"
        if parent_kind == "notice"
        else "stage71.parent(deadline)+stage71.object_link(deadline_applies_to->canonical_record)"
    )
    return _base_row(
        object_kind=OBJECT_KIND_EVENT,
        object_id=ident,
        parent_kind=parent_kind,
        parent_id=int(row["parent_id"]),
        parent_governed_identity=_logical_identity(conn, parent_kind, row["parent_id"]),
        category=str(row["event_category"]),
        status=str(row["status"]),
        represented_time=row["represented_date_or_period"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["represented_date_or_period"]),
        ownership_path=ownership,
        source_bindings=[
            _binding_view(item)
            for item in conn.execute(
                "SELECT * FROM record_governed_procedural_time_bindings "
                "WHERE record_kind='event' AND record_id=? "
                "ORDER BY source_type, source_id, binding_role",
                (ident,),
            ).fetchall()
        ],
        object_links=links,
        contestation=_contestation(str(row["event_category"])),
        supersession=_empty_supersession(),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['event_category']))} · {row['actor_label']}",
        limitations=row["limitations"],
        reliance=None,
    )


def _calculation_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    calculated = str(row["calculated_deadline"])[:10]
    chronology = ("calculated_deadline", "exact_date", calculated, calculated) if _is_exact_date(calculated) else ("unavailable", "unavailable", None, None)
    return _base_row(
        object_kind=OBJECT_KIND_CALCULATION,
        object_id=int(row["id"]),
        parent_kind="deadline",
        parent_id=int(row["deadline_id"]),
        parent_governed_identity=_logical_identity(conn, "deadline", row["deadline_id"]),
        category=str(row["result_category"]),
        status=None,
        represented_time=str(row["calculated_deadline"]),
        recorded_at=row["calculated_at"],
        chronology=chronology,
        ownership_path="stage71.parent(deadline)+stage71.object_link(deadline_applies_to->canonical_record)",
        source_bindings=[],
        object_links=[],
        contestation={"status": "not_represented", "representation": None},
        supersession=_empty_supersession(),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"Deadline calculation ({row['calculation_mode']}) · {_label(str(row['result_category']))}",
        limitations=procedural.CALCULATION_BOUNDARY,
        reliance=None,
    )


def _pathway_row(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
    ownership_path: str,
) -> dict[str, Any]:
    ident = int(row["id"])
    return _base_row(
        object_kind=OBJECT_KIND_PATHWAY_LINK,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["relationship_type"]),
        status=pathway._status(conn, ident, str(row["status"])),
        represented_time=None,
        recorded_at=row["created_at"],
        chronology=_recording_only(row["created_at"]),
        ownership_path=ownership_path,
        source_bindings=[
            _binding_view(item)
            for item in conn.execute(
                "SELECT * FROM record_governed_pathway_bindings "
                "WHERE pathway_link_id=? ORDER BY source_type, source_id, binding_role",
                (ident,),
            ).fetchall()
        ],
        object_links=[
            {
                "object_type": row["source_object_kind"],
                "object_id": row["source_object_id"],
                "object_governed_identity": _logical_identity(conn, str(row["source_object_kind"]), row["source_object_id"]),
                "relationship_role": "source_endpoint",
            },
            {
                "object_type": row["target_object_kind"],
                "object_id": row["target_object_id"],
                "object_governed_identity": _logical_identity(conn, str(row["target_object_kind"]), row["target_object_id"]),
                "relationship_role": "target_endpoint",
            },
        ],
        contestation={
            "status": str(row["contestation_status"]),
            "representation": row["contestation_representation"],
        },
        supersession=_stage72_history(conn, ident),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['relationship_type']))} · {row['source_object_kind']}->{row['target_object_kind']}",
        limitations=row["limitations"],
        reliance={
            "status": str(row["reliance_status"]),
            "description": row["reliance_description"],
        },
    )


def _bindings_for(
    conn: sqlite3.Connection,
    table: str,
    id_column: str,
    ident: int,
) -> list[dict[str, Any]]:
    return [
        _binding_view(item)
        for item in conn.execute(
            f"SELECT source_type, source_id, binding_role, source_version, source_timestamp "
            f"FROM {table} WHERE {id_column}=? ORDER BY source_type, source_id, binding_role",
            (ident,),
        ).fetchall()
    ]


def _contrary_sources(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        binding for binding in bindings
        if str(binding["binding_role"]).startswith("contrary_")
    ]


def _observation_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = [
        {
            "source_type": "record_document_association",
            "source_id": str(item["association_id"]),
            "binding_role": "observed_relationship_source",
            "source_version": None,
            "source_timestamp": item["source_created_at"],
            "record_reference": item["record_reference"],
            "relationship_type": item["relationship_type"],
        }
        for item in conn.execute(
            "SELECT association_id, record_reference, relationship_type, source_created_at "
            "FROM record_pattern_observation_bindings WHERE observation_id=? "
            "ORDER BY source_created_at, association_id",
            (ident,),
        ).fetchall()
    ]
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT status, reviewed_at, reviewed_by, rationale "
            "FROM record_pattern_observation_reviews WHERE observation_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    return _base_row(
        object_kind=OBJECT_KIND_OBSERVATION,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["observation_type"]),
        status=str(row["status"]),
        represented_time=None,
        recorded_at=row["created_at"],
        chronology=("unavailable", "unavailable", None, None),
        ownership_path="stage62.record_pattern_observation_bindings(record_reference=canonical_record)",
        source_bindings=bindings,
        object_links=[
            {
                "object_type": "canonical_record",
                "object_id": item["record_reference"],
                "object_governed_identity": f"canonical_record:{item['record_reference']}",
                "relationship_role": "observation_scope",
            }
            for item in bindings
        ],
        contestation={"status": "not_represented", "representation": None},
        supersession=_empty_supersession(),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['observation_type']))} · {row['title']}",
        limitations="Observation only; no inference, allegation, finding or determination is established.",
        reliance=None,
        epistemic_label="observation",
        attribution={"created_by": row["created_by"], "authoring_mode": "governed_observation"},
        review_state=_record_review_state(reviews),
        does_not_establish=_no_establishment("observation"),
    )


def _inference_supersession(conn: sqlite3.Connection, ident: int) -> dict[str, Any]:
    history = []
    for item in conn.execute(
        "SELECT replacement_inference_id, event_type, rationale, actor, actor_role, occurred_at, "
        "evidence_references_json, idempotency_key FROM record_governed_inference_supersessions "
        "WHERE inference_id=? ORDER BY occurred_at, id",
        (ident,),
    ).fetchall():
        replacement = None
        if item["replacement_inference_id"] is not None:
            replacement = _logical_identity(conn, OBJECT_KIND_INFERENCE, item["replacement_inference_id"])
        history.append(
            {
                "replacement_object_kind": OBJECT_KIND_INFERENCE,
                "replacement_governed_identity": replacement,
                "event_type": item["event_type"],
                "occurred_at": item["occurred_at"],
                "idempotency_key": item["idempotency_key"],
                "evidence_references": json.loads(item["evidence_references_json"] or "[]"),
            }
        )
    return {
        "superseded": bool(history),
        "replacement": history[-1] if history else None,
        "review_history": [],
        "supersession_history": history,
    }


def _inference_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_inference_bindings", "inference_id", ident)
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT status, reviewed_at, reviewed_by, reviewed_by_role, rationale, "
            "contrary_evidence_note, idempotency_key FROM record_governed_inference_reviews "
            "WHERE inference_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    status = inferences._current_status(conn, ident, str(row["status"]))
    supersession = _inference_supersession(conn, ident)
    supersession["review_history"] = reviews
    return _base_row(
        object_kind=OBJECT_KIND_INFERENCE,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["inference_type"]),
        status=status,
        represented_time=None,
        recorded_at=row["created_at"],
        chronology=("unavailable", "unavailable", None, None),
        ownership_path="stage63.canonical_record_source_binding",
        source_bindings=bindings,
        object_links=[
            {
                "object_type": binding["source_type"],
                "object_id": binding["source_id"],
                "object_governed_identity": _logical_identity(conn, binding["source_type"], binding["source_id"]),
                "relationship_role": binding["binding_role"],
            }
            for binding in bindings
        ],
        contestation={"status": "not_represented", "representation": None},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['inference_type']))} · inference",
        limitations=row["qualification"],
        reliance=None,
        epistemic_label="inference",
        attribution={"created_by": row["created_by"], "created_by_role": row["created_by_role"]},
        review_state=_record_review_state(reviews),
        contrary_sources=_contrary_sources(bindings),
        does_not_establish=_no_establishment("inference"),
    )


def _allegation_history(conn: sqlite3.Connection, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_allegation_reviews WHERE allegation_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_ALLEGATION,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_ALLEGATION, item["replacement_allegation_id"]),
            "event_type": item["event_type"],
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_allegation_id, event_type, occurred_at, idempotency_key "
            "FROM record_governed_allegation_supersessions WHERE allegation_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    withdrawals = [
        dict(item)
        for item in conn.execute(
            "SELECT withdrawal_type, rationale, actor, actor_role, occurred_at, idempotency_key "
            "FROM record_governed_allegation_withdrawals WHERE allegation_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
        "withdrawal_history": withdrawals,
        "withdrawn": bool(withdrawals),
    }
    return supersession, _record_review_state(reviews, "disposition")


def _allegation_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_allegation_bindings", "allegation_id", ident)
    status = allegations._event_status(conn, ident, str(row["status"]))
    supersession, review_state = _allegation_history(conn, ident)
    chronology = _parse_interval(row["alleged_period"] or row["made_or_recorded_at"])
    return _base_row(
        object_kind=OBJECT_KIND_ALLEGATION,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["allegation_category"]),
        status=status,
        represented_time=row["alleged_period"] or row["made_or_recorded_at"],
        recorded_at=row["created_at"],
        chronology=chronology,
        ownership_path="stage64.canonical_record_source_binding",
        source_bindings=bindings,
        object_links=[
            {
                "object_type": binding["source_type"],
                "object_id": binding["source_id"],
                "object_governed_identity": _logical_identity(conn, binding["source_type"], binding["source_id"]),
                "relationship_role": binding["binding_role"],
            }
            for binding in bindings
        ],
        contestation={"status": "attributed_proposition_only", "representation": row["representation_mode"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['allegation_category']))} · allegation",
        limitations=row["limitations"],
        reliance=None,
        epistemic_label="allegation",
        attribution={
            "attributed_source_label": row["attributed_source_label"],
            "attribution_context": row["attribution_context"],
        },
        representation_mode=str(row["representation_mode"]),
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish=_no_establishment("allegation"),
    )


def _response_history(conn: sqlite3.Connection, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_response_reviews WHERE response_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_RESPONSE,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_RESPONSE, item["replacement_response_id"]),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_response_id, occurred_at, idempotency_key "
            "FROM record_governed_response_supersessions WHERE response_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    withdrawals = [
        dict(item)
        for item in conn.execute(
            "SELECT withdrawal_type, rationale, actor, actor_role, occurred_at, idempotency_key "
            "FROM record_governed_response_withdrawals WHERE response_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
        "withdrawal_history": withdrawals,
        "withdrawn": bool(withdrawals),
    }
    return supersession, _record_review_state(reviews, "disposition")


def _response_row(conn: sqlite3.Connection, row: Mapping[str, Any], allegation_id: int) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_response_bindings", "response_id", ident)
    status = responses._status(conn, ident, str(row["status"]))
    supersession, review_state = _response_history(conn, ident)
    return _base_row(
        object_kind=OBJECT_KIND_RESPONSE,
        object_id=ident,
        parent_kind=OBJECT_KIND_ALLEGATION,
        parent_id=allegation_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_ALLEGATION, allegation_id),
        category=str(row["response_category"]),
        status=status,
        represented_time=row["response_period"] or row["recorded_at"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["response_period"] or row["recorded_at"]),
        ownership_path="stage65.allegation_link+canonical_record_source_binding",
        source_bindings=bindings,
        object_links=[
            {
                "object_type": OBJECT_KIND_ALLEGATION,
                "object_id": str(allegation_id),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_ALLEGATION, allegation_id),
                "relationship_role": "responds_to_allegation",
            },
            *[
                {
                    "object_type": binding["source_type"],
                    "object_id": binding["source_id"],
                    "object_governed_identity": _logical_identity(conn, binding["source_type"], binding["source_id"]),
                    "relationship_role": binding["binding_role"],
                }
                for binding in bindings
            ],
        ],
        contestation={"status": "response_not_resolution", "representation": row["response_category"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['response_category']))} · response",
        limitations=row["limitations"],
        reliance=None,
        epistemic_label="response",
        attribution={
            "attributed_respondent_label": row["attributed_respondent_label"],
            "attribution_context": row["attribution_context"],
            "respondent_capacity": row["respondent_capacity"],
        },
        representation_mode=str(row["representation_mode"]),
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={**_no_establishment("response"), "does_not_resolve_allegation": True},
    )


def _characterisation_row(conn: sqlite3.Connection, row: Mapping[str, Any], ownership_path: str) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_characterisation_bindings", "characterisation_id", ident)
    refs = [
        dict(item)
        for item in conn.execute(
            "SELECT object_kind, object_id, relationship_role "
            "FROM record_governed_characterisation_references WHERE characterisation_id=? "
            "ORDER BY object_kind, object_id, relationship_role",
            (ident,),
        ).fetchall()
    ]
    events = [
        dict(item)
        for item in conn.execute(
            "SELECT event_type, resulting_status, rationale, occurred_at, idempotency_key, replacement_id "
            "FROM record_governed_characterisation_events WHERE characterisation_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_CHARACTERISATION,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_CHARACTERISATION, item["replacement_id"]),
            "event_type": item["event_type"],
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in events
        if item["event_type"] == "superseded" and item["replacement_id"] is not None
    ]
    return _base_row(
        object_kind=OBJECT_KIND_CHARACTERISATION,
        object_id=ident,
        parent_kind=str(row["primary_object_kind"]),
        parent_id=row["primary_object_id"],
        parent_governed_identity=_logical_identity(conn, str(row["primary_object_kind"]), row["primary_object_id"]),
        category=str(row["term_code"]),
        status=str(row["lifecycle_status"]),
        represented_time=None,
        recorded_at=row["created_at"],
        chronology=("unavailable", "unavailable", None, None),
        ownership_path=ownership_path,
        source_bindings=bindings,
        object_links=[
            {
                "object_type": item["object_kind"],
                "object_id": item["object_id"],
                "object_governed_identity": _logical_identity(conn, item["object_kind"], item["object_id"]),
                "relationship_role": item["relationship_role"],
            }
            for item in refs
        ],
        contestation={"status": str(row["lifecycle_status"]), "representation": row["epistemic_basis"]},
        supersession={
            "superseded": bool(supersessions),
            "replacement": supersessions[-1] if supersessions else None,
            "review_history": events,
            "supersession_history": supersessions,
        },
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{characterisations.vocabulary(str(row['term_code']), str(row['vocabulary_version']))['display_label']} · characterisation",
        limitations=row["limitations"],
        reliance=None,
        epistemic_label="characterisation",
        attribution={
            "attribution_kind": row["attribution_kind"],
            "attributed_label": row["attributed_label"],
            "attribution_source_type": row["attribution_source_type"],
            "attribution_source_id": row["attribution_source_id"],
            "external_source_description": row["external_source_description"],
        },
        representation_mode=str(row["representation_mode"]),
        review_state=_record_review_state(events, "resulting_status"),
        contrary_sources=_contrary_sources(bindings),
        does_not_establish=_no_establishment("characterisation"),
    )


def _stage66_history(conn: sqlite3.Connection, object_type: str, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_decision_authority_reviews WHERE "
            + ("authority_id=? AND mandate_id IS NULL" if object_type == "authority" else "mandate_id=?")
            + " ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_AUTHORITY if object_type == "authority" else OBJECT_KIND_MANDATE,
            "replacement_governed_identity": _logical_identity(
                conn,
                OBJECT_KIND_AUTHORITY if object_type == "authority" else OBJECT_KIND_MANDATE,
                item["replacement_id"],
            ),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_id, occurred_at, idempotency_key "
            "FROM record_governed_decision_authority_supersessions "
            "WHERE object_type=? AND object_id=? ORDER BY occurred_at, id",
            (object_type, ident),
        ).fetchall()
    ]
    cessations = [
        dict(item)
        for item in conn.execute(
            "SELECT cessation_type, cessation_date_or_period, rationale, actor, actor_role, occurred_at, idempotency_key "
            "FROM record_governed_decision_authority_cessations "
            "WHERE object_type=? AND object_id=? ORDER BY occurred_at, id",
            (object_type, ident),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
        "cessation_history": cessations,
        "ceased": bool(cessations),
    }
    return supersession, _record_review_state(reviews, "disposition")


def _authority_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = [
        _binding_view(item)
        for item in conn.execute(
            "SELECT source_type, source_id, binding_role, source_version, source_timestamp "
            "FROM record_governed_decision_authority_bindings "
            "WHERE object_type='authority' AND object_id=? ORDER BY source_type, source_id, binding_role",
            (ident,),
        ).fetchall()
    ]
    supersession, review_state = _stage66_history(conn, "authority", ident)
    return _base_row(
        object_kind=OBJECT_KIND_AUTHORITY,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["holder_kind"]),
        status=authorities._status(conn, "authority", ident, str(row["status"])),
        represented_time=row["holder_effective_period"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["holder_effective_period"]),
        ownership_path="stage66.authority_binding(canonical_record)",
        source_bindings=bindings,
        object_links=[
            {
                "object_type": binding["source_type"],
                "object_id": binding["source_id"],
                "object_governed_identity": _logical_identity(conn, binding["source_type"], binding["source_id"]),
                "relationship_role": binding["binding_role"],
            }
            for binding in bindings
        ],
        contestation={"status": "source_backed_representation_only", "representation": row["holder_kind"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{row['holder_label']} · decision authority",
        limitations=row["limitations"],
        reliance=None,
        epistemic_label="decision_authority",
        attribution={
            "holder_label": row["holder_label"],
            "institution_context": row["institution_context"],
            "office_role_capacity": row["office_role_capacity"],
            "named_holder": row["named_holder"],
            "attribution_context": row["attribution_context"],
        },
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={**_no_establishment("decision_authority"), "does_not_establish_jurisdiction": True, "does_not_establish_lawfulness": True},
    )


def _mandate_row(conn: sqlite3.Connection, row: Mapping[str, Any], ownership_path: str) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = [
        _binding_view(item)
        for item in conn.execute(
            "SELECT source_type, source_id, binding_role, source_version, source_timestamp "
            "FROM record_governed_decision_authority_bindings "
            "WHERE object_type='mandate' AND object_id=? ORDER BY source_type, source_id, binding_role",
            (ident,),
        ).fetchall()
    ]
    supersession, review_state = _stage66_history(conn, "mandate", ident)
    represented = None
    if row["effective_from"] or row["effective_to"]:
        represented = f"{row['effective_from'] or ''}/{row['effective_to'] or ''}"
    return _base_row(
        object_kind=OBJECT_KIND_MANDATE,
        object_id=ident,
        parent_kind=OBJECT_KIND_AUTHORITY,
        parent_id=int(row["authority_id"]),
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_AUTHORITY, row["authority_id"]),
        category=str(row["mandate_basis_category"]),
        status=authorities._status(conn, "mandate", ident, str(row["status"])),
        represented_time=represented,
        recorded_at=row["created_at"],
        chronology=_parse_interval(represented),
        ownership_path=ownership_path,
        source_bindings=bindings,
        object_links=[
            {
                "object_type": binding["source_type"],
                "object_id": binding["source_id"],
                "object_governed_identity": _logical_identity(conn, binding["source_type"], binding["source_id"]),
                "relationship_role": binding["binding_role"],
            }
            for binding in bindings
        ],
        contestation={"status": "mandate_record_only", "representation": row["mandate_basis_category"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['mandate_basis_category']))} · {row['title_label']}",
        limitations=row["limitations"],
        reliance=None,
        epistemic_label="mandate",
        attribution={
            "subject_matter_scope": row["subject_matter_scope"],
            "procedural_scope": row["procedural_scope"],
            "territorial_organisational_scope": row["territorial_organisational_scope"],
            "affected_class": row["affected_class"],
            "delegation_status": row["delegation_status"],
            "delegating_authority_identity": None if row["delegating_authority_id"] is None else _logical_identity(conn, OBJECT_KIND_AUTHORITY, row["delegating_authority_id"]),
            "delegating_mandate_identity": None if row["delegating_mandate_id"] is None else _logical_identity(conn, OBJECT_KIND_MANDATE, row["delegating_mandate_id"]),
            "express_limitations": row["express_limitations"],
            "conditions_prerequisites": row["conditions_prerequisites"],
        },
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={**_no_establishment("mandate"), "does_not_establish_jurisdiction": True, "does_not_establish_lawfulness": True},
    )


def _determination_history(conn: sqlite3.Connection, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_determination_reviews WHERE determination_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_DETERMINATION,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION, item["replacement_determination_id"]),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_determination_id, occurred_at, idempotency_key "
            "FROM record_governed_determination_supersessions WHERE determination_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
    }
    return supersession, _record_review_state(reviews, "disposition")


def _determination_row(conn: sqlite3.Connection, row: Mapping[str, Any], ownership_path: str) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_determination_bindings", "determination_id", ident)
    links = [
        {
            "object_type": item["object_type"],
            "object_id": str(item["object_id"]),
            "object_governed_identity": _logical_identity(conn, item["object_type"], item["object_id"]),
            "relationship_role": item["relationship_role"],
        }
        for item in conn.execute(
            "SELECT object_type, object_id, relationship_role "
            "FROM record_governed_determination_governed_object_links "
            "WHERE determination_id=? ORDER BY object_type, object_id, relationship_role",
            (ident,),
        ).fetchall()
    ]
    authority_link = conn.execute(
        "SELECT authority_id, mandate_id FROM record_governed_determination_authority_links "
        "WHERE determination_id=?",
        (ident,),
    ).fetchone()
    if authority_link is not None:
        links.extend(
            [
                {
                    "object_type": OBJECT_KIND_AUTHORITY,
                    "object_id": str(authority_link["authority_id"]),
                    "object_governed_identity": _logical_identity(conn, OBJECT_KIND_AUTHORITY, authority_link["authority_id"]),
                    "relationship_role": "attributed_decision_authority",
                },
                {
                    "object_type": OBJECT_KIND_MANDATE,
                    "object_id": str(authority_link["mandate_id"]),
                    "object_governed_identity": _logical_identity(conn, OBJECT_KIND_MANDATE, authority_link["mandate_id"]),
                    "relationship_role": "attributed_decision_mandate",
                },
            ]
        )
    supersession, review_state = _determination_history(conn, ident)
    return _base_row(
        object_kind=OBJECT_KIND_DETERMINATION,
        object_id=ident,
        parent_kind=None,
        parent_id=None,
        parent_governed_identity=None,
        category=str(row["determination_category"]),
        status=determinations._status(conn, ident, str(row["status"])),
        represented_time=row["decision_date_or_period"],
        recorded_at=row["recorded_date"] or row["created_at"],
        chronology=_parse_interval(row["decision_date_or_period"]),
        ownership_path=ownership_path,
        source_bindings=bindings,
        object_links=links,
        contestation={"status": "attributed_determination_record_only", "representation": row["representation_mode"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['determination_category']))} · {row['title_label']}",
        limitations={
            "source_limitations": row["limitations"],
            "reasons": row["reasons"],
            "reasons_status": row["reasons_status"],
            "formal_outcome": row["formal_outcome"],
            "issues_determined": row["issues_determined"],
            "finality_description": row["finality_description"],
        },
        reliance={"status": "unavailable", "description": "Determination links do not establish express reliance unless separately governed."},
        epistemic_label="attributed_determination",
        representation_mode=str(row["representation_mode"]),
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={**_no_establishment("attributed_determination"), "does_not_establish_cde_endorsement": True, "does_not_establish_correctness": True},
    )


def _determination_effect_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    determination_id = int(row["determination_id"])
    payload = json.loads(row["request_payload_json"] or "{}")
    bindings = payload.get("bindings") if isinstance(payload, dict) else []
    if not isinstance(bindings, list):
        bindings = []
    return _base_row(
        object_kind=OBJECT_KIND_DETERMINATION_EFFECT,
        object_id=ident,
        parent_kind=OBJECT_KIND_DETERMINATION,
        parent_id=determination_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
        category=str(row["event_type"]),
        status="recorded",
        represented_time=row["represented_date_or_period"],
        recorded_at=row["occurred_at"],
        chronology=_parse_interval(row["represented_date_or_period"]),
        ownership_path="stage67.effect_event_parent(scoped_determination)",
        source_bindings=[dict(item) for item in bindings if isinstance(item, Mapping)],
        object_links=[
            {
                "object_type": OBJECT_KIND_DETERMINATION,
                "object_id": str(determination_id),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
                "relationship_role": "effect_event_parent",
            }
        ],
        contestation={"status": "effect_as_recorded_only", "representation": row["event_type"]},
        supersession=_empty_supersession(),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['event_type']))} · determination effect event",
        limitations=row["qualification"],
        reliance=None,
        epistemic_label="determination_effect_event",
        does_not_establish={**_no_establishment("determination_effect_event"), "does_not_alter_legal_effect_without_source": True},
    )


def _challenge_history(conn: sqlite3.Connection, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_challenge_reviews WHERE challenge_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_CHALLENGE,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_CHALLENGE, item["replacement_challenge_id"]),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_challenge_id, occurred_at, idempotency_key "
            "FROM record_governed_challenge_supersessions WHERE challenge_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
    }
    return supersession, _record_review_state(reviews, "disposition")


def _challenge_row(conn: sqlite3.Connection, row: Mapping[str, Any], determination_id: int) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_challenge_bindings", "challenge_id", ident)
    authority_link = conn.execute(
        "SELECT authority_id, mandate_id FROM record_governed_challenge_authority_links WHERE challenge_id=?",
        (ident,),
    ).fetchone()
    links = [
        {
            "object_type": OBJECT_KIND_DETERMINATION,
            "object_id": str(determination_id),
            "object_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
            "relationship_role": "target_determination",
        }
    ]
    if authority_link is not None:
        links.extend(
            [
                {
                    "object_type": OBJECT_KIND_AUTHORITY,
                    "object_id": str(authority_link["authority_id"]),
                    "object_governed_identity": _logical_identity(conn, OBJECT_KIND_AUTHORITY, authority_link["authority_id"]),
                    "relationship_role": "challenge_authority",
                },
                {
                    "object_type": OBJECT_KIND_MANDATE,
                    "object_id": str(authority_link["mandate_id"]),
                    "object_governed_identity": _logical_identity(conn, OBJECT_KIND_MANDATE, authority_link["mandate_id"]),
                    "relationship_role": "challenge_mandate",
                },
            ]
        )
    supersession, review_state = _challenge_history(conn, ident)
    return _base_row(
        object_kind=OBJECT_KIND_CHALLENGE,
        object_id=ident,
        parent_kind=OBJECT_KIND_DETERMINATION,
        parent_id=determination_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
        category=str(row["challenge_form"]),
        status=challenges._status(conn, ident, str(row["status"])),
        represented_time=row["filing_date_or_period"],
        recorded_at=row["recorded_date"] or row["created_at"],
        chronology=_parse_interval(row["filing_date_or_period"]),
        ownership_path="stage68.challenge_target(scoped_determination)",
        source_bindings=bindings,
        object_links=links,
        contestation={"status": "challenge_as_recorded_only", "representation": row["challenge_form"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['challenge_form']))} · {row['title_label']}",
        limitations={"source_limitations": row["limitations"], "grounds": row["grounds"], "procedural_status_at_creation": row["procedural_status_at_creation"]},
        reliance=None,
        epistemic_label="challenge_proceeding",
        attribution={
            "applicant_label": row["applicant_label"],
            "applicant_kind": row["applicant_kind"],
            "applicant_capacity": row["applicant_capacity"],
            "reviewing_forum_label": row["reviewing_forum_label"],
        },
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={**_no_establishment("challenge_proceeding"), "does_not_invalidate_determination": True, "does_not_suspend_determination": True},
    )


def _challenge_event_row(conn: sqlite3.Connection, row: Mapping[str, Any], challenge_id: int) -> dict[str, Any]:
    ident = int(row["id"])
    return _base_row(
        object_kind=OBJECT_KIND_CHALLENGE_EVENT,
        object_id=ident,
        parent_kind=OBJECT_KIND_CHALLENGE,
        parent_id=challenge_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_CHALLENGE, challenge_id),
        category=str(row["event_type"]),
        status="recorded",
        represented_time=row["event_date_or_period"],
        recorded_at=row["occurred_at"],
        chronology=_parse_interval(row["event_date_or_period"]),
        ownership_path="stage68.event_parent(scoped_challenge)",
        source_bindings=[
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "binding_role": "procedural_event_source",
                "source_version": None,
                "source_timestamp": None,
            }
        ],
        object_links=[
            {
                "object_type": OBJECT_KIND_CHALLENGE,
                "object_id": str(challenge_id),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_CHALLENGE, challenge_id),
                "relationship_role": "challenge_event_parent",
            }
        ],
        contestation={"status": "challenge_event_as_recorded_only", "representation": row["event_type"]},
        supersession=_empty_supersession(),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['event_type']))} · challenge event",
        limitations=row["rationale"],
        reliance=None,
        epistemic_label="challenge_event",
        does_not_establish={**_no_establishment("challenge_event"), "does_not_invalidate_determination": True},
    )


def _challenge_outcome_row(conn: sqlite3.Connection, row: Mapping[str, Any], challenge_id: int) -> dict[str, Any]:
    ident = int(row["id"])
    links = [
        {
            "object_type": OBJECT_KIND_CHALLENGE,
            "object_id": str(challenge_id),
            "object_governed_identity": _logical_identity(conn, OBJECT_KIND_CHALLENGE, challenge_id),
            "relationship_role": "challenge_outcome_parent",
        }
    ]
    if row["outcome_determination_id"] is not None:
        links.append(
            {
                "object_type": OBJECT_KIND_DETERMINATION,
                "object_id": str(row["outcome_determination_id"]),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION, row["outcome_determination_id"]),
                "relationship_role": "outcome_determination_as_recorded",
            }
        )
    return _base_row(
        object_kind=OBJECT_KIND_CHALLENGE_OUTCOME,
        object_id=ident,
        parent_kind=OBJECT_KIND_CHALLENGE,
        parent_id=challenge_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_CHALLENGE, challenge_id),
        category=str(row["outcome_type"]),
        status="recorded",
        represented_time=row["outcome_date_or_period"],
        recorded_at=row["recorded_at"],
        chronology=_parse_interval(row["outcome_date_or_period"]),
        ownership_path="stage68.outcome_parent(scoped_challenge)",
        source_bindings=[
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "binding_role": "outcome_source",
                "source_version": None,
                "source_timestamp": None,
            }
        ],
        object_links=links,
        contestation={"status": "challenge_outcome_as_recorded_only", "representation": row["outcome_type"]},
        supersession=_empty_supersession(),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['outcome_type']))} · challenge outcome",
        limitations={"outcome_text": row["outcome_text"], "rationale": row["rationale"]},
        reliance=None,
        epistemic_label="challenge_outcome",
        does_not_establish={**_no_establishment("challenge_outcome"), "does_not_invalidate_determination": True, "does_not_alter_legal_effect_without_source": True},
    )


def _stage69_history(conn: sqlite3.Connection, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_remedy_reviews WHERE remedy_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_REMEDY,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_REMEDY, item["replacement_remedy_id"]),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_remedy_id, occurred_at, idempotency_key "
            "FROM record_governed_remedy_supersessions WHERE remedy_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
    }
    return supersession, _record_review_state(reviews, "disposition")


def _remedy_row(conn: sqlite3.Connection, row: Mapping[str, Any], determination_id: int) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_remedy_bindings", "remedy_id", ident)
    supersession, review_state = _stage69_history(conn, ident)
    return _base_row(
        object_kind=OBJECT_KIND_REMEDY,
        object_id=ident,
        parent_kind=OBJECT_KIND_DETERMINATION,
        parent_id=determination_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
        category=str(row["remedy_category"]),
        status=remedies._status(conn, ident, str(row["status"])),
        represented_time=row["performance_period_or_deadline"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["performance_period_or_deadline"]),
        ownership_path="stage69.remedy_determination_link(scoped_determination)",
        source_bindings=bindings,
        object_links=[
            {
                "object_type": OBJECT_KIND_DETERMINATION,
                "object_id": str(determination_id),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
                "relationship_role": "remedy_source_determination",
            },
            *[
                {
                    "object_type": binding["source_type"],
                    "object_id": binding["source_id"],
                    "object_governed_identity": _logical_identity(conn, binding["source_type"], binding["source_id"]),
                    "relationship_role": binding["binding_role"],
                }
                for binding in bindings
            ],
        ],
        contestation={"status": "remedy_or_direction_as_recorded_only", "representation": row["direction_type"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['remedy_category']))} · {row['title_label']}",
        limitations={
            "source_limitations": row["limitations"],
            "direction_type": row["direction_type"],
            "beneficiary_or_affected_party": row["beneficiary_or_affected_party"],
            "obligated_party": row["obligated_party"],
            "conditions_prerequisites": row["conditions_prerequisites"],
            "scope": row["scope"],
            "implementation_description": row["implementation_description"],
        },
        reliance=None,
        epistemic_label="remedy_or_direction",
        attribution={
            "representation_mode": row["representation_mode"],
            "qualification": row["qualification"],
            "rationale": row["rationale"],
        },
        representation_mode=str(row["representation_mode"]),
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={
            **_no_establishment("remedy_or_direction"),
            "does_not_establish_implementation": True,
            "does_not_establish_compliance": True,
            "does_not_establish_completion": True,
        },
    )


def _stage70_history(conn: sqlite3.Connection, ident: int) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT disposition, reviewed_by, reviewed_by_role, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_implementation_event_reviews WHERE event_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_IMPLEMENTATION_EVENT,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_IMPLEMENTATION_EVENT, item["replacement_event_id"]),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_event_id, occurred_at, idempotency_key "
            "FROM record_governed_implementation_event_supersessions WHERE event_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersession = {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews,
        "supersession_history": supersessions,
    }
    return supersession, _record_review_state(reviews, "disposition")


def _implementation_event_row(conn: sqlite3.Connection, row: Mapping[str, Any], remedy_id: int) -> dict[str, Any]:
    ident = int(row["id"])
    bindings = _bindings_for(conn, "record_governed_implementation_event_bindings", "event_id", ident)
    object_links = [
        {
            "object_type": OBJECT_KIND_REMEDY,
            "object_id": str(remedy_id),
            "object_governed_identity": _logical_identity(conn, OBJECT_KIND_REMEDY, remedy_id),
            "relationship_role": "implementation_event_remedy",
        }
    ]
    object_links.extend(
        {
            "object_type": item["object_type"],
            "object_id": str(item["object_id"]),
            "object_governed_identity": _logical_identity(conn, item["object_type"], item["object_id"]),
            "relationship_role": item["relationship_role"],
        }
        for item in conn.execute(
            "SELECT object_type, object_id, relationship_role "
            "FROM record_governed_implementation_event_object_links WHERE event_id=? "
            "ORDER BY object_type, object_id, relationship_role",
            (ident,),
        ).fetchall()
    )
    supersession, review_state = _stage70_history(conn, ident)
    return _base_row(
        object_kind=OBJECT_KIND_IMPLEMENTATION_EVENT,
        object_id=ident,
        parent_kind=OBJECT_KIND_REMEDY,
        parent_id=remedy_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_REMEDY, remedy_id),
        category=str(row["event_category"]),
        status=implementation_events._status(conn, ident, str(row["status"])),
        represented_time=row["represented_event_date_or_period"],
        recorded_at=row["recorded_date"] or row["created_at"],
        chronology=_parse_interval(row["represented_event_date_or_period"]),
        ownership_path="stage70.implementation_event_remedy_link(scoped_remedy)",
        source_bindings=bindings,
        object_links=object_links,
        contestation={"status": "implementation_or_compliance_event_as_recorded_only", "representation": row["epistemic_basis"]},
        supersession=supersession,
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['event_category']))} · {row['title_label']}",
        limitations={
            "source_limitations": row["limitations"],
            "represented_amount_quantity_extent": row["represented_amount_quantity_extent"],
            "represented_deadline_or_extension": row["represented_deadline_or_extension"],
            "verification_method": row["verification_method"],
            "verification_conclusion": row["verification_conclusion"],
        },
        reliance=None,
        epistemic_label="implementation_or_compliance_event",
        attribution={
            "epistemic_basis": row["epistemic_basis"],
            "attributed_participant": row["attributed_participant"],
            "represented_capacity": row["represented_capacity"],
            "qualification": row["qualification"],
        },
        representation_mode=str(row["representation_mode"]),
        review_state=review_state,
        contrary_sources=_contrary_sources(bindings),
        does_not_establish={
            **_no_establishment("implementation_or_compliance_event"),
            "does_not_establish_implementation": True,
            "does_not_establish_compliance": True,
            "does_not_establish_breach": True,
            "does_not_establish_completion": True,
        },
    )


def _formal_completion_row(
    conn: sqlite3.Connection,
    event_row: Mapping[str, Any],
    remedy_id: int,
    completion_determination_id: int,
) -> dict[str, Any]:
    event_identity = _logical_identity(conn, OBJECT_KIND_IMPLEMENTATION_EVENT, event_row["id"])
    completion_identity = _logical_identity(conn, OBJECT_KIND_DETERMINATION, completion_determination_id)
    return _base_row(
        object_kind=OBJECT_KIND_FORMAL_COMPLETION,
        object_id=completion_determination_id,
        parent_kind=OBJECT_KIND_IMPLEMENTATION_EVENT,
        parent_id=int(event_row["id"]),
        parent_governed_identity=event_identity,
        category="implementation_completed_as_formally_determined",
        status="linked_as_formal_completion_determination",
        represented_time=event_row["represented_event_date_or_period"],
        recorded_at=event_row["recorded_date"] or event_row["created_at"],
        chronology=_parse_interval(event_row["represented_event_date_or_period"]),
        ownership_path="stage70.object_link(formal_completion_determination)+scoped_remedy",
        source_bindings=[],
        object_links=[
            {
                "object_type": OBJECT_KIND_IMPLEMENTATION_EVENT,
                "object_id": str(event_row["id"]),
                "object_governed_identity": event_identity,
                "relationship_role": "formal_completion_event",
            },
            {
                "object_type": OBJECT_KIND_REMEDY,
                "object_id": str(remedy_id),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_REMEDY, remedy_id),
                "relationship_role": "formal_completion_remedy",
            },
            {
                "object_type": OBJECT_KIND_DETERMINATION,
                "object_id": str(completion_determination_id),
                "object_governed_identity": completion_identity,
                "relationship_role": "formal_completion_determination",
            },
        ],
        contestation={"status": "formal_completion_determination_as_recorded_only", "representation": event_row["event_category"]},
        supersession=_empty_supersession(),
        governed_digest=f"{event_identity}|formal_completion|{completion_identity}",
        display_label="Implementation completed as formally determined · linked determination",
        limitations="Formal completion is represented only by the distinct linked governed determination; the projection does not determine completion or compliance.",
        reliance=None,
        epistemic_label="formal_completion_determination",
        does_not_establish={
            **_no_establishment("formal_completion_determination"),
            "does_not_establish_implementation": True,
            "does_not_establish_compliance": True,
            "does_not_establish_completion": True,
        },
    )


def _publication_history(conn: sqlite3.Connection, ident: int) -> dict[str, Any]:
    reviews = [
        dict(item)
        for item in conn.execute(
            "SELECT review_type, status, rationale, reviewed_at, idempotency_key "
            "FROM record_governed_determination_publication_reviews WHERE publication_id=? ORDER BY reviewed_at, id",
            (ident,),
        ).fetchall()
    ]
    events = [
        dict(item)
        for item in conn.execute(
            "SELECT event_type, lifecycle_status, rationale, occurred_at, idempotency_key "
            "FROM record_governed_determination_publication_events WHERE publication_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    supersessions = [
        {
            "replacement_object_kind": OBJECT_KIND_DETERMINATION_PUBLICATION,
            "replacement_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION_PUBLICATION, item["replacement_publication_id"]),
            "occurred_at": item["occurred_at"],
            "idempotency_key": item["idempotency_key"],
        }
        for item in conn.execute(
            "SELECT replacement_publication_id, occurred_at, idempotency_key "
            "FROM record_governed_determination_publication_supersessions "
            "WHERE publication_id=? ORDER BY occurred_at, id",
            (ident,),
        ).fetchall()
    ]
    return {
        "superseded": bool(supersessions),
        "replacement": supersessions[-1] if supersessions else None,
        "review_history": reviews + events,
        "supersession_history": supersessions,
    }


def _publication_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ident = int(row["id"])
    determination_id = int(row["determination_id"])
    return _base_row(
        object_kind=OBJECT_KIND_DETERMINATION_PUBLICATION,
        object_id=ident,
        parent_kind=OBJECT_KIND_DETERMINATION,
        parent_id=determination_id,
        parent_governed_identity=_logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
        category=str(row["lifecycle_status"]),
        status=str(row["lifecycle_status"]),
        represented_time=row["published_at"] or row["approved_at"] or row["effect_as_of"],
        recorded_at=row["created_at"],
        chronology=_parse_interval(row["published_at"] or row["approved_at"] or row["effect_as_of"]),
        ownership_path="stage73.publication_determination_link(scoped_determination)",
        source_bindings=[],
        object_links=[
            {
                "object_type": OBJECT_KIND_DETERMINATION,
                "object_id": str(determination_id),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_DETERMINATION, determination_id),
                "relationship_role": "publication_subject_determination",
            },
            {
                "object_type": OBJECT_KIND_AUTHORITY,
                "object_id": str(row["authority_id"]),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_AUTHORITY, row["authority_id"]),
                "relationship_role": "publication_authority_snapshot",
            },
            {
                "object_type": OBJECT_KIND_MANDATE,
                "object_id": str(row["mandate_id"]),
                "object_governed_identity": _logical_identity(conn, OBJECT_KIND_MANDATE, row["mandate_id"]),
                "relationship_role": "publication_mandate_snapshot",
            },
        ],
        contestation={"status": "publication_snapshot_only", "representation": row["challenge_warning_status"]},
        supersession=_publication_history(conn, ident),
        governed_digest=str(row["idempotency_key"]),
        display_label=f"{_label(str(row['lifecycle_status']))} · {row['public_title']}",
        limitations={
            "source_limitations": row["limitations"],
            "reasons_status": row["reasons_status"],
            "privacy_status": row["privacy_status"],
            "redaction_status": row["redaction_status"],
            "redaction_notice": row["redaction_notice"],
            "authority_inspection_status": row["authority_inspection_status"],
            "mandate_inspection_status": row["mandate_inspection_status"],
            "challenge_warning_status": row["challenge_warning_status"],
            "current_effect_status": row["current_effect_status"],
            "current_effect_rationale": row["current_effect_rationale"],
            "content_digest_valid": row["content_digest"] == publications._snapshot_digest(publications._snapshot(dict(row))),
        },
        reliance=None,
        epistemic_label="determination_publication",
        attribution={
            "representation_mode": row["representation_mode"],
            "publication_version": int(row["publication_version"]),
            "eligibility_status": row["eligibility_status"],
        },
        representation_mode=str(row["representation_mode"]),
        review_state=None,
        does_not_establish={**_no_establishment("determination_publication"), "does_not_establish_endorsement": True},
    )


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        lower = row["chronology_lower_bound"] or _HIGH_BOUND
        upper = row["chronology_upper_bound"] or _HIGH_BOUND
        return (
            lower,
            upper,
            PRECISION_RANK.get(row["chronology_precision"], 4),
            KIND_RANK.get(row["object_kind"], 9),
            row["governed_digest"],
        )

    return sorted(rows, key=key)


def _mark_ordering_relations(rows: list[dict[str, Any]]) -> None:
    bounded = [row for row in rows if row["chronology_lower_bound"] and row["chronology_upper_bound"]]
    for row in rows:
        if not row["chronology_lower_bound"] or not row["chronology_upper_bound"]:
            row["ordering_relation"] = "indeterminate"
            continue
        lower, upper = row["chronology_lower_bound"], row["chronology_upper_bound"]
        row["ordering_relation"] = "determinate"
        for other in bounded:
            if other is row:
                continue
            if lower <= other["chronology_upper_bound"] and other["chronology_lower_bound"] <= upper:
                row["ordering_relation"] = "indeterminate"
                break


def _digest_row(row: dict[str, Any]) -> dict[str, Any]:
    item = {key: value for key, value in row.items() if key not in {"object_id", "parent_id"}}
    item["object_links"] = [
        {key: value for key, value in link.items() if key != "object_id"}
        for link in row["object_links"]
    ]
    return item


def _gap(
    gap_code: str,
    object_category: str,
    scope_root: str,
    binding_mechanism: str,
    lifecycle_filters: str,
    excluded_or_superseded: bool,
) -> dict[str, Any]:
    return {
        "gap_code": gap_code,
        "object_category": object_category,
        "scope_root": scope_root,
        "binding_mechanism": binding_mechanism,
        "lifecycle_filters": lifecycle_filters,
        "excluded_or_superseded_rows_existed": excluded_or_superseded,
        "statement": GAP_STATEMENTS[gap_code],
    }


def _project(conn: sqlite3.Connection, reference: str, as_of: str | None) -> dict[str, Any]:
    if not _table_exists(conn, "records"):
        raise ValueError("governed_pathway_projection_records_table_absent")
    if conn.execute("SELECT 1 FROM records WHERE reference=? LIMIT 1", (reference,)).fetchone() is None:
        raise ValueError("governed_pathway_projection_record_not_found")

    stage71_present, stage71_complete = _schema_state(conn, STAGE71_TABLES)
    if stage71_present and not stage71_complete:
        raise ValueError("governed_pathway_projection_stage71_schema_incomplete")
    stage72_present, stage72_complete = _schema_state(conn, STAGE72_TABLES)
    if stage72_present and not stage72_complete:
        raise ValueError("governed_pathway_projection_stage72_schema_incomplete")
    stage62_present, stage62_complete = _schema_state(conn, STAGE62_TABLES)
    if stage62_present and not stage62_complete:
        raise ValueError("governed_pathway_projection_stage62_schema_incomplete")
    stage63_present, stage63_complete = _schema_state(conn, STAGE63_TABLES)
    if stage63_present and not stage63_complete:
        raise ValueError("governed_pathway_projection_stage63_schema_incomplete")
    stage64_present, stage64_complete = _schema_state(conn, STAGE64_TABLES)
    if stage64_present and not stage64_complete:
        raise ValueError("governed_pathway_projection_stage64_schema_incomplete")
    stage65_present, stage65_complete = _schema_state(conn, STAGE65_TABLES)
    if stage65_present and not stage65_complete:
        raise ValueError("governed_pathway_projection_stage65_schema_incomplete")
    stage74_present, stage74_complete = _schema_state(conn, STAGE74_TABLES)
    if stage74_present and not stage74_complete:
        raise ValueError("governed_pathway_projection_stage74_schema_incomplete")
    stage66_present, stage66_complete = _schema_state(conn, STAGE66_TABLES)
    if stage66_present and not stage66_complete:
        raise ValueError("governed_pathway_projection_stage66_schema_incomplete")
    stage67_present, stage67_complete = _schema_state(conn, STAGE67_TABLES)
    if stage67_present and not stage67_complete:
        raise ValueError("governed_pathway_projection_stage67_schema_incomplete")
    stage68_present, stage68_complete = _schema_state(conn, STAGE68_TABLES)
    if stage68_present and not stage68_complete:
        raise ValueError("governed_pathway_projection_stage68_schema_incomplete")
    stage69_present, stage69_complete = _schema_state(conn, STAGE69_TABLES)
    if stage69_present and not stage69_complete:
        raise ValueError("governed_pathway_projection_stage69_schema_incomplete")
    stage70_present, stage70_complete = _schema_state(conn, STAGE70_TABLES)
    if stage70_present and not stage70_complete:
        raise ValueError("governed_pathway_projection_stage70_schema_incomplete")
    stage73_present, stage73_complete = _schema_state(conn, STAGE73_TABLES)
    if stage73_present and not stage73_complete:
        raise ValueError("governed_pathway_projection_stage73_schema_incomplete")

    notice_ids: set[int] = set()
    deadline_ids: set[int] = set()
    if stage71_present:
        for row in conn.execute(
            "SELECT record_kind, record_id FROM record_governed_procedural_time_object_links "
            "WHERE object_type='canonical_record' AND object_id=? "
            "AND relationship_role IN ('notice_concerns','deadline_applies_to')",
            (reference,),
        ).fetchall():
            if row["record_kind"] == "notice":
                notice_ids.add(int(row["record_id"]))
            elif row["record_kind"] == "deadline":
                deadline_ids.add(int(row["record_id"]))

    rows: list[dict[str, Any]] = []
    observation_rows: list[dict[str, Any]] = []
    inference_rows: list[dict[str, Any]] = []
    allegation_rows: list[dict[str, Any]] = []
    response_rows: list[dict[str, Any]] = []
    characterisation_rows: list[dict[str, Any]] = []
    authority_rows: list[dict[str, Any]] = []
    mandate_rows: list[dict[str, Any]] = []
    determination_rows: list[dict[str, Any]] = []
    determination_effect_rows: list[dict[str, Any]] = []
    challenge_rows: list[dict[str, Any]] = []
    challenge_event_rows: list[dict[str, Any]] = []
    challenge_outcome_rows: list[dict[str, Any]] = []
    remedy_rows: list[dict[str, Any]] = []
    implementation_event_rows: list[dict[str, Any]] = []
    formal_completion_rows: list[dict[str, Any]] = []
    publication_rows: list[dict[str, Any]] = []
    notice_rows: list[dict[str, Any]] = []
    deadline_rows: list[dict[str, Any]] = []
    observation_ids: set[int] = set()
    inference_ids: set[int] = set()
    allegation_ids: set[int] = set()
    response_ids: set[int] = set()
    characterisation_ids: set[int] = set()
    authority_ids: set[int] = set()
    mandate_ids: set[int] = set()
    determination_ids: set[int] = set()
    challenge_ids: set[int] = set()
    remedy_ids: set[int] = set()
    implementation_event_ids: set[int] = set()
    formal_completion_ids: set[int] = set()
    publication_ids: set[int] = set()
    if stage62_present:
        for row in conn.execute(
            "SELECT DISTINCT observation_id FROM record_pattern_observation_bindings "
            "WHERE record_reference=? ORDER BY observation_id",
            (reference,),
        ).fetchall():
            observation_ids.add(int(row["observation_id"]))
        for ident in sorted(observation_ids):
            found = conn.execute("SELECT * FROM record_pattern_observations WHERE id=?", (ident,)).fetchone()
            if found is not None:
                observation_rows.append(_observation_row(conn, found))
    if stage63_present:
        for row in conn.execute(
            "SELECT DISTINCT inference_id FROM record_governed_inference_bindings "
            "WHERE source_type='canonical_record' AND source_id=? ORDER BY inference_id",
            (reference,),
        ).fetchall():
            inference_ids.add(int(row["inference_id"]))
        for ident in sorted(inference_ids):
            found = conn.execute("SELECT * FROM record_governed_inferences WHERE id=?", (ident,)).fetchone()
            if found is not None:
                inference_rows.append(_inference_row(conn, found))
    if stage64_present:
        for row in conn.execute(
            "SELECT DISTINCT allegation_id FROM record_governed_allegation_bindings "
            "WHERE source_type='canonical_record' AND source_id=? ORDER BY allegation_id",
            (reference,),
        ).fetchall():
            allegation_ids.add(int(row["allegation_id"]))
        for ident in sorted(allegation_ids):
            found = conn.execute("SELECT * FROM record_governed_allegations WHERE id=?", (ident,)).fetchone()
            if found is not None:
                allegation_rows.append(_allegation_row(conn, found))
    if stage65_present and allegation_ids:
        for row in conn.execute(
            "SELECT DISTINCT r.*, l.allegation_id FROM record_governed_responses r "
            "JOIN record_governed_response_allegation_links l ON l.response_id=r.id "
            "JOIN record_governed_response_bindings b ON b.response_id=r.id "
            "WHERE l.allegation_id IN (%s) AND b.source_type='canonical_record' AND b.source_id=? "
            "ORDER BY r.id"
            % ",".join("?" for _ in sorted(allegation_ids)),
            (*sorted(allegation_ids), reference),
        ).fetchall():
            response_ids.add(int(row["id"]))
            response_rows.append(_response_row(conn, row, int(row["allegation_id"])))
    scoped_for_characterisation = {
        ("canonical_record", reference),
        *[(OBJECT_KIND_OBSERVATION, str(ident)) for ident in observation_ids],
        *[("accepted_pattern_observation", str(ident)) for ident in observation_ids],
        *[(OBJECT_KIND_INFERENCE, str(ident)) for ident in inference_ids],
        *[(OBJECT_KIND_ALLEGATION, str(ident)) for ident in allegation_ids],
        *[(OBJECT_KIND_RESPONSE, str(ident)) for ident in response_ids],
    }
    if stage74_present:
        for row in conn.execute("SELECT * FROM record_governed_characterisations ORDER BY created_at, id").fetchall():
            primary = (str(row["primary_object_kind"]), str(row["primary_object_id"]))
            ownership_path = None
            if primary in scoped_for_characterisation:
                ownership_path = "stage74.primary_object_in_stage78a2a_scope"
            else:
                for ref in conn.execute(
                    "SELECT object_kind, object_id FROM record_governed_characterisation_references "
                    "WHERE characterisation_id=? ORDER BY object_kind, object_id",
                    (int(row["id"]),),
                ).fetchall():
                    if (str(ref["object_kind"]), str(ref["object_id"])) in scoped_for_characterisation:
                        ownership_path = "stage74.reference_object_in_stage78a2a_scope"
                        break
            if ownership_path is not None:
                characterisation_ids.add(int(row["id"]))
                characterisation_rows.append(_characterisation_row(conn, row, ownership_path))
    rows.extend(observation_rows)
    rows.extend(inference_rows)
    rows.extend(allegation_rows)
    rows.extend(response_rows)
    rows.extend(characterisation_rows)

    scoped_for_determinations = {
        ("canonical_record", reference),
        *[("accepted_pattern_observation", str(ident)) for ident in observation_ids],
        *[("governed_inference", str(ident)) for ident in inference_ids],
        *[("governed_allegation", str(ident)) for ident in allegation_ids],
        *[("governed_response", str(ident)) for ident in response_ids],
        *[(OBJECT_KIND_AUTHORITY, str(ident)) for ident in authority_ids],
    }
    if stage66_present:
        for row in conn.execute(
            "SELECT DISTINCT object_id FROM record_governed_decision_authority_bindings "
            "WHERE object_type='authority' AND source_type='canonical_record' AND source_id=? "
            "ORDER BY object_id",
            (reference,),
        ).fetchall():
            authority_ids.add(int(row["object_id"]))
        for row in conn.execute(
            "SELECT DISTINCT object_id FROM record_governed_decision_authority_bindings "
            "WHERE object_type='mandate' AND source_type='canonical_record' AND source_id=? "
            "ORDER BY object_id",
            (reference,),
        ).fetchall():
            mandate_ids.add(int(row["object_id"]))
        for ident in sorted(authority_ids):
            found = conn.execute(
                "SELECT * FROM record_governed_decision_authorities WHERE id=?", (ident,)
            ).fetchone()
            if found is not None:
                authority_rows.append(_authority_row(conn, found))
        for ident in sorted(mandate_ids):
            found = conn.execute(
                "SELECT * FROM record_governed_decision_authority_mandates WHERE id=?", (ident,)
            ).fetchone()
            if found is not None:
                mandate_rows.append(_mandate_row(conn, found, "stage66.mandate_binding(canonical_record)"))
    if stage67_present:
        for row in conn.execute(
            "SELECT DISTINCT determination_id FROM record_governed_determination_bindings "
            "WHERE source_type='canonical_record' AND source_id=? ORDER BY determination_id",
            (reference,),
        ).fetchall():
            determination_ids.add(int(row["determination_id"]))
        scoped_for_determinations.update(
            {
                *[(OBJECT_KIND_AUTHORITY, str(ident)) for ident in authority_ids],
                *[("decision_authority", str(ident)) for ident in authority_ids],
            }
        )
        for row in conn.execute(
            "SELECT DISTINCT determination_id FROM record_governed_determination_governed_object_links"
        ).fetchall():
            ident = int(row["determination_id"])
            objects = conn.execute(
                "SELECT object_type, object_id FROM record_governed_determination_governed_object_links "
                "WHERE determination_id=?",
                (ident,),
            ).fetchall()
            if any((str(item["object_type"]), str(item["object_id"])) in scoped_for_determinations for item in objects):
                determination_ids.add(ident)
        for ident in sorted(determination_ids):
            found = conn.execute("SELECT * FROM record_governed_determinations WHERE id=?", (ident,)).fetchone()
            if found is None:
                continue
            determination_rows.append(_determination_row(conn, found, "stage67.binding_or_governed_object_link(canonical_record_scope)"))
            link = conn.execute(
                "SELECT authority_id, mandate_id FROM record_governed_determination_authority_links WHERE determination_id=?",
                (ident,),
            ).fetchone()
            if link is not None:
                authority_ids.add(int(link["authority_id"]))
                mandate_ids.add(int(link["mandate_id"]))
        if stage66_present:
            existing_authority_row_ids = {int(row["object_id"]) for row in authority_rows}
            existing_mandate_row_ids = {int(row["object_id"]) for row in mandate_rows}
            for ident in sorted(authority_ids - existing_authority_row_ids):
                found = conn.execute("SELECT * FROM record_governed_decision_authorities WHERE id=?", (ident,)).fetchone()
                if found is not None:
                    authority_rows.append(_authority_row(conn, found))
            for ident in sorted(mandate_ids - existing_mandate_row_ids):
                found = conn.execute("SELECT * FROM record_governed_decision_authority_mandates WHERE id=?", (ident,)).fetchone()
                if found is not None:
                    mandate_rows.append(_mandate_row(conn, found, "stage67.determination_authority_link(scoped_determination)"))
        for ident in sorted(determination_ids):
            for effect in conn.execute(
                "SELECT * FROM record_governed_determination_effect_events WHERE determination_id=?",
                (ident,),
            ).fetchall():
                determination_effect_rows.append(_determination_effect_row(conn, effect))
    if stage68_present and determination_ids:
        for row in conn.execute(
            "SELECT DISTINCT challenge_id, determination_id FROM record_governed_challenge_determination_links "
            "WHERE determination_id IN (%s) ORDER BY challenge_id"
            % ",".join("?" for _ in sorted(determination_ids)),
            tuple(sorted(determination_ids)),
        ).fetchall():
            challenge_ids.add(int(row["challenge_id"]))
        for ident in sorted(challenge_ids):
            found = conn.execute("SELECT * FROM record_governed_challenge_proceedings WHERE id=?", (ident,)).fetchone()
            if found is None:
                continue
            target = conn.execute(
                "SELECT determination_id FROM record_governed_challenge_determination_links WHERE challenge_id=?",
                (ident,),
            ).fetchone()
            challenge_rows.append(_challenge_row(conn, found, int(target["determination_id"])))
            for event in conn.execute(
                "SELECT * FROM record_governed_challenge_events WHERE challenge_id=?",
                (ident,),
            ).fetchall():
                challenge_event_rows.append(_challenge_event_row(conn, event, ident))
            for outcome in conn.execute(
                "SELECT * FROM record_governed_challenge_outcomes WHERE challenge_id=?",
                (ident,),
            ).fetchall():
                challenge_outcome_rows.append(_challenge_outcome_row(conn, outcome, ident))
    if stage69_present and determination_ids:
        for row in conn.execute(
            "SELECT DISTINCT remedy_id, determination_id FROM record_governed_remedy_determination_links "
            "WHERE determination_id IN (%s) ORDER BY remedy_id"
            % ",".join("?" for _ in sorted(determination_ids)),
            tuple(sorted(determination_ids)),
        ).fetchall():
            remedy_ids.add(int(row["remedy_id"]))
        for ident in sorted(remedy_ids):
            found = conn.execute("SELECT * FROM record_governed_remedies WHERE id=?", (ident,)).fetchone()
            if found is None:
                continue
            target = conn.execute(
                "SELECT determination_id FROM record_governed_remedy_determination_links WHERE remedy_id=?",
                (ident,),
            ).fetchone()
            remedy_rows.append(_remedy_row(conn, found, int(target["determination_id"])))
    if stage70_present and remedy_ids:
        for row in conn.execute(
            "SELECT DISTINCT event_id, remedy_id FROM record_governed_implementation_event_remedy_links "
            "WHERE remedy_id IN (%s) ORDER BY event_id"
            % ",".join("?" for _ in sorted(remedy_ids)),
            tuple(sorted(remedy_ids)),
        ).fetchall():
            implementation_event_ids.add(int(row["event_id"]))
        for ident in sorted(implementation_event_ids):
            found = conn.execute("SELECT * FROM record_governed_implementation_events WHERE id=?", (ident,)).fetchone()
            if found is None:
                continue
            target = conn.execute(
                "SELECT remedy_id FROM record_governed_implementation_event_remedy_links WHERE event_id=?",
                (ident,),
            ).fetchone()
            remedy_id = int(target["remedy_id"])
            implementation_event_rows.append(_implementation_event_row(conn, found, remedy_id))
            for link in conn.execute(
                "SELECT object_id FROM record_governed_implementation_event_object_links "
                "WHERE event_id=? AND object_type='governed_determination' "
                "AND relationship_role='formal_completion_determination'",
                (ident,),
            ).fetchall():
                completion_id = int(link["object_id"])
                if completion_id not in formal_completion_ids:
                    formal_completion_ids.add(completion_id)
                    formal_completion_rows.append(_formal_completion_row(conn, found, remedy_id, completion_id))
    if stage73_present and determination_ids:
        for row in conn.execute(
            "SELECT id FROM record_governed_determination_publications "
            "WHERE determination_id IN (%s) ORDER BY publication_version, id"
            % ",".join("?" for _ in sorted(determination_ids)),
            tuple(sorted(determination_ids)),
        ).fetchall():
            publication_ids.add(int(row["id"]))
        for ident in sorted(publication_ids):
            found = conn.execute(
                "SELECT * FROM record_governed_determination_publications WHERE id=?", (ident,)
            ).fetchone()
            if found is not None:
                publication_rows.append(_publication_row(conn, found))
    rows.extend(authority_rows)
    rows.extend(mandate_rows)
    rows.extend(determination_rows)
    rows.extend(determination_effect_rows)
    rows.extend(challenge_rows)
    rows.extend(challenge_event_rows)
    rows.extend(challenge_outcome_rows)
    rows.extend(remedy_rows)
    rows.extend(implementation_event_rows)
    rows.extend(formal_completion_rows)
    rows.extend(publication_rows)
    if stage71_present:
        for ident in sorted(notice_ids):
            found = conn.execute(
                "SELECT * FROM record_governed_procedural_notices WHERE id=?", (ident,)
            ).fetchone()
            if found is not None:
                notice_rows.append(_notice_row(conn, found))
        for ident in sorted(deadline_ids):
            found = conn.execute(
                "SELECT * FROM record_governed_procedural_deadlines WHERE id=?", (ident,)
            ).fetchone()
            if found is not None:
                deadline_rows.append(_deadline_row(conn, found))
    rows.extend(notice_rows)
    rows.extend(deadline_rows)

    if stage71_present:
        for parent_kind, idents in (("notice", notice_ids), ("deadline", deadline_ids)):
            for ident in sorted(idents):
                for event in conn.execute(
                    "SELECT * FROM record_governed_procedural_time_events "
                    "WHERE parent_kind=? AND parent_id=?",
                    (parent_kind, ident),
                ).fetchall():
                    rows.append(_event_row(conn, event))
        for deadline in deadline_rows:
            for calculation in conn.execute(
                "SELECT * FROM record_governed_deadline_calculations WHERE deadline_id=?",
                (int(deadline["object_id"]),),
            ).fetchall():
                rows.append(_calculation_row(conn, calculation))

    pathway_included = 0
    pathway_exclusions: dict[str, int] = {}
    if stage72_present:
        in_scope_endpoints = {
            (row["object_kind"], row["object_id"]) for row in rows if row["object_kind"] in _STAGE71_ENDPOINT_KINDS
        }
        in_scope_endpoints.update(
            (row["object_kind"], row["object_id"]) for row in rows if row["object_kind"] in _A2A_ENDPOINT_KINDS
        )
        in_scope_endpoints.update(
            (row["object_kind"], row["object_id"]) for row in rows if row["object_kind"] in _A2B1_ENDPOINT_KINDS
        )
        in_scope_endpoints.update(
            (row["object_kind"], row["object_id"]) for row in rows if row["object_kind"] in _A2B2_ENDPOINT_KINDS
        )
        in_scope_endpoints.update((OBJECT_KIND_OBSERVATION, str(ident)) for ident in observation_ids)
        in_scope_endpoints.update(("accepted_pattern_observation", str(ident)) for ident in observation_ids)
        for link in conn.execute(
            "SELECT * FROM record_governed_pathway_links"
        ).fetchall():
            endpoints = [
                (str(link["source_object_kind"]), str(link["source_object_id"])),
                (str(link["target_object_kind"]), str(link["target_object_id"])),
            ]
            if any(kind == "canonical_record" and object_id != reference for kind, object_id in endpoints):
                pathway_exclusions["cross_record_endpoint"] = pathway_exclusions.get("cross_record_endpoint", 0) + 1
                continue
            touches_root = any(kind == "canonical_record" and object_id == reference for kind, object_id in endpoints)
            both_in_scope = all(endpoint in in_scope_endpoints for endpoint in endpoints)
            if touches_root:
                rows.append(_pathway_row(conn, link, "stage72.endpoint(canonical_record=root)"))
                pathway_included += 1
            elif both_in_scope:
                rows.append(_pathway_row(conn, link, "stage72.both_endpoints_in_stage78a_scope"))
                pathway_included += 1
            else:
                pathway_exclusions["endpoint_out_of_scope"] = pathway_exclusions.get("endpoint_out_of_scope", 0) + 1

    rows = _sort_rows(rows)
    _mark_ordering_relations(rows)

    notice_count = len(notice_rows)
    deadline_count = len(deadline_rows)
    observation_count = len(observation_rows)
    inference_count = len(inference_rows)
    allegation_count = len(allegation_rows)
    response_count = len(response_rows)
    characterisation_count = len(characterisation_rows)
    authority_count = len(authority_rows)
    mandate_count = len(mandate_rows)
    determination_count = len(determination_rows)
    determination_effect_count = len(determination_effect_rows)
    challenge_count = len(challenge_rows)
    challenge_event_count = len(challenge_event_rows)
    challenge_outcome_count = len(challenge_outcome_rows)
    remedy_count = len(remedy_rows)
    implementation_event_count = len(implementation_event_rows)
    verification_count = sum(1 for row in implementation_event_rows if row["category"] == "verification_performed")
    formal_completion_count = len(formal_completion_rows)
    publication_count = len(publication_rows)
    determination_reason_count = sum(
        1
        for row in determination_rows
        if isinstance(row.get("limitations"), Mapping)
        and row["limitations"].get("reasons_status") == "reasons_recorded"
    )
    event_count = sum(1 for row in rows if row["object_kind"] == OBJECT_KIND_EVENT)
    calculation_count = sum(1 for row in rows if row["object_kind"] == OBJECT_KIND_CALCULATION)
    evidenced_receipt_rows = [
        row for row in notice_rows if row["category"] == "notice_received_as_evidenced"
    ]

    gaps: list[dict[str, Any]] = []
    if stage62_present and observation_count == 0:
        gaps.append(_gap("no_governed_observation_linked", OBJECT_KIND_OBSERVATION, reference,
                         "record_pattern_observation_bindings(record_reference)", "none", False))
    if stage63_present and inference_count == 0:
        gaps.append(_gap("no_governed_inference_linked", OBJECT_KIND_INFERENCE, reference,
                         "record_governed_inference_bindings(canonical_record)", "none", False))
    if stage64_present and allegation_count == 0:
        gaps.append(_gap("no_governed_allegation_linked", OBJECT_KIND_ALLEGATION, reference,
                         "record_governed_allegation_bindings(canonical_record)", "none", False))
    if stage65_present and response_count == 0:
        gaps.append(_gap("no_governed_response_linked", OBJECT_KIND_RESPONSE, reference,
                         "record_governed_response_allegation_links+record_governed_response_bindings(canonical_record)", "none", False))
    if stage74_present and characterisation_count == 0:
        gaps.append(_gap("no_governed_characterisation_linked", OBJECT_KIND_CHARACTERISATION, reference,
                         "record_governed_characterisations(primary_object)+references", "none", False))
    if stage66_present and authority_count == 0:
        gaps.append(_gap("no_governed_decision_authority_linked", OBJECT_KIND_AUTHORITY, reference,
                         "record_governed_decision_authority_bindings(canonical_record)", "none", False))
    if stage66_present and mandate_count == 0:
        gaps.append(_gap("no_governed_mandate_linked", OBJECT_KIND_MANDATE, reference,
                         "record_governed_decision_authority_bindings(canonical_record_or_scoped_determination)", "none", False))
    if stage67_present and determination_count == 0:
        gaps.append(_gap("no_governed_determination_linked", OBJECT_KIND_DETERMINATION, reference,
                         "record_governed_determination_bindings_or_governed_object_links", "none", False))
    if stage67_present:
        for row in determination_rows:
            if isinstance(row.get("limitations"), Mapping) and row["limitations"].get("reasons_status") == "no_reasons_recorded_in_source":
                gaps.append(_gap("no_governed_determination_reasons", OBJECT_KIND_DETERMINATION, reference,
                                 f"record_governed_determinations({row['governed_digest']}).reasons_status",
                                 "reasons_status=no_reasons_recorded_in_source", False))
    if stage68_present and challenge_count == 0:
        gaps.append(_gap("no_governed_challenge_linked", OBJECT_KIND_CHALLENGE, reference,
                         "record_governed_challenge_determination_links(scoped_determination)", "none", False))
    if stage69_present and remedy_count == 0:
        gaps.append(_gap("no_governed_remedy_linked", OBJECT_KIND_REMEDY, reference,
                         "record_governed_remedy_determination_links(scoped_determination)", "none", False))
    if stage70_present and implementation_event_count == 0:
        gaps.append(_gap("no_governed_implementation_event_linked", OBJECT_KIND_IMPLEMENTATION_EVENT, reference,
                         "record_governed_implementation_event_remedy_links(scoped_remedy)", "none", False))
    if stage70_present and verification_count == 0:
        gaps.append(_gap("no_governed_verification_linked", OBJECT_KIND_IMPLEMENTATION_EVENT, reference,
                         "record_governed_implementation_events(event_category=verification_performed)", "event_category=verification_performed", False))
    if stage70_present and formal_completion_count == 0:
        gaps.append(_gap("no_governed_formal_completion_determination_linked", OBJECT_KIND_FORMAL_COMPLETION, reference,
                         "record_governed_implementation_event_object_links(formal_completion_determination)", "none", False))
    if stage73_present and publication_count == 0:
        gaps.append(_gap("no_governed_determination_publication_linked", OBJECT_KIND_DETERMINATION_PUBLICATION, reference,
                         "record_governed_determination_publications(scoped_determination)", "none", False))
    if notice_count == 0:
        gaps.append(_gap("no_governed_notice_linked", OBJECT_KIND_NOTICE, reference,
                         "record_governed_procedural_time_object_links(notice_concerns)", "none", False))
    elif not evidenced_receipt_rows:
        superseded_receipt = any(
            row["status"] == "superseded" for row in notice_rows if row["category"] == "notice_received_as_evidenced"
        )
        gaps.append(_gap("no_evidenced_receipt_notice_in_scope", OBJECT_KIND_NOTICE, reference,
                         "record_governed_procedural_time_notices(notice_category=notice_received_as_evidenced)",
                         "notice_category=notice_received_as_evidenced", superseded_receipt))
    if deadline_count == 0:
        gaps.append(_gap("no_governed_deadline_linked", OBJECT_KIND_DEADLINE, reference,
                         "record_governed_procedural_time_object_links(deadline_applies_to)", "none", False))
    if stage71_present:
        for deadline in deadline_rows:
            if not any(
                row["object_kind"] == OBJECT_KIND_CALCULATION and row["parent_id"] == deadline["object_id"]
                for row in rows
            ):
                gaps.append(_gap("no_governed_deadline_calculation", OBJECT_KIND_CALCULATION, reference,
                                 f"record_governed_deadline_calculations(deadline={deadline['governed_digest']})",
                                 "none", False))
    if stage72_present and pathway_included == 0:
        gaps.append(_gap("no_governed_pathway_link_in_scope", OBJECT_KIND_PATHWAY_LINK, reference,
                         "record_governed_pathway_links(root_endpoint_or_both_endpoints_in_scope)", "none", False))
    gaps.sort(key=lambda item: (item["gap_code"], item["binding_mechanism"]))

    coverage = {
        "stage62_schema_present": stage62_present,
        "stage63_schema_present": stage63_present,
        "stage64_schema_present": stage64_present,
        "stage65_schema_present": stage65_present,
        "stage74_schema_present": stage74_present,
        "stage66_schema_present": stage66_present,
        "stage67_schema_present": stage67_present,
        "stage68_schema_present": stage68_present,
        "stage69_schema_present": stage69_present,
        "stage70_schema_present": stage70_present,
        "stage73_schema_present": stage73_present,
        "stage71_schema_present": stage71_present,
        "stage72_schema_present": stage72_present,
        "observations_in_scope": observation_count,
        "inferences_in_scope": inference_count,
        "allegations_in_scope": allegation_count,
        "responses_in_scope": response_count,
        "characterisations_in_scope": characterisation_count,
        "decision_authorities_in_scope": authority_count,
        "decision_mandates_in_scope": mandate_count,
        "determinations_in_scope": determination_count,
        "determination_reasons_recorded": determination_reason_count,
        "determination_effect_events_in_scope": determination_effect_count,
        "challenges_in_scope": challenge_count,
        "challenge_events_in_scope": challenge_event_count,
        "challenge_outcomes_in_scope": challenge_outcome_count,
        "remedies_in_scope": remedy_count,
        "implementation_events_in_scope": implementation_event_count,
        "verification_events_in_scope": verification_count,
        "formal_completion_determinations_in_scope": formal_completion_count,
        "determination_publications_in_scope": publication_count,
        "notices_in_scope": notice_count,
        "deadlines_in_scope": deadline_count,
        "procedural_time_events_in_scope": event_count,
        "deadline_calculations_in_scope": calculation_count,
        "pathway_links_included": pathway_included,
        "pathway_links_excluded": sum(pathway_exclusions.values()),
        "pathway_link_exclusion_reasons": [
            {"reason": reason, "count": pathway_exclusions[reason]}
            for reason in sorted(pathway_exclusions)
        ],
    }
    scope = {
        "root_object_kind": "canonical_record",
        "record_reference": reference,
        "included_object_kinds": [
            OBJECT_KIND_OBSERVATION,
            OBJECT_KIND_INFERENCE,
            OBJECT_KIND_ALLEGATION,
            OBJECT_KIND_RESPONSE,
            OBJECT_KIND_CHARACTERISATION,
            OBJECT_KIND_AUTHORITY,
            OBJECT_KIND_MANDATE,
            OBJECT_KIND_DETERMINATION,
            OBJECT_KIND_DETERMINATION_EFFECT,
            OBJECT_KIND_CHALLENGE,
            OBJECT_KIND_CHALLENGE_EVENT,
            OBJECT_KIND_CHALLENGE_OUTCOME,
            OBJECT_KIND_REMEDY,
            OBJECT_KIND_IMPLEMENTATION_EVENT,
            OBJECT_KIND_FORMAL_COMPLETION,
            OBJECT_KIND_DETERMINATION_PUBLICATION,
            OBJECT_KIND_NOTICE,
            OBJECT_KIND_DEADLINE,
            OBJECT_KIND_EVENT,
            OBJECT_KIND_CALCULATION,
            OBJECT_KIND_PATHWAY_LINK,
        ],
        "stage71_ownership_rule": "record_governed_procedural_time_object_links(object_type='canonical_record', object_id=record_reference)",
        "stage72_inclusion_rule": "root_endpoint_and_no_cross_record_endpoint_or_both_endpoints_in_stage78a_scope",
        "stage62_ownership_rule": "record_pattern_observation_bindings(record_reference=record_reference)",
        "stage63_ownership_rule": "record_governed_inference_bindings(source_type='canonical_record', source_id=record_reference)",
        "stage64_ownership_rule": "record_governed_allegation_bindings(source_type='canonical_record', source_id=record_reference)",
        "stage65_ownership_rule": "scoped allegation link plus record_governed_response_bindings(source_type='canonical_record', source_id=record_reference)",
        "stage74_ownership_rule": "primary object or explicit reference already in Stage 78A2A scope",
        "stage66_authority_ownership_rule": "record_governed_decision_authority_bindings(object_type='authority', source_type='canonical_record', source_id=record_reference)",
        "stage66_mandate_ownership_rule": "record_governed_decision_authority_bindings(object_type='mandate', source_type='canonical_record', source_id=record_reference) or scoped determination authority link",
        "stage67_determination_ownership_rule": "record_governed_determination_bindings(canonical_record) or governed object link to an already scoped governed object",
        "stage68_challenge_ownership_rule": "record_governed_challenge_determination_links(target is scoped determination)",
        "stage69_remedy_ownership_rule": "record_governed_remedy_determination_links(target is scoped determination)",
        "stage70_implementation_ownership_rule": "record_governed_implementation_event_remedy_links(target is scoped remedy)",
        "stage70_formal_completion_rule": "record_governed_implementation_event_object_links(formal_completion_determination) from scoped implementation event",
        "stage73_publication_ownership_rule": "record_governed_determination_publications(determination_id is scoped determination)",
    }

    digest_rows = [_digest_row(row) for row in rows]
    digest_payload = {
        "projection_contract": PROJECTION_CONTRACT,
        "projection_version": PROJECTION_VERSION,
        "record_reference": reference,
        "scope": scope,
        "rows": digest_rows,
        "coverage": coverage,
        "gaps": gaps,
    }
    projection: dict[str, Any] = {
        "projection_contract": PROJECTION_CONTRACT,
        "projection_version": PROJECTION_VERSION,
        "record_reference": reference,
        "scope": scope,
        "rows": rows,
        "coverage": coverage,
        "gaps": gaps,
        "projection_digest": "sha256:" + hashlib.sha256(_json(digest_payload).encode()).hexdigest(),
    }
    if as_of is not None:
        projection["generated_as_of"] = str(as_of)
    return projection


def project_pathway(
    conn_or_db: sqlite3.Connection | str | Path,
    record_reference: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Project the governed procedural pathway for one canonical record.

    Accepts either an existing ``sqlite3.Connection`` (used as-is, never
    closed, never written) or a database path, in which case the database is
    opened read-only with ``PRAGMA query_only=ON``.  The projection performs no
    schema initialisation, no writes and no lifecycle mutation, and raises
    bounded ``ValueError`` codes for a missing records schema, an unknown
    record reference, or partially present Stage 71/Stage 72 schemas.
    """

    reference = str(record_reference or "")
    if not reference.strip():
        raise ValueError("governed_pathway_projection_record_reference_required")
    if isinstance(conn_or_db, sqlite3.Connection):
        return _project(conn_or_db, reference, as_of)
    path = Path(conn_or_db)
    if not path.is_file():
        raise ValueError("governed_pathway_projection_database_unavailable")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        return _project(conn, reference, as_of)
    finally:
        conn.close()
