import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from html import unescape

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import document_lifecycle_events as lifecycle_events
from api.document_intake import store_pending_document, update_intake_status
from api.routes import admin_session


PDF_BYTES = b"%PDF-1.7\nstage-57-confirmation\n%%EOF\n"


def confirmation_token(response) -> str:
    match = re.search(
        r'name="confirmation_token" value="([^"]+)"',
        str(response.content or ""),
    )
    if not match:
        raise AssertionError("lifecycle confirmation token not rendered")
    return unescape(match.group(1))


class Stage57GovernedLifecycleDecisionConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.root = self.base / "pending"
        self.db_path = self.base / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "stage-57-session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.original_db_path = admin_session.DB_PATH
        admin_session.DB_PATH = self.db_path
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: session},
            query_params={},
        )

    def tearDown(self):
        admin_session.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, suffix=""):
        return store_pending_document(
            data=PDF_BYTES + suffix.encode(),
            original_filename=f"stage-57{suffix}.pdf",
            content_type="application/pdf",
            title="Stage 57 confirmation fixture",
            institution_source="Civic Office",
            document_date="2026-08-09",
            category="Decision",
            description="Synthetic confirmation fixture.",
            visibility="private",
            notes="Private administrative context.",
            reference_identifier=f"STAGE-57{suffix}",
            actor="intake-admin",
            uploaded_at="2026-08-09T09:00:00Z",
            root=self.root,
        )

    def _events(self, intake_id):
        return lifecycle_events.list_lifecycle_decisions(
            intake_id=intake_id,
            db_path=self.db_path,
        )

    def _metadata_path(self, item):
        return self.root / item["intake_id"] / "metadata.json"

    def _under_review(self, item):
        return update_intake_status(
            item["intake_id"],
            "under_review",
            actor="admin-user",
            actor_role="admin",
            note="Begin review.",
            root=self.root,
            lifecycle_db_path=self.db_path,
        )

    def _preview(self, item, new_status, note):
        return admin_session.admin_document_intake_status_update(
            item["intake_id"],
            self.request,
            new_status=new_status,
            admin_note=note,
        )

    def _confirm(self, item, preview):
        return admin_session.admin_document_intake_status_confirm(
            item["intake_id"],
            self.request,
            confirmation_token=confirmation_token(preview),
        )

    def _unsigned_token_variant(self, token, **changes):
        payload_b64, signature = token.split(".", 1)
        payload = json.loads(admin_session._b64decode(payload_b64).decode("utf-8"))
        payload.update(changes)
        encoded = admin_session._b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        return encoded + "." + signature

    def _assert_rejected_without_mutation(self, item, token):
        metadata_path = self._metadata_path(item)
        before_metadata = metadata_path.read_bytes()
        before_events = self._events(item["intake_id"])
        with self.assertRaises(FakeHTTPException) as context:
            admin_session.admin_document_intake_status_confirm(
                item["intake_id"], self.request, confirmation_token=token
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(metadata_path.read_bytes(), before_metadata)
        self.assertEqual(self._events(item["intake_id"]), before_events)

    def test_selecting_approve_or_reject_only_renders_signed_proposal(self):
        for index, new_status in enumerate(("approved", "rejected")):
            with self.subTest(new_status=new_status):
                item = self._store(str(index))
                self._under_review(item)
                before = self._events(item["intake_id"])
                preview = self._preview(item, new_status, "Decision rationale.")
                content = str(preview.content)
                self.assertEqual(self._events(item["intake_id"]), before)
                self.assertIn("Proposed state", content)
                self.assertIn(new_status.title(), content)
                self.assertIn(
                    "Confirm Approval" if new_status == "approved" else "Confirm Rejection",
                    content,
                )

    def test_incident_flow_makes_rejection_consequence_explicit(self):
        item = self._store()
        self._under_review(item)
        rationale = "Approval-style rationale entered during review."
        preview = self._preview(item, "rejected", rationale)
        self.assertIn("Proposed state", str(preview.content))
        self.assertIn("Rejected", str(preview.content))
        self.assertIn("Confirm Rejection", str(preview.content))
        before = self._metadata_path(item).read_bytes()
        event_count = len(self._events(item["intake_id"]))

        # Cancel is the ordinary back link; no confirmation POST is made.
        self.assertEqual(self._metadata_path(item).read_bytes(), before)
        self.assertEqual(len(self._events(item["intake_id"])), event_count)

        self._confirm(item, preview)
        events = self._events(item["intake_id"])
        self.assertEqual(len(events), event_count + 1)
        self.assertEqual(events[-1]["new_status"], "rejected")
        self.assertEqual(events[-1]["rationale"], rationale)

    def test_confirmed_rationale_actor_and_role_are_exactly_recorded(self):
        item = self._store()
        self._under_review(item)
        preview = self._preview(item, "approved", "  Approve after review.  ")
        self.assertIn("Approve after review.", str(preview.content))
        self._confirm(item, preview)
        event = self._events(item["intake_id"])[-1]
        self.assertEqual(event["new_status"], "approved")
        self.assertEqual(event["rationale"], "Approve after review.")
        self.assertEqual(event["actor"], "admin-user")
        self.assertEqual(event["actor_role"], "admin")

    def test_signed_proposal_cannot_be_tampered_or_change_actor(self):
        item = self._store()
        self._under_review(item)
        preview = self._preview(item, "rejected", "Reject for documented reason.")
        token = confirmation_token(preview)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with self.assertRaises(FakeHTTPException) as context:
            admin_session.admin_document_intake_status_confirm(
                item["intake_id"],
                self.request,
                confirmation_token=tampered,
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(len(self._events(item["intake_id"])), 1)

    def test_stale_confirmation_fails_without_overwriting_other_decision(self):
        item = self._store()
        self._under_review(item)
        preview = self._preview(item, "rejected", "Reject after review.")
        update_intake_status(
            item["intake_id"],
            "approved",
            actor="admin-user",
            actor_role="admin",
            note="Approved in a competing request.",
            root=self.root,
            lifecycle_db_path=self.db_path,
        )
        with self.assertRaises(FakeHTTPException) as context:
            self._confirm(item, preview)
        self.assertEqual(context.exception.status_code, 409)
        events = self._events(item["intake_id"])
        self.assertEqual([event["new_status"] for event in events], ["under_review", "approved"])

    def test_identical_confirmation_retry_is_idempotent(self):
        item = self._store()
        self._under_review(item)
        preview = self._preview(item, "approved", "Approve once.")
        self._confirm(item, preview)
        self._confirm(item, preview)
        events = self._events(item["intake_id"])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["new_status"], "approved")

    def test_get_review_is_observational(self):
        item = self._store()
        self._under_review(item)
        metadata_path = self._metadata_path(item)
        before_metadata = metadata_path.read_bytes()
        before_events = self._events(item["intake_id"])
        before_paths = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        response = admin_session.admin_document_intake_preview_page(
            item["intake_id"], self.request
        )
        after_paths = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(metadata_path.read_bytes(), before_metadata)
        self.assertEqual(self._events(item["intake_id"]), before_events)
        self.assertEqual(after_paths, before_paths)

    def test_stage56_rationale_and_digest_rules_still_apply_before_confirmation(self):
        item = self._store()
        self._under_review(item)
        for note in (None, "   ", "x" * 501):
            with self.subTest(note=note), self.assertRaises(FakeHTTPException):
                self._preview(item, "approved", note)
        metadata_path = self._metadata_path(item)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["sha256_hash"] = None
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(FakeHTTPException):
            self._preview(item, "approved", "Approve with missing digest.")
        self.assertEqual(len(self._events(item["intake_id"])), 1)

    def test_publication_confirmation_requires_explicit_consequence(self):
        item = self._store()
        self._under_review(item)
        approved = self._preview(item, "approved", "Approve for publication.")
        self._confirm(item, approved)
        before = self._events(item["intake_id"])
        preview = self._preview(item, "published", "Publish after approval.")
        self.assertEqual(self._events(item["intake_id"]), before)
        self.assertIn("Proposed state", str(preview.content))
        self.assertIn("Confirm Publication", str(preview.content))
        self._confirm(item, preview)
        events = self._events(item["intake_id"])
        self.assertEqual(len(events), len(before) + 1)
        self.assertEqual(events[-1]["previous_status"], "approved")
        self.assertEqual(events[-1]["new_status"], "published")

    def test_archive_confirmation_requires_explicit_consequence(self):
        item = self._store()
        self._under_review(item)
        approved = self._preview(item, "approved", "Approve before archive.")
        self._confirm(item, approved)
        published = self._preview(item, "published", "Publish before archive.")
        self._confirm(item, published)
        before = self._events(item["intake_id"])
        preview = self._preview(item, "archived", "Archive after publication.")
        self.assertEqual(self._events(item["intake_id"]), before)
        self.assertIn("Confirm Archival", str(preview.content))
        self._confirm(item, preview)
        events = self._events(item["intake_id"])
        self.assertEqual(len(events), len(before) + 1)
        self.assertEqual(events[-1]["previous_status"], "published")
        self.assertEqual(events[-1]["new_status"], "archived")

    def test_cancel_navigation_is_observational(self):
        item = self._store()
        self._under_review(item)
        preview = self._preview(item, "rejected", "Cancel this proposal.")
        metadata_path = self._metadata_path(item)
        before_metadata = metadata_path.read_bytes()
        before_events = self._events(item["intake_id"])
        before_status_history = json.loads(before_metadata)["status_history"]
        response = admin_session.admin_document_intake_preview_page(
            item["intake_id"], self.request
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Document Intake Review", str(response.content))
        self.assertEqual(metadata_path.read_bytes(), before_metadata)
        self.assertEqual(self._events(item["intake_id"]), before_events)
        self.assertEqual(json.loads(metadata_path.read_bytes())["status_history"], before_status_history)
        self.assertEqual(json.loads(metadata_path.read_bytes())["status"], "under_review")
        self.assertIn("Confirm Rejection", str(preview.content))

    def test_cross_document_and_cross_session_confirmation_rejected(self):
        item_a = self._store("-a")
        item_b = self._store("-b")
        self._under_review(item_a)
        self._under_review(item_b)
        preview = self._preview(item_a, "approved", "Approve A.")
        token = confirmation_token(preview)
        before_a = self._events(item_a["intake_id"])
        before_b = self._events(item_b["intake_id"])
        with self.assertRaises(FakeHTTPException) as context:
            admin_session.admin_document_intake_status_confirm(
                item_b["intake_id"], self.request, confirmation_token=token
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(self._events(item_a["intake_id"]), before_a)
        self.assertEqual(self._events(item_b["intake_id"]), before_b)

        actor_b = admin_session.create_admin_session("actor-b")
        request_b = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: actor_b}, query_params={}
        )
        with self.assertRaises(FakeHTTPException) as context:
            admin_session.admin_document_intake_status_confirm(
                item_a["intake_id"], request_b, confirmation_token=token
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(self._events(item_a["intake_id"]), before_a)

    def test_signed_decision_evidence_tampering_fails_closed(self):
        item = self._store()
        self._under_review(item)
        preview = self._preview(item, "approved", "Approve with exact evidence.")
        token = confirmation_token(preview)
        variants = {
            "target": {"new_status": "rejected"},
            "rationale": {"rationale": "Changed rationale."},
            "intake": {"intake_id": "other-intake"},
            "previous": {"previous_status": "pending"},
            "actor": {"actor": "actor-b"},
            "role": {"actor_role": "reviewer"},
            "digest": {"sha256_hash": "0" * 64},
            "identifier": {"document_identifier": "DOC-2099-000001"},
        }
        for label, changes in variants.items():
            with self.subTest(label=label):
                self._assert_rejected_without_mutation(
                    item, self._unsigned_token_variant(token, **changes)
                )
        for label, invalid_token in {
            "truncated": token[:-8],
            "invalid_signature": token[:-1] + ("A" if token[-1] != "A" else "B"),
            "malformed": "not-a-token",
            "missing": "",
        }.items():
            with self.subTest(label=label):
                self._assert_rejected_without_mutation(item, invalid_token)

    def test_legacy_identifier_change_rejects_same_state_replay(self):
        item = self._store("-legacy")
        registry_path = self.root / ".document_identifiers.sqlite3"
        if registry_path.exists():
            registry_path.unlink()
        self._under_review(item)
        metadata_path = self._metadata_path(item)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["document_identifier"] = "DOC-2026-000001"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        preview = self._preview(item, "approved", "Approve legacy evidence.")
        token = confirmation_token(preview)

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["document_identifier"] = "DOC-2026-000002"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        update_intake_status(
            item["intake_id"],
            "approved",
            actor="admin-user",
            actor_role="admin",
            note="Approve legacy evidence.",
            root=self.root,
            lifecycle_db_path=self.db_path,
        )
        before_metadata = metadata_path.read_bytes()
        before_events = self._events(item["intake_id"])
        with self.assertRaises(FakeHTTPException) as context:
            admin_session.admin_document_intake_status_confirm(
                item["intake_id"], self.request, confirmation_token=token
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(metadata_path.read_bytes(), before_metadata)
        self.assertEqual(self._events(item["intake_id"]), before_events)


if __name__ == "__main__":
    unittest.main()
