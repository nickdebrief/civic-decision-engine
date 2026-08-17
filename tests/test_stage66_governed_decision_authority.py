import sqlite3
import unittest

from api import record_governed_decision_authorities as authority


class Stage66AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT)"
        )
        self.conn.executemany(
            "INSERT INTO records VALUES (?, ?, ?)",
            [("REC-1", "1", "2026-01-01"), ("REC-2", "1", "2026-01-02")],
        )
        self.conn.execute(
            "CREATE TABLE record_pattern_observations (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)"
        )
        self.conn.executemany(
            "INSERT INTO record_pattern_observations VALUES (?, ?, ?)",
            [(1, "accepted", "2026-01-01"), (2, "proposed", "2026-01-02")],
        )

    def tearDown(self):
        self.conn.close()

    def qualification(self):
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

    def bindings(self, *items):
        return [
            {"source_type": kind, "source_id": ident, "binding_role": role}
            for kind, ident, role in (items or (("canonical_record", "REC-1", "authority_basis_source"),))
        ]

    def mandate(self, **overrides):
        value = {
            "mandate_basis_category": "governance_instrument",
            "title_label": "Review mandate",
            "subject_matter_scope": "governed records",
            "procedural_scope": "administrative review",
            "territorial_organisational_scope": "CDE",
            "affected_class": "record",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "express_limitations": "No substantive determination.",
            "conditions_prerequisites": "Source-backed inspection only.",
            "rationale": "Preserve the represented mandate.",
            "qualification": "A source-backed representation only.",
            "limitations": "The source may be incomplete or contested.",
        }
        value.update(overrides)
        return value

    def create(self, **overrides):
        value = {
            "holder_kind": "office",
            "holder_label": "Review Office",
            "institution_context": "CDE",
            "office_role_capacity": "Administrative review office",
            "named_holder": None,
            "holder_effective_period": "2026-01-01 onward as represented",
            "attribution_context": "Governance instrument",
            "rationale": "Preserve a source-backed representation.",
            "qualification": "This is a governed representation only.",
            "limitations": "Authority is not conferred or validated.",
            "qualification_contract": self.qualification(),
            "recorder_declaration": {"acknowledged": True},
            "bindings": self.bindings(),
            "mandate": self.mandate(),
            "actor": "admin",
            "actor_role": "administrator",
        }
        value.update(overrides)
        return authority.create_authority(self.conn, **value)

    def test_valid_creation_keeps_authority_and_mandate_distinct(self):
        item = self.create()
        self.assertNotEqual(("authority", item["id"]), ("mandate", item["mandates"][0]["id"]))
        self.assertEqual(item["status"], "recorded")
        self.assertEqual(item["mandates"][0]["status"], "recorded")
        self.assertEqual(item["authoring_mode"], "human_recorded")
        self.assertEqual(item["schema_version"], authority.SCHEMA_VERSION)

    def test_closed_holder_and_basis_vocabularies(self):
        with self.assertRaisesRegex(ValueError, "holder_kind_invalid"):
            self.create(holder_kind="determination")
        with self.assertRaisesRegex(ValueError, "basis_category_invalid"):
            self.create(mandate=self.mandate(mandate_basis_category="legal_validity"))

    def test_basis_required_and_non_basis_sources_cannot_substitute(self):
        for role in ("contextual_source", "contrary_source"):
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "authority_basis_source_required"):
                self.create(bindings=self.bindings(("canonical_record", "REC-1", role)))
        with self.assertRaisesRegex(ValueError, "observation_cannot_be_sole_basis"):
            self.create(bindings=self.bindings(("accepted_pattern_observation", "1", "authority_basis_source")))
        for source_type in ("governed_inference", "governed_allegation", "governed_response"):
            with self.subTest(source_type=source_type), self.assertRaisesRegex(ValueError, "source_type_invalid"):
                self.create(bindings=self.bindings((source_type, "1", "authority_basis_source")))

    def test_accepted_observation_can_be_context_only(self):
        item = self.create(bindings=self.bindings(("canonical_record", "REC-1", "authority_basis_source"), ("accepted_pattern_observation", "1", "contextual_source")))
        self.assertEqual(len(item["bindings"]), 2)

    def test_unknown_binding_and_invalid_source_roll_back_all_stage66_rows(self):
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.create(bindings=[{"source_type": "canonical_record", "source_id": "REC-1", "binding_role": "authority_basis_source", "unexpected": True}])
        self.assertFalse(authority._table_exists(self.conn, "record_governed_decision_authorities"))
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self.create(bindings=self.bindings(("canonical_record", "MISSING", "authority_basis_source")))
        self.assertFalse(authority._table_exists(self.conn, "record_governed_decision_authorities"))

    def test_creation_and_mandate_idempotency(self):
        first = self.create(idempotency_key="authority-key", mandate_idempotency_key="mandate-key")
        second = self.create(idempotency_key="authority-key", mandate_idempotency_key="mandate-key")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["mandates"][0]["id"], second["mandates"][0]["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(idempotency_key="authority-key", holder_label="Changed", mandate_idempotency_key="mandate-key")

    def test_named_person_requires_capacity_appointment_source_and_declaration(self):
        args = {
            "holder_kind": "named_person",
            "named_holder": "A. Person",
            "bindings": self.bindings(("canonical_record", "REC-1", "authority_basis_source")),
        }
        with self.assertRaisesRegex(ValueError, "appointment_source_required"):
            self.create(**args)
        args["bindings"] = self.bindings(("canonical_record", "REC-1", "authority_basis_source"), ("canonical_record", "REC-2", "appointment_source"))
        with self.assertRaisesRegex(ValueError, "appointment_declaration_required"):
            self.create(**args)
        item = self.create(**args, appointment_declaration={"acknowledged": True})
        self.assertTrue(item["appointment_declaration"]["acknowledged"])

    def test_title_or_existing_decision_authorship_does_not_create_authority(self):
        self.assertRaises(ValueError, self.create, office_role_capacity="")
        self.assertEqual(authority.list_authorities(self.conn), [])

    def test_delegation_requires_parent_source_declaration_and_does_not_inherit_scope(self):
        parent = self.create()
        delegated = self.create(holder_label="Delegated Office")
        mandate = self.mandate(
            mandate_basis_category="delegation_instrument",
            subject_matter_scope="narrow delegated records",
            delegation_status="delegated",
            delegating_authority_id=parent["id"],
            delegating_mandate_id=parent["mandates"][0]["id"],
        )
        # Direct creation of a delegated mandate requires its own delegation source.
        with self.assertRaisesRegex(ValueError, "delegation_source_required"):
            authority.create_mandate(self.conn, authority_id=delegated["id"], **mandate, qualification_contract=self.qualification(), recorder_declaration={"acknowledged": True}, bindings=self.bindings(), actor="admin", actor_role="administrator")
        delegation_bindings = self.bindings(("canonical_record", "REC-1", "authority_basis_source"), ("canonical_record", "REC-2", "delegation_source"))
        with self.assertRaisesRegex(ValueError, "delegation_declaration_required"):
            authority.create_mandate(self.conn, authority_id=delegated["id"], **mandate, qualification_contract=self.qualification(), recorder_declaration={"acknowledged": True}, bindings=delegation_bindings, actor="admin", actor_role="administrator")
        created = authority.create_mandate(self.conn, authority_id=delegated["id"], **mandate, qualification_contract=self.qualification(), recorder_declaration={"acknowledged": True}, delegation_source_declaration={"acknowledged": True}, bindings=delegation_bindings, actor="admin", actor_role="administrator")
        self.assertEqual(created["subject_matter_scope"], "narrow delegated records")
        self.assertEqual(authority.get_mandate(self.conn, parent["mandates"][0]["id"])["subject_matter_scope"], "governed records")
        with self.assertRaisesRegex(ValueError, "delegation_status_invalid"):
            self.create(mandate=self.mandate(delegation_status="unknown"))

    def test_dates_are_representation_not_indefinite_validity(self):
        item = self.create(holder_effective_period="from source", mandate=self.mandate(effective_to=None))
        self.assertEqual(item["mandates"][0]["effective_to"], None)
        self.assertNotIn("indefinite", str(item).lower())

    def test_review_is_append_only_and_self_review_is_recorded(self):
        item = self.create()
        reviewed = authority.review_authority(self.conn, authority_id=item["id"], mandate_id=None, disposition="accepted_as_source_backed_authority_record", rationale="Source-backed representation may remain recorded.", boundary_declaration={"acknowledged": True}, actor="admin", actor_role="administrator", idempotency_key="review-1")
        self.assertEqual(reviewed["status"], "accepted_as_source_backed_authority_record")
        self.assertEqual(reviewed["reviews"][0]["is_self_review"], 1)
        authority.review_authority(self.conn, authority_id=item["id"], mandate_id=None, disposition="accepted_as_source_backed_authority_record", rationale="Source-backed representation may remain recorded.", boundary_declaration={"acknowledged": True}, actor="admin", actor_role="administrator", idempotency_key="review-1")
        self.assertEqual(self.conn.execute("select count(*) from record_governed_decision_authority_reviews").fetchone()[0], 1)

    def test_mandate_review_cannot_be_attached_to_another_authority(self):
        first = self.create(idempotency_key="a1", mandate_idempotency_key="m1")
        second = self.create(holder_label="Other", idempotency_key="a2", mandate_idempotency_key="m2")
        with self.assertRaisesRegex(ValueError, "target_mismatch"):
            authority.review_authority(self.conn, authority_id=second["id"], mandate_id=first["mandates"][0]["id"], disposition="accepted_as_source_backed_authority_record", rationale="mismatch", boundary_declaration={"acknowledged": True}, actor="admin", actor_role="administrator")

    def test_supersession_preserves_original_rejects_self_and_cycles(self):
        first = self.create(idempotency_key="a1", mandate_idempotency_key="m1")
        second = self.create(holder_label="Replacement", idempotency_key="a2", mandate_idempotency_key="m2")
        with self.assertRaisesRegex(ValueError, "self_reference"):
            authority.supersede_authority_record(self.conn, object_type="authority", object_id=first["id"], replacement_id=first["id"], rationale="x", actor="admin", actor_role="administrator")
        authority.supersede_authority_record(self.conn, object_type="authority", object_id=first["id"], replacement_id=second["id"], rationale="More precise record", actor="admin", actor_role="administrator", idempotency_key="s1")
        with self.assertRaisesRegex(ValueError, "cycle_rejected"):
            authority.supersede_authority_record(self.conn, object_type="authority", object_id=second["id"], replacement_id=first["id"], rationale="cycle", actor="admin", actor_role="administrator")
        self.assertEqual(authority.get_authority(self.conn, first["id"])["status"], "superseded")
        self.assertEqual(len(authority.get_authority(self.conn, first["id"])["bindings"]), 1)

    def test_cessation_requires_source_is_idempotent_and_terminal_orders_are_deterministic(self):
        item = self.create(idempotency_key="a1", mandate_idempotency_key="m1")
        with self.assertRaisesRegex(ValueError, "binding_role_invalid"):
            authority.cease_authority_record(self.conn, object_type="authority", object_id=item["id"], cessation_type="expiry_recorded", cessation_date_or_period="2027", rationale="source-backed cessation", cessation_bindings=self.bindings(("canonical_record", "REC-1", "contextual_source")), actor="admin", actor_role="administrator")
        with self.assertRaisesRegex(ValueError, "binding_required"):
            authority.cease_authority_record(self.conn, object_type="authority", object_id=item["id"], cessation_type="expiry_recorded", cessation_date_or_period="2027", rationale="source-backed cessation", cessation_bindings=[], actor="admin", actor_role="administrator")
        cessation = self.bindings(("canonical_record", "REC-2", "cessation_source"))
        authority.cease_authority_record(self.conn, object_type="authority", object_id=item["id"], cessation_type="expiry_recorded", cessation_date_or_period="2027", rationale="source-backed cessation", cessation_bindings=cessation, actor="admin", actor_role="administrator", idempotency_key="c1")
        authority.cease_authority_record(self.conn, object_type="authority", object_id=item["id"], cessation_type="expiry_recorded", cessation_date_or_period="2027", rationale="source-backed cessation", cessation_bindings=cessation, actor="admin", actor_role="administrator", idempotency_key="c1")
        self.assertEqual(authority.get_authority(self.conn, item["id"])["status"], "ceased")
        with self.assertRaisesRegex(ValueError, "supersession_terminal"):
            other = self.create(holder_label="Other", idempotency_key="a2", mandate_idempotency_key="m2")
            authority.supersede_authority_record(self.conn, object_type="authority", object_id=item["id"], replacement_id=other["id"], rationale="late", actor="admin", actor_role="administrator")

    def test_superseded_record_cannot_be_ceased(self):
        first = self.create(idempotency_key="a1", mandate_idempotency_key="m1")
        second = self.create(holder_label="Replacement", idempotency_key="a2", mandate_idempotency_key="m2")
        authority.supersede_authority_record(self.conn, object_type="authority", object_id=first["id"], replacement_id=second["id"], rationale="replace", actor="admin", actor_role="administrator")
        with self.assertRaisesRegex(ValueError, "cessation_terminal"):
            authority.cease_authority_record(self.conn, object_type="authority", object_id=first["id"], cessation_type="expiry_recorded", cessation_date_or_period="2027", rationale="late", cessation_bindings=self.bindings(("canonical_record", "REC-2", "cessation_source")), actor="admin", actor_role="administrator")

    def test_read_only_diagnostic_does_not_initialize_tables(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as db:
            result = authority.read_authority_diagnostic(db_path=db.name)
            self.assertFalse(result["authority_table_present"])
            self.assertFalse(self.conn.execute("select 1 from sqlite_master where name like 'record_governed_decision_authority%'").fetchone())

    def test_no_determination_status_or_public_surface_in_persistence_vocabulary(self):
        forbidden = {"confirmed", "valid", "lawful", "currently_authorised", "determination", "finding"}
        self.assertTrue(forbidden.isdisjoint(authority.AUTHORITY_STATUSES))
        self.assertFalse(hasattr(authority, "create_determination"))

    def test_admin_source_selector_is_deliberate_empty_and_non_public(self):
        from api.routes import admin_session
        from types import SimpleNamespace

        selector = admin_session._stage66_source_selector([
            {"source_type": "canonical_record", "source_id": "REC-1", "label": "Record <one>", "status": "Recorded", "description": ""}
        ])
        self.assertIn('name="authority_bindings_json"', selector)
        self.assertIn('value=""', selector)
        self.assertNotIn("<textarea", selector)
        self.assertIn("Record &lt;one&gt;", selector)
        self.assertNotIn("withdrawal_source", selector)
        self.assertIn("Remove", selector)
        page = admin_session._stage66_html({"authorities": []}, admin_session={"username": "admin"}, candidates=[])
        self.assertIn("AUTHORITY PRECEDES DETERMINATION", page)
        self.assertNotIn("/authority", page.split("<nav", 1)[0])
        import inspect
        route_source = inspect.getsource(admin_session)
        self.assertIn('"/admin/governed-decision-authorities"', route_source)
        self.assertIn('"/admin/governed-decision-authorities/{authority_id}"', route_source)
        self.assertIn('"/api/admin/session/governed-decision-authorities"', route_source)
        self.assertNotIn('@router.get("/governed-decision-authorities"', route_source)
        with self.assertRaises(Exception) as error:
            admin_session.require_admin_session(SimpleNamespace(cookies={}))
        self.assertEqual(error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
