import unittest

from api import record_governed_decision_authorities as authority
from tests.test_stage66_governed_decision_authority import Stage66AuthorityTests


class Stage661ClassificationTests(Stage66AuthorityTests):
    def test_form_classifications_begin_neutral_and_source_payload_is_empty(self):
        from api.routes.admin_session import _stage66_html

        html = _stage66_html({"authorities": []}, admin_session={"username": "admin"}, candidates=[])
        self.assertIn('Choose holder kind', html)
        self.assertIn('Choose mandate basis', html)
        self.assertIn('Choose delegation status', html)
        self.assertIn('Choose binding role', html)
        self.assertIn('id="stage66-source-payload" value=""', html)
        self.assertNotIn('value="institution" selected', html)
        self.assertNotIn('value="appointment_instrument" selected', html)
        self.assertNotIn('value="appointment_source" selected', html)

    def test_classifications_are_required_and_never_coerced(self):
        with self.assertRaisesRegex(ValueError, "holder_kind_required"):
            self.create(holder_kind="")
        with self.assertRaisesRegex(ValueError, "holder_kind_invalid"):
            self.create(holder_kind="institutional")
        with self.assertRaisesRegex(ValueError, "basis_category_required"):
            self.create(mandate=self.mandate(mandate_basis_category=""))
        with self.assertRaisesRegex(ValueError, "basis_category_invalid"):
            self.create(mandate=self.mandate(mandate_basis_category="placeholder"))
        with self.assertRaisesRegex(ValueError, "delegation_status_required"):
            self.create(mandate={**self.mandate(), "delegation_status": None})
        with self.assertRaisesRegex(ValueError, "delegation_status_invalid"):
            self.create(mandate=self.mandate(delegation_status="placeholder"))

    def test_valid_classifications_persist_exactly_and_roles_are_not_inferred(self):
        item = self.create(
            holder_kind="office",
            mandate=self.mandate(mandate_basis_category="appointment_instrument"),
            bindings=self.bindings(("canonical_record", "REC-1", "authority_basis_source")),
        )
        self.assertEqual(item["holder_kind"], "office")
        self.assertEqual(item["mandates"][0]["mandate_basis_category"], "appointment_instrument")
        self.assertEqual(item["mandates"][0]["delegation_status"], "not_delegated")
        with self.assertRaisesRegex(ValueError, "authority_basis_source_required"):
            self.create(bindings=self.bindings(("canonical_record", "REC-1", "appointment_source")))

    def test_conditional_declarations_and_delegation_fields_are_server_enforced(self):
        with self.assertRaisesRegex(ValueError, "appointment_declaration_inapplicable"):
            self.create(appointment_declaration={"acknowledged": True})
        with self.assertRaisesRegex(ValueError, "appointment_declaration_inapplicable"):
            self.create(appointment_declaration={"unexpected": "tampered"})
        with self.assertRaisesRegex(ValueError, "appointment_declaration_required"):
            self.create(holder_kind="named_person", named_holder="A. Person", bindings=self.bindings(("canonical_record", "REC-1", "authority_basis_source"), ("canonical_record", "REC-2", "appointment_source")))
        parent = self.create(idempotency_key="classification-parent", mandate_idempotency_key="classification-parent-mandate")
        with self.assertRaisesRegex(ValueError, "delegation_parent_required"):
            self.create(mandate=self.mandate(delegation_status="delegated"))
        with self.assertRaisesRegex(ValueError, "delegation_fields_inapplicable"):
            authority.create_mandate(self.conn, authority_id=parent["id"], **self.mandate(delegating_authority_id=parent["id"], delegating_mandate_id=parent["mandates"][0]["id"], delegation_source_declaration={"acknowledged": True}), qualification_contract=self.qualification(), recorder_declaration={"acknowledged": True}, bindings=self.bindings(), actor="admin", actor_role="administrator")

    def test_js_independent_validation_and_read_only_diagnostic(self):
        parent = self.create(idempotency_key="js-independent-authority", mandate_idempotency_key="js-independent-mandate")
        with self.assertRaisesRegex(ValueError, "delegation_status_required"):
            authority.create_mandate(self.conn, authority_id=parent["id"], **{**self.mandate(), "delegation_status": None}, qualification_contract=self.qualification(), recorder_declaration={"acknowledged": True}, bindings=self.bindings(), actor="admin", actor_role="administrator")
        self.assertEqual(self.conn.execute("select count(*) from record_governed_decision_authorities").fetchone()[0], 1)

    def test_accessible_conditional_controls_and_boundary_language(self):
        from api.routes.admin_session import _stage66_html

        html = _stage66_html({"authorities": []}, admin_session={"username": "admin"}, candidates=[])
        for control in ("stage66-holder-kind", "stage66-mandate-basis", "stage66-delegation-status", "stage66-appointment-controls", "stage66-delegation-controls", "stage66-role-guidance"):
            self.assertIn(control, html)
        self.assertIn("AUTHORITY PRECEDES DETERMINATION", html)
        self.assertIn("does not confer authority", html)
        self.assertNotIn("currently authorised", html)


if __name__ == "__main__":
    unittest.main()
