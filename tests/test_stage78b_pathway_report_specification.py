"""Stage 78B frozen procedural-pathway report specification tests."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import record_governed_decision_authorities as authorities
from api import record_governed_determinations as determinations
from api import record_governed_reports as reports
from tests.test_stage78a_pathway_projection import OTHER_RECORD, RECORD, ProjectionFixture


FIXED_TIME = "2026-08-30T00:00:00Z"


def _enable_report_record_snapshot(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(records)").fetchall()}
    if "is_latest" not in columns:
        conn.execute("ALTER TABLE records ADD COLUMN is_latest INTEGER DEFAULT 1")


def _fresh_connection() -> sqlite3.Connection:
    conn = ProjectionFixture.fresh_connection()
    _enable_report_record_snapshot(conn)
    return conn


def _fresh_file_connection(directory: str, *, journal_mode: str) -> tuple[Path, sqlite3.Connection, str]:
    path = Path(directory) / f"pathway-freeze-{journal_mode.lower()}.db"
    conn = sqlite3.connect(path, timeout=0.2)
    conn.row_factory = sqlite3.Row
    actual = str(conn.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0])
    ProjectionFixture.seed_records(conn)
    _enable_report_record_snapshot(conn)
    return path, conn, actual


def _populate_projection(conn: sqlite3.Connection) -> ProjectionFixture:
    fixture = ProjectionFixture(conn)
    fixture.notice(idempotency_key="notice-1")
    deadline = fixture.deadline(idempotency_key="deadline-1")
    fixture.calculation(deadline["id"], idempotency_key="calc-1")
    fixture.pathway_link(observation_key="pathway-observation", idempotency_key="pathway-1")
    fixture.inference(key="inference-1", status="accepted_as_inference")
    allegation = fixture.allegation(key="allegation-1", status="accepted_as_attributed_allegation")
    fixture.response(allegation_id=allegation["id"], key="response-1")
    fixture.characterisation(key="characterisation-1", status="accepted")
    determination = fixture.accepted_determination(key="determination-1")
    fixture.effect_event(determination["id"], key="effect-1")
    challenge = fixture.challenge(determination_id=determination["id"], key="challenge-1")
    fixture.challenge_event(challenge["id"], key="challenge-event-1")
    remedy = fixture.remedy(determination_id=determination["id"], key="remedy-1")
    fixture.implementation_event(remedy_id=remedy["id"], key="implementation-1")
    fixture.publication(determination_id=determination["id"], key="publication-1")
    return fixture


def _create_pathway_report(conn: sqlite3.Connection, *, key: str = "pathway-report", _commit: bool = True) -> dict:
    with patch.object(reports, "utc_now", return_value=FIXED_TIME):
        return reports.create_report(
            conn,
            title="Procedural pathway",
            purpose="Internal pathway review",
            audience="Internal reviewers",
            distribution_class="internal_working",
            canonical_record_reference=RECORD,
            document_ids=[],
            association_ids=[],
            sections=[],
            exclusions=[],
            requested_formats=["html", "docx"],
            rendering_profile=reports.PATHWAY_RENDERING_PROFILE,
            template_version=reports.PATHWAY_TEMPLATE_VERSION,
            actor="creator",
            actor_role="administrator",
            idempotency_key=key,
            report_type=reports.PATHWAY_REPORT_TYPE,
            created_at=FIXED_TIME,
            _commit=_commit,
        )


def _spec(report: dict) -> dict:
    return copy.deepcopy(report["versions"][0]["specification"])


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _independent_row_authority_digest(row: dict) -> str:
    payload = {
        "object_kind": row["object_kind"],
        "governed_logical_identity": row["governed_logical_identity"],
        "parent_governed_identity": row["parent_governed_identity"],
        "endpoint_identities": row["endpoint_identities"],
        "status": row["status"],
        "ownership_path": row["ownership_path"],
        "source_authority_key": row["source_authority_key"],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _all_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def _report_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = _all_table_counts(conn)
    return {
        "reports": counts.get("record_governed_reports", 0),
        "versions": counts.get("record_governed_report_versions", 0),
        "events": counts.get("record_governed_report_events", 0),
    }


def _external_notice_status_update(db_path: Path, status: str) -> str:
    conn = sqlite3.connect(db_path, timeout=0.1)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=100")
        conn.execute(
            "UPDATE record_governed_procedural_notices SET status=? WHERE idempotency_key='notice-1'",
            (status,),
        )
        conn.commit()
        return "committed"
    except sqlite3.Error as exc:
        conn.rollback()
        return str(exc)
    finally:
        conn.close()


class Stage78BFrozenSpecificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _fresh_connection()
        _populate_projection(self.conn)
        self.report = _create_pathway_report(self.conn)
        self.specification = _spec(self.report)

    def tearDown(self) -> None:
        self.conn.close()

    def assertInvalidSpec(self, specification: dict, error: str) -> None:
        before = _all_table_counts(self.conn)
        with self.assertRaisesRegex(ValueError, error):
            reports.validate_pathway_report_specification(self.conn, specification)
        self.assertEqual(before, _all_table_counts(self.conn))

    def assertSourceDrift(self, error: str) -> None:
        before = _all_table_counts(self.conn)
        with self.assertRaisesRegex(ValueError, error):
            reports._validate_generation_sources(self.conn, self.specification)
        self.assertEqual(before, _all_table_counts(self.conn))

    def test_real_producer_creates_full_scope_frozen_specification(self) -> None:
        spec = self.specification
        self.assertEqual(spec["report_type"], reports.PATHWAY_REPORT_TYPE)
        self.assertEqual(spec["specification_schema_version"], reports.PATHWAY_SPECIFICATION_SCHEMA_VERSION)
        self.assertEqual(spec["distribution_class"], "internal_working")
        self.assertEqual(spec["rendering_profile"], reports.PATHWAY_RENDERING_PROFILE)
        self.assertEqual(spec["template_version"], reports.PATHWAY_TEMPLATE_VERSION)
        pathway = spec["pathway_projection"]
        self.assertEqual(pathway["projection_contract"], reports.PATHWAY_PROJECTION_CONTRACT)
        self.assertEqual(pathway["projection_version"], reports.PATHWAY_PROJECTION_VERSION)
        self.assertEqual(pathway["canonical_record_reference"], RECORD)
        self.assertEqual(pathway["inclusion_mode"], reports.PATHWAY_INCLUSION_MODE)
        self.assertEqual(pathway["exclusion_rule"], reports.PATHWAY_EXCLUSION_RULE)
        self.assertGreater(len(pathway["rows"]), 10)

    def test_canonical_record_parity_and_source_identity_are_exact(self) -> None:
        pathway = self.specification["pathway_projection"]
        self.assertEqual(self.specification["primary_record"]["reference"], RECORD)
        self.assertEqual(pathway["source_identity"], {"object_kind": reports.PATHWAY_SOURCE_IDENTITY_KIND, "object_id": RECORD})

    def test_compact_inventory_contains_identity_source_key_row_digest_and_ownership_only(self) -> None:
        expected = {
            "object_kind", "governed_logical_identity", "parent_governed_identity",
            "endpoint_identities", "status", "source_authority_key", "row_authority_digest",
            "ownership_path",
        }
        identities = []
        for row in self.specification["pathway_projection"]["rows"]:
            self.assertEqual(set(row), expected)
            self.assertTrue(row["object_kind"])
            self.assertTrue(row["governed_logical_identity"])
            self.assertTrue(row["source_authority_key"])
            self.assertRegex(row["row_authority_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(row["row_authority_digest"], _independent_row_authority_digest(row))
            self.assertTrue(row["ownership_path"])
            identities.append(row["governed_logical_identity"])
        self.assertEqual(len(identities), len(set(identities)))

    def test_simple_non_sha_source_keys_freeze_successfully(self) -> None:
        source_keys = {
            row["source_authority_key"]
            for row in self.specification["pathway_projection"]["rows"]
        }
        self.assertIn("notice-1", source_keys)
        self.assertIn("deadline-1", source_keys)
        self.assertIn("determination-1", source_keys)
        self.assertFalse(any(key == "notice-1" and len(key) == 64 for key in source_keys))
        reports.validate_pathway_report_specification(self.conn, self.specification)

    def test_namespaced_source_keys_freeze_successfully(self) -> None:
        conn = _fresh_connection()
        try:
            fixture = ProjectionFixture(conn)
            fixture.notice(idempotency_key=None)
            report = _create_pathway_report(conn, key="namespaced-source-key")
            rows = report["versions"][0]["specification"]["pathway_projection"]["rows"]
            source_keys = [row["source_authority_key"] for row in rows]
            self.assertTrue(any(key.startswith("stage71-notice:") for key in source_keys))
            for row in rows:
                self.assertEqual(row["row_authority_digest"], _independent_row_authority_digest(row))
        finally:
            conn.close()

    def test_formal_completion_composed_source_key_freezes_successfully(self) -> None:
        conn = _fresh_connection()
        try:
            fixture = ProjectionFixture(conn)
            remedy_determination = fixture.accepted_determination(key="formal-remedy-det")
            completion = fixture.accepted_determination(key="formal-completion-det", category="status_determination")
            remedy = fixture.remedy(determination_id=remedy_determination["id"], key="formal-remedy")
            fixture.implementation_event(
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
            report = _create_pathway_report(conn, key="formal-completion-source-key")
            rows = report["versions"][0]["specification"]["pathway_projection"]["rows"]
        finally:
            conn.close()
        formal = [row for row in rows if row["object_kind"] == "formal_completion_determination"]
        self.assertEqual(len(formal), 1)
        self.assertIn("|formal_completion|", formal[0]["source_authority_key"])
        self.assertEqual(formal[0]["row_authority_digest"], _independent_row_authority_digest(formal[0]))

    def test_obsolete_governed_digest_field_is_absent(self) -> None:
        for row in self.specification["pathway_projection"]["rows"]:
            self.assertNotIn("governed_digest", row)

    def test_coverage_unavailable_families_and_gaps_are_frozen(self) -> None:
        pathway = self.specification["pathway_projection"]
        expected_unavailable = sorted(
            key.removesuffix("_schema_present")
            for key, value in pathway["coverage"].items()
            if key.startswith("stage") and key.endswith("_schema_present") and value is False
        )
        self.assertEqual(pathway["unavailable_families"], expected_unavailable)
        self.assertIsInstance(pathway["gaps"], list)

    def test_specification_digest_matches_canonical_json(self) -> None:
        version = self.report["versions"][0]
        self.assertEqual(version["specification_digest"], reports.specification_digest(self.specification))

    def test_repeated_identical_creation_replays_idempotently(self) -> None:
        replay = _create_pathway_report(self.conn)
        self.assertEqual(replay["id"], self.report["id"])
        self.assertEqual(replay["versions"][0]["specification"], self.specification)

    def test_equivalent_physical_ids_preserve_frozen_identity(self) -> None:
        for row in self.specification["pathway_projection"]["rows"]:
            self.assertNotIn("object_id", row)
            self.assertNotIn("parent_id", row)
            self.assertNotIn("id", row)

    def test_insertion_order_variation_preserves_frozen_identity(self) -> None:
        live = reports._compact_pathway_identity(self.conn, RECORD)
        self.assertEqual(live["rows"], self.specification["pathway_projection"]["rows"])
        self.assertEqual(live["projection_digest"], self.specification["pathway_projection"]["projection_digest"])

    def test_existing_report_types_remain_unchanged(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            record = {"reference": "CR-1", "title": "Record", "finding": "Original", "status": "recorded", "version": 1}
            with patch.object(reports.rda, "record_context", return_value=record):
                item = reports.create_report(
                    conn,
                    title="Internal report",
                    purpose="Review",
                    audience="Administrators",
                    distribution_class="internal_working",
                    canonical_record_reference="CR-1",
                    document_ids=[],
                    association_ids=[],
                    sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Selected."}]}],
                    exclusions=[],
                    requested_formats=["docx"],
                    rendering_profile="internal",
                    template_version="cde-internal-v1",
                    actor="creator",
                    actor_role="administrator",
                    idempotency_key="canonical-report",
                )
            self.assertEqual(item["report_type"], "canonical_record_report")
            self.assertEqual(item["versions"][0]["specification"]["specification_schema_version"], reports.SPECIFICATION_SCHEMA_VERSION)
            self.assertNotIn("pathway_projection", item["versions"][0]["specification"])
        finally:
            conn.close()

    def test_wrong_report_type_schema_pairing_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["specification_schema_version"] = reports.SPECIFICATION_SCHEMA_VERSION
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_wrong_canonical_record_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["canonical_record_reference"] = OTHER_RECORD
        self.assertInvalidSpec(mutated, "governed_report_pathway_record_mismatch")

    def test_unknown_object_kind_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["object_kind"] = "unknown_kind"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_inventory_invalid")

    def test_missing_logical_identity_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["governed_logical_identity"] = ""
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_duplicate_logical_identity_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][1]["governed_logical_identity"] = mutated["pathway_projection"]["rows"][0]["governed_logical_identity"]
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_inventory_invalid")

    def test_malformed_projection_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["projection_digest"] = "not-a-digest"
        self.assertInvalidSpec(mutated, "governed_report_pathway_projection_digest_invalid")

    def test_missing_source_authority_key_rejects(self) -> None:
        mutated = _spec(self.report)
        del mutated["pathway_projection"]["rows"][0]["source_authority_key"]
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_null_source_authority_key_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["source_authority_key"] = None
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_blank_source_authority_key_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["source_authority_key"] = ""
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_whitespace_only_source_authority_key_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["source_authority_key"] = "   "
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_missing_ownership_path_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["ownership_path"] = ""
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_caller_supplied_pathway_authority_rejects_before_persistence(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_authority_caller_supplied"):
                reports.create_report(
                    conn,
                    title="Procedural pathway",
                    purpose="Internal pathway review",
                    audience="Internal reviewers",
                    distribution_class="internal_working",
                    canonical_record_reference=RECORD,
                    document_ids=[],
                    association_ids=[],
                    sections=[{"caller": "override"}],
                    exclusions=[],
                    requested_formats=["docx"],
                    rendering_profile=reports.PATHWAY_RENDERING_PROFILE,
                    template_version=reports.PATHWAY_TEMPLATE_VERSION,
                    actor="creator",
                    actor_role="administrator",
                    idempotency_key="caller-authority",
                    report_type=reports.PATHWAY_REPORT_TYPE,
                )
            self.assertEqual(reports.list_reports(conn), [])
        finally:
            conn.close()

    def test_non_internal_distribution_rejects(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_distribution_invalid"):
                reports.create_report(
                    conn,
                    title="Procedural pathway",
                    purpose="Internal pathway review",
                    audience="Internal reviewers",
                    distribution_class="restricted_review",
                    canonical_record_reference=RECORD,
                    document_ids=[],
                    association_ids=[],
                    sections=[],
                    exclusions=[],
                    requested_formats=["docx"],
                    rendering_profile=reports.PATHWAY_RENDERING_PROFILE,
                    template_version=reports.PATHWAY_TEMPLATE_VERSION,
                    actor="creator",
                    actor_role="administrator",
                    idempotency_key="wrong-distribution",
                    report_type=reports.PATHWAY_REPORT_TYPE,
                )
            self.assertEqual(reports.list_reports(conn), [])
        finally:
            conn.close()

    def test_partial_pathway_specification_group_rejects(self) -> None:
        mutated = _spec(self.report)
        del mutated["pathway_projection"]
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_unsupported_projection_contract_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["projection_contract"] = "stage78.pathway_projection.v0"
        self.assertInvalidSpec(mutated, "governed_report_pathway_projection_contract_unsupported")

    def test_unsupported_projection_version_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["projection_version"] = "78a2a"
        self.assertInvalidSpec(mutated, "governed_report_pathway_projection_version_unsupported")

    def test_missing_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        del mutated["pathway_projection"]["rows"][0]["row_authority_digest"]
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_blank_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = ""
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_non_hex_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = "g" * 64
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_uppercase_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = mutated["pathway_projection"]["rows"][0]["row_authority_digest"].upper()
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_short_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = "0" * 63
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_long_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = "0" * 65
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_whitespace_padded_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = f" {mutated['pathway_projection']['rows'][0]['row_authority_digest']} "
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_valid_looking_stale_row_authority_digest_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = "0" * 64
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_obsolete_governed_digest_field_rejects(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["governed_digest"] = mutated["pathway_projection"]["rows"][0]["source_authority_key"]
        self.assertInvalidSpec(mutated, "governed_report_pathway_specification_invalid")

    def test_stale_row_digest_rejects_when_status_changes_with_same_source_key(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["status"] = "synthetic_status"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_stale_row_digest_rejects_when_ownership_changes_with_same_source_key(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["ownership_path"] = "synthetic.ownership"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_stale_row_digest_rejects_when_parent_changes_with_same_source_key(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["parent_governed_identity"] = "synthetic:parent"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_stale_row_digest_rejects_when_endpoint_changes_with_same_source_key(self) -> None:
        mutated = _spec(self.report)
        row = next(item for item in mutated["pathway_projection"]["rows"] if item["endpoint_identities"])
        row["endpoint_identities"][0]["relationship_role"] = "synthetic_endpoint_role"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_stale_row_digest_rejects_when_object_kind_changes_with_same_source_key(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["object_kind"] = "procedural_deadline"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_stale_row_digest_rejects_when_logical_identity_changes_with_same_source_key(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["governed_logical_identity"] = "synthetic:identity"
        self.assertInvalidSpec(mutated, "governed_report_pathway_row_authority_digest_invalid")

    def test_recomputed_row_digest_restores_valid_mutated_authority_payload(self) -> None:
        mutated = _spec(self.report)
        mutated["pathway_projection"]["rows"][0]["status"] = "synthetic_status"
        mutated["pathway_projection"]["rows"][0]["row_authority_digest"] = _independent_row_authority_digest(mutated["pathway_projection"]["rows"][0])
        reports.validate_pathway_report_specification(self.conn, mutated)

    def test_status_drift_fails_source_validation(self) -> None:
        self.conn.execute("UPDATE record_governed_procedural_notices SET status='superseded' WHERE idempotency_key='notice-1'")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_source_authority_key_drift_fails_source_validation(self) -> None:
        self.conn.execute("UPDATE record_governed_procedural_notices SET idempotency_key='notice-mutated' WHERE idempotency_key='notice-1'")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_ownership_path_drift_fails_source_validation(self) -> None:
        row = self.conn.execute(
            "SELECT id FROM record_governed_procedural_time_object_links WHERE object_id=? AND object_type='canonical_record' ORDER BY id LIMIT 1",
            (RECORD,),
        ).fetchone()
        self.conn.execute("UPDATE record_governed_procedural_time_object_links SET object_id=? WHERE id=?", (OTHER_RECORD, row["id"]))
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_parent_identity_drift_fails_source_validation(self) -> None:
        self.conn.execute("UPDATE record_governed_deadline_calculations SET deadline_id=999 WHERE idempotency_key='calc-1'")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_endpoint_identity_drift_fails_source_validation(self) -> None:
        self.conn.execute("UPDATE record_governed_pathway_links SET target_object_id='999' WHERE idempotency_key='pathway-1'")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_withdrawal_after_freeze_fails_source_validation(self) -> None:
        self.conn.execute("UPDATE record_governed_remedies SET status='withdrawn' WHERE idempotency_key='remedy-1'")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_supersession_after_freeze_fails_source_validation(self) -> None:
        original = self.conn.execute("SELECT id FROM record_governed_determinations WHERE idempotency_key='determination-1'").fetchone()
        replacement = ProjectionFixture(self.conn).determination(key="replacement-determination")
        determinations.supersede_determination(
            self.conn,
            determination_id=original["id"],
            replacement_determination_id=replacement["id"],
            rationale="Supersession after freeze.",
            actor="reviewer",
            actor_role="administrator",
            idempotency_key="determination-after-freeze-supersession",
        )
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_cessation_after_freeze_fails_source_validation(self) -> None:
        original = self.conn.execute("SELECT id FROM record_governed_decision_authorities WHERE idempotency_key='determination-1-authority'").fetchone()
        authorities.cease_authority_record(
            self.conn,
            object_type="authority",
            object_id=original["id"],
            cessation_type="expiry_recorded",
            cessation_date_or_period="2026-12-31",
            rationale="Cessation after freeze.",
            cessation_bindings=[{"source_type": "canonical_record", "source_id": RECORD, "binding_role": "cessation_source"}],
            actor="reviewer",
            actor_role="administrator",
            idempotency_key="authority-after-freeze-cessation",
        )
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_new_in_scope_row_after_freeze_fails_source_validation(self) -> None:
        ProjectionFixture(self.conn).notice(idempotency_key="new-notice")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_removed_row_after_freeze_fails_source_validation(self) -> None:
        self.conn.execute("DELETE FROM record_governed_procedural_time_object_links WHERE record_kind='notice'")
        self.conn.execute("DELETE FROM record_governed_procedural_notices WHERE idempotency_key='notice-1'")
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_projection_digest_drift_reaches_specific_predicate(self) -> None:
        self.specification["pathway_projection"]["projection_digest"] = "0" * 64
        self.assertSourceDrift("governed_report_pathway_projection_digest_drift")

    def test_row_inventory_drift_reaches_specific_predicate(self) -> None:
        self.specification["pathway_projection"]["rows"] = self.specification["pathway_projection"]["rows"][1:]
        self.assertSourceDrift("governed_report_pathway_row_inventory_drift")

    def test_coverage_drift_reaches_specific_predicate(self) -> None:
        self.specification["pathway_projection"]["coverage"]["stage71_schema_present"] = False
        self.specification["pathway_projection"]["unavailable_families"] = ["stage71"]
        self.assertSourceDrift("governed_report_pathway_coverage_drift")

    def test_scoped_gap_drift_reaches_specific_predicate(self) -> None:
        self.specification["pathway_projection"]["gaps"].append({"gap_code": "synthetic_gap", "statement": "No governed synthetic record was found linked within this canonical-record scope.", "object_kind": "synthetic", "record_reference": RECORD, "binding_mechanism": "none", "source_field": "none", "authoritative_absence": False})
        self.assertSourceDrift("governed_report_pathway_gap_drift")

    def test_complete_family_availability_drift_fails_closed(self) -> None:
        conn = _fresh_connection()
        try:
            fixture = ProjectionFixture(conn)
            fixture.notice(idempotency_key="notice-1")
            report = _create_pathway_report(conn, key="availability-freeze")
            spec = _spec(report)
            determination = fixture.accepted_determination(key="late-determination")
            fixture.remedy(determination_id=determination["id"], key="late-remedy")
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_projection_digest_drift"):
                reports._validate_generation_sources(conn, spec)
        finally:
            conn.close()

    def test_partial_family_rejection_is_bounded(self) -> None:
        conn = _fresh_connection()
        try:
            conn.execute("CREATE TABLE record_governed_remedies (id INTEGER PRIMARY KEY)")
            conn.commit()
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_schema_incomplete"):
                _create_pathway_report(conn, key="partial-family")
        finally:
            conn.close()

    def test_canonically_equivalent_json_object_order_is_non_authoritative(self) -> None:
        reordered = json.loads(json.dumps(self.specification, sort_keys=False, indent=2))
        self.assertEqual(reports.specification_digest(reordered), reports.specification_digest(self.specification))
        reports.validate_pathway_report_specification(self.conn, reordered)

    def test_insignificant_json_whitespace_is_non_authoritative(self) -> None:
        encoded = json.dumps(self.specification, indent=2)
        decoded = json.loads(encoded)
        self.assertEqual(decoded, self.specification)
        reports._validate_generation_sources(self.conn, decoded)

    def test_array_order_mutation_is_authoritative(self) -> None:
        self.specification["pathway_projection"]["rows"] = list(reversed(self.specification["pathway_projection"]["rows"]))
        self.assertSourceDrift("governed_report_pathway_row_inventory_drift")

    def test_specification_digest_mutation_rejects_before_generation(self) -> None:
        self.conn.execute("UPDATE record_governed_report_versions SET specification_digest=? WHERE id=?", ("0" * 64, self.report["versions"][0]["id"]))
        with self.assertRaisesRegex(ValueError, "governed_report_specification_digest_mismatch"):
            reports.generate_report(self.conn, report_id=self.report["id"], actor="worker", actor_role="system", idempotency_key="generate-digest")

    def test_failed_validation_is_non_mutating(self) -> None:
        self.specification["pathway_projection"]["rows"][0]["governed_logical_identity"] = ""
        before = _all_table_counts(self.conn)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_specification_invalid"):
                reports._validate_generation_sources(self.conn, self.specification)
        self.assertEqual(before, _all_table_counts(self.conn))

    def test_generation_validation_creates_no_schema_or_governed_rows(self) -> None:
        before_tables = set(_all_table_counts(self.conn))
        before_counts = _all_table_counts(self.conn)
        reports._validate_generation_sources(self.conn, self.specification)
        self.assertEqual(before_tables, set(_all_table_counts(self.conn)))
        self.assertEqual(before_counts, _all_table_counts(self.conn))


class Stage78BFreezeTransactionTests(unittest.TestCase):
    def test_old_unlocked_sequence_can_persist_stale_freeze(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage78b-old-freeze-") as directory:
            path = Path(directory) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE source (id INTEGER PRIMARY KEY, status TEXT)")
            conn.execute("CREATE TABLE report (id INTEGER PRIMARY KEY, frozen_status TEXT)")
            conn.execute("INSERT INTO source VALUES (1, 'before')")
            conn.commit()
            frozen = conn.execute("SELECT status FROM source WHERE id=1").fetchone()[0]
            self.assertFalse(conn.in_transaction)
            external = sqlite3.connect(path)
            external.execute("UPDATE source SET status='after' WHERE id=1")
            external.commit()
            external.close()
            conn.execute("SAVEPOINT stage75_create")
            conn.execute("INSERT INTO report(frozen_status) VALUES (?)", (frozen,))
            conn.execute("RELEASE SAVEPOINT stage75_create")
            conn.commit()
            self.assertEqual(conn.execute("SELECT frozen_status FROM report").fetchone()[0], "before")
            self.assertEqual(conn.execute("SELECT status FROM source").fetchone()[0], "after")
            conn.close()

    def test_begin_immediate_excludes_concurrent_writer_under_wal_and_rollback_journal(self) -> None:
        for journal in ("WAL", "DELETE"):
            with self.subTest(journal=journal):
                with tempfile.TemporaryDirectory(prefix=f"stage78b-freeze-{journal.lower()}-") as directory:
                    db_path, conn, actual = _fresh_file_connection(directory, journal_mode=journal)
                    try:
                        _populate_projection(conn)
                        conn.commit()
                        original = reports._compact_pathway_identity
                        attempts: list[str] = []

                        def guarded_projection(active_conn: sqlite3.Connection, record_reference: str) -> dict:
                            attempts.append(_external_notice_status_update(db_path, f"during-{actual}"))
                            return original(active_conn, record_reference)

                        with patch.object(reports, "_compact_pathway_identity", side_effect=guarded_projection):
                            report = _create_pathway_report(conn, key=f"locked-{journal.lower()}")
                        self.assertIn("locked", attempts[0])
                        self.assertFalse(conn.in_transaction)
                        self.assertEqual(_external_notice_status_update(db_path, f"after-{actual}"), "committed")
                        self.assertEqual(report["versions"][0]["specification"]["pathway_projection"]["canonical_record_reference"], RECORD)
                    finally:
                        conn.close()

    def test_commit_false_keeps_owned_transaction_until_caller_releases_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage78b-commit-false-") as directory:
            db_path, conn, _ = _fresh_file_connection(directory, journal_mode="WAL")
            try:
                _populate_projection(conn)
                conn.commit()
                with patch.object(reports, "utc_now", return_value=FIXED_TIME):
                    item = reports.create_report(
                        conn,
                        title="Procedural pathway",
                        purpose="Internal pathway review",
                        audience="Internal reviewers",
                        distribution_class="internal_working",
                        canonical_record_reference=RECORD,
                        document_ids=[],
                        association_ids=[],
                        sections=[],
                        exclusions=[],
                        requested_formats=["html"],
                        rendering_profile=reports.PATHWAY_RENDERING_PROFILE,
                        template_version=reports.PATHWAY_TEMPLATE_VERSION,
                        actor="creator",
                        actor_role="administrator",
                        idempotency_key="commit-false-pathway",
                        report_type=reports.PATHWAY_REPORT_TYPE,
                        created_at=FIXED_TIME,
                        _commit=False,
                    )
                self.assertTrue(conn.in_transaction)
                self.assertIn("locked", _external_notice_status_update(db_path, "while-uncommitted"))
                conn.commit()
                self.assertFalse(conn.in_transaction)
                self.assertEqual(_external_notice_status_update(db_path, "after-caller-commit"), "committed")
                self.assertEqual(item["versions"][0]["specification"]["report_type"], reports.PATHWAY_REPORT_TYPE)
            finally:
                conn.close()

    def test_existing_caller_write_transaction_visible_and_savepoint_scoped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage78b-caller-transaction-") as directory:
            _, conn, _ = _fresh_file_connection(directory, journal_mode="WAL")
            try:
                _populate_projection(conn)
                conn.commit()
                reports.ensure_report_tables(conn)
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE records SET version='2' WHERE reference=?", (RECORD,))
                before = _report_counts(conn)
                item = _create_pathway_report(conn, key="caller-owned", _commit=False)
                self.assertEqual(item["versions"][0]["specification"]["primary_record"]["version"], "2")
                self.assertTrue(conn.in_transaction)
                conn.execute("ROLLBACK")
                self.assertEqual(_report_counts(conn), before)
            finally:
                conn.close()

    def test_read_only_connection_rejects_freeze_boundedly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage78b-readonly-") as directory:
            db_path, conn, _ = _fresh_file_connection(directory, journal_mode="WAL")
            _populate_projection(conn)
            reports.ensure_report_tables(conn)
            conn.commit()
            conn.close()
            ro = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            ro.row_factory = sqlite3.Row
            try:
                with self.assertRaisesRegex(ValueError, "governed_report_pathway_freeze_transaction_unavailable"):
                    _create_pathway_report(ro, key="readonly")
                self.assertFalse(ro.in_transaction)
            finally:
                ro.close()

    def test_projection_failure_rolls_back_and_retry_succeeds(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            with patch.object(reports, "_compact_pathway_identity", side_effect=ValueError("governed_report_pathway_schema_incomplete")):
                with self.assertRaisesRegex(ValueError, "governed_report_pathway_schema_incomplete"):
                    _create_pathway_report(conn, key="projection-failure")
            self.assertEqual(_report_counts(conn), {"reports": 0, "versions": 0, "events": 0})
            item = _create_pathway_report(conn, key="projection-failure")
            self.assertEqual(item["report_type"], reports.PATHWAY_REPORT_TYPE)
        finally:
            conn.close()

    def test_version_insert_failure_rolls_back_report_work(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            reports.ensure_report_tables(conn)
            conn.execute(
                "CREATE TRIGGER fail_stage78b_version BEFORE INSERT ON record_governed_report_versions "
                "BEGIN SELECT RAISE(ABORT, 'forced_version_failure'); END"
            )
            conn.commit()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "forced_version_failure"):
                _create_pathway_report(conn, key="version-failure")
            self.assertEqual(_report_counts(conn), {"reports": 0, "versions": 0, "events": 0})
            self.assertFalse(conn.in_transaction)
        finally:
            conn.close()

    def test_event_insert_failure_rolls_back_report_and_version_work(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            reports.ensure_report_tables(conn)
            conn.execute(
                "CREATE TRIGGER fail_stage78b_event BEFORE INSERT ON record_governed_report_events "
                "BEGIN SELECT RAISE(ABORT, 'forced_event_failure'); END"
            )
            conn.commit()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "forced_event_failure"):
                _create_pathway_report(conn, key="event-failure")
            self.assertEqual(_report_counts(conn), {"reports": 0, "versions": 0, "events": 0})
            self.assertFalse(conn.in_transaction)
        finally:
            conn.close()

    def test_caller_owned_changes_survive_savepoint_rollback(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            conn.commit()
            reports.ensure_report_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE records SET version='caller-change' WHERE reference=?", (RECORD,))
            with patch.object(reports, "_compact_pathway_identity", side_effect=ValueError("governed_report_pathway_schema_incomplete")):
                with self.assertRaisesRegex(ValueError, "governed_report_pathway_schema_incomplete"):
                    _create_pathway_report(conn, key="caller-rollback")
            self.assertEqual(conn.execute("SELECT version FROM records WHERE reference=?", (RECORD,)).fetchone()[0], "caller-change")
            self.assertEqual(_report_counts(conn), {"reports": 0, "versions": 0, "events": 0})
            conn.rollback()
        finally:
            conn.close()

    def test_exact_idempotent_replay_remains_stable_after_locking(self) -> None:
        conn = _fresh_connection()
        try:
            _populate_projection(conn)
            first = _create_pathway_report(conn, key="idempotent-lock")
            second = _create_pathway_report(conn, key="idempotent-lock")
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(_report_counts(conn), {"reports": 1, "versions": 1, "events": 1})
        finally:
            conn.close()

    def test_existing_report_type_transaction_state_remains_unchanged(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            record = {"reference": "CR-1", "title": "Record", "finding": "Original", "status": "recorded", "version": 1}
            with patch.object(reports.rda, "record_context", return_value=record):
                item = reports.create_report(
                    conn,
                    title="Internal report",
                    purpose="Review",
                    audience="Administrators",
                    distribution_class="internal_working",
                    canonical_record_reference="CR-1",
                    document_ids=[],
                    association_ids=[],
                    sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Selected."}]}],
                    exclusions=[],
                    requested_formats=["docx"],
                    rendering_profile="internal",
                    template_version="cde-internal-v1",
                    actor="creator",
                    actor_role="administrator",
                    idempotency_key="canonical-transaction-unchanged",
                    _commit=False,
                )
            self.assertEqual(item["report_type"], "canonical_record_report")
            self.assertFalse(conn.in_transaction)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
