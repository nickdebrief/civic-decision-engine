from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from api import record_governed_pathway as pathway


class Stage72PathwayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT, title TEXT);
        INSERT INTO records VALUES ('REC-72', '1', '2026-08-20T09:00:00Z', 'Canonical record');
        CREATE TABLE record_pattern_observations (id INTEGER PRIMARY KEY, status TEXT, title TEXT, created_at TEXT);
        INSERT INTO record_pattern_observations VALUES (1, 'accepted', 'Observed pattern', '2026-08-20T10:00:00Z');
        """)

    def tearDown(self) -> None:
        self.conn.close()

    def source(self) -> list[dict[str, str]]:
        return [{"source_type": "canonical_record", "source_id": "REC-72", "binding_role": "relationship_source"}]

    def create(self, **overrides):
        values = dict(
            source_object_kind="canonical_record", source_object_id="REC-72",
            target_object_kind="accepted_pattern_observation", target_object_id="1",
            relationship_type="evidence_to_observation", rationale="Preserve the represented connection.",
            reliance_status="not_represented", reliance_description=None,
            reliance_declaration={"acknowledged": True, "status": "not_represented"},
            contestation_status="not_represented", contestation_representation=None,
            limitations=pathway.LIMITATIONS_BOUNDARY, bindings=self.source(),
            actor="admin", actor_role="administrator", idempotency_key="stage72-1",
        )
        values.update(overrides)
        return pathway.create_pathway_link(self.conn, **values)

    def test_isolated_schema_and_deliberate_relationship_are_idempotent(self) -> None:
        item = self.create()
        retry = self.create()
        self.assertEqual(item["id"], retry["id"])
        self.assertEqual(item["source_object_kind"], "canonical_record")
        self.assertEqual(item["target_object_kind"], "accepted_pattern_observation")
        self.assertEqual(item["bindings"][0]["binding_role"], "relationship_source")
        tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("record_governed_pathway_links", tables)
        self.assertIn("record_governed_pathway_bindings", tables)

    def test_closed_directions_endpoints_and_reliance_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "direction_invalid"):
            self.create(target_object_kind="governed_inference", target_object_id="1", relationship_type="evidence_to_observation")
        with self.assertRaisesRegex(ValueError, "self_link"):
            self.create(source_object_kind="accepted_pattern_observation", source_object_id="1", target_object_kind="accepted_pattern_observation", target_object_id="1", relationship_type="evidence_to_observation")
        with self.assertRaisesRegex(ValueError, "endpoint_not_found"):
            self.create(source_object_id="MISSING")
        with self.assertRaisesRegex(ValueError, "description_required"):
            self.create(reliance_status="expressly_relied_upon", reliance_declaration={"acknowledged": True, "status": "expressly_relied_upon"})
        with self.assertRaisesRegex(ValueError, "declaration_required"):
            self.create(reliance_declaration={"acknowledged": False, "status": "not_represented"})
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.create(bindings=[{"source_type": "canonical_record", "source_id": "REC-72", "binding_role": "relationship_source", "unexpected": True}])

    def test_conflicting_idempotency_and_append_only_lifecycle(self) -> None:
        item = self.create()
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(rationale="Different content")
        reviewed = pathway.review_pathway_link(self.conn, link_id=item["id"], disposition="accepted_as_represented_pathway", rationale="Faithfully represented.", boundary_declaration={"acknowledged": True, "status": "not_represented"}, actor="reviewer", actor_role="administrator", idempotency_key="review-72")
        self.assertEqual(reviewed["status"], "accepted_as_represented_pathway")
        replacement = self.create(idempotency_key="stage72-2", target_object_id="1")
        superseded = pathway.supersede_pathway_link(self.conn, link_id=item["id"], replacement_link_id=replacement["id"], rationale="Corrected representation.", actor="admin", actor_role="administrator", idempotency_key="sup-72")
        self.assertEqual(superseded["status"], "superseded")
        self.assertEqual(pathway.get_pathway_link(self.conn, replacement["id"])["status"], "recorded")
        with self.assertRaisesRegex(ValueError, "terminal"):
            pathway.review_pathway_link(self.conn, link_id=item["id"], disposition="requires_pathway_correction", rationale="Late review.", boundary_declaration={"acknowledged": True, "status": "not_represented"}, actor="reviewer", actor_role="administrator", idempotency_key="review-after-supersession")

    def test_supersession_cycle_is_rejected(self) -> None:
        first = self.create(idempotency_key="stage72-cycle-1")
        second = self.create(idempotency_key="stage72-cycle-2")
        third = self.create(idempotency_key="stage72-cycle-3")
        pathway.supersede_pathway_link(self.conn, link_id=first["id"], replacement_link_id=second["id"], rationale="First correction.", actor="admin", actor_role="administrator", idempotency_key="sup-cycle-1")
        pathway.supersede_pathway_link(self.conn, link_id=second["id"], replacement_link_id=third["id"], rationale="Second correction.", actor="admin", actor_role="administrator", idempotency_key="sup-cycle-2")
        with self.assertRaisesRegex(ValueError, "cycle"):
            pathway.supersede_pathway_link(self.conn, link_id=third["id"], replacement_link_id=first["id"], rationale="Cycle attempt.", actor="admin", actor_role="administrator", idempotency_key="sup-cycle-3")

    def test_read_only_diagnostic_does_not_initialize_tables(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            result = pathway.read_pathway_diagnostic(db_path=handle.name)
            self.assertFalse(result["pathway_table_present"])
            self.assertEqual(pathway.read_candidates(db_path=handle.name), [])
            check = sqlite3.connect(handle.name)
            self.assertIsNone(check.execute("SELECT name FROM sqlite_master WHERE name='record_governed_pathway_links'").fetchone())
            check.close()

    def test_canonical_projection_is_distinct_and_deterministic(self) -> None:
        self.conn.execute("CREATE TABLE record_governed_response_allegation_links (id INTEGER PRIMARY KEY, response_id INTEGER, allegation_id INTEGER)")
        self.conn.execute("INSERT INTO record_governed_response_allegation_links VALUES (1, 7, 8)")
        self.conn.commit()
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            disk = sqlite3.connect(handle.name)
            self.conn.backup(disk)
            disk.commit(); disk.close()
            projected = pathway.project_canonical_relationships(db_path=handle.name)
        self.assertEqual(projected[0]["provenance"], "canonical_existing_relationship")
        self.assertEqual(projected[0]["relationship_type"], "allegation_to_response")

    def test_admin_surface_is_authenticated_and_deliberately_empty(self) -> None:
        from api.routes import admin_session
        from api.public_navigation import public_primary_navigation

        html = admin_session._stage72_html(admin_session={"username": "admin"}, diagnostic={"links": []}, candidates=[], sources=[{"source_type": "canonical_record", "source_id": "REC-72", "label": "Canonical record", "status": "recorded"}], canonical=[])
        self.assertIn("A LINK RECORDS A REPRESENTED RELATIONSHIP", html)
        self.assertIn("Choose relationship type", html)
        self.assertIn("Choose source object", html)
        self.assertIn("Choose target object", html)
        self.assertIn('value=""', html)
        self.assertIn("CHRONOLOGY IS NOT CAUSATION", html)
        self.assertIn("created_at", html)
        self.assertIn('value="canonical_record::REC-72"', html)
        self.assertIn('if(item.hidden&&item.selected)select.value=""', html)
        self.assertIn("/admin/governed-pathway", html)
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/admin/governed-pathway"', source)
        self.assertIn("require_admin_session(request)", source)
        self.assertNotIn("@router.get(\"/pathway\"", source)
        self.assertNotIn("Governed Decision Pathway", public_primary_navigation(active="archive"))

    def test_visible_endpoint_payload_is_server_usable_without_javascript(self) -> None:
        from api.routes.admin_session import _stage72_endpoint_payload

        self.assertEqual(_stage72_endpoint_payload("canonical_record::REC-72", None, None, "source_required"), ("canonical_record", "REC-72"))
        self.assertEqual(_stage72_endpoint_payload(None, "canonical_record", "REC-72", "source_required"), ("canonical_record", "REC-72"))
        with self.assertRaisesRegex(ValueError, "mismatch"):
            _stage72_endpoint_payload("canonical_record::REC-72", "accepted_pattern_observation", "1", "source_required")

    def test_contestation_requires_a_representation_without_reversing_the_link(self) -> None:
        with self.assertRaisesRegex(ValueError, "contestation_representation_required"):
            self.create(contestation_status="disputed_as_recorded")
        item = self.create(contestation_status="disputed_as_recorded", contestation_representation="A contrary representation was recorded.", idempotency_key="contested-72")
        self.assertEqual(item["contestation_status"], "disputed_as_recorded")
        self.assertEqual(item["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
