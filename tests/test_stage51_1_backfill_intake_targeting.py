from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import load_pending_document, store_pending_document
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_source_attachments,
)
from scripts.backfill_email_attachment_preservation import run as run_backfill
from tests.test_stage49_email_attachment_preservation import MULTI_ATTACHMENT_EML
from tests.test_stage51_outlook_msg_attachment_preservation import _build_stage51_msg


def _store_msg(root: Path, *, title: str = "Target MSG source") -> dict:
    return store_pending_document(
        data=_build_stage51_msg(),
        original_filename="target-source.msg",
        content_type="application/vnd.ms-outlook",
        title=title,
        institution_source="Civic Evidence Office",
        document_date="2026-08-06",
        category="Email Correspondence",
        description="Targeted MSG intake.",
        visibility="private",
        notes="Targeting test.",
        actor="targeting-admin",
        uploaded_at="2026-08-06T10:00:00Z",
        root=root,
    )


def _store_eml(root: Path, *, title: str = "Target EML source") -> dict:
    return store_pending_document(
        data=MULTI_ATTACHMENT_EML,
        original_filename="target-source.eml",
        content_type="message/rfc822",
        title=title,
        institution_source="Civic Evidence Office",
        document_date="2026-08-06",
        category="Email Correspondence",
        description="Targeted EML intake.",
        visibility="private",
        notes="Targeting test.",
        actor="targeting-admin",
        uploaded_at="2026-08-06T10:00:00Z",
        root=root,
    )


def _store_pre_stage51(root: Path, store_fn) -> dict:
    """Ingest a source with preservation disabled, modelling pre-Stage-51 state."""

    with patch(
        "api.email_attachment_preservation.preserve_outlook_msg_attachments",
        return_value=[],
    ), patch(
        "api.email_attachment_preservation.preserve_rfc5322_attachments",
        return_value=[],
    ):
        return store_fn(root)


class BackfillIntakeTargetingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {"CDE_DOCUMENT_INTAKE_ROOT": str(self.root)},
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_default_behaviour_without_intake_id_is_unchanged(self):
        # Two pre-Stage-51 sources; default scan should consider both (up to limit).
        msg = _store_pre_stage51(self.root, _store_msg)
        eml = _store_pre_stage51(self.root, _store_eml)

        result = run_backfill(root=self.root, limit=100, dry_run=True)
        # Both candidates are inspected in default mode.
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["created"], 5)  # 2 MSG + 3 EML attachments
        self.assertNotIn("skip_reason", result)
        # No writes occurred.
        self.assertFalse((self.root / REGISTRY_FILENAME).exists())

    def test_target_selects_exactly_one_msg_and_ignores_others(self):
        msg = _store_pre_stage51(self.root, _store_msg)
        other = _store_pre_stage51(self.root, lambda r: _store_eml(r, title="Other EML"))

        result = run_backfill(
            root=self.root, limit=100, dry_run=True, intake_id=msg["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["created"], 2)  # the MSG's two attachments
        self.assertNotIn("skip_reason", result)
        # No writes; no registry.
        self.assertFalse((self.root / REGISTRY_FILENAME).exists())

    def test_target_msg_real_run_creates_only_target_objects(self):
        msg = _store_pre_stage51(self.root, _store_msg)
        _store_pre_stage51(self.root, lambda r: _store_eml(r, title="Untouched EML"))
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}

        result = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=msg["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["linked"], 2)
        relationships = list_source_attachments(msg["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 2)
        # The untouched EML source has no relationship rows.
        self.assertEqual(
            len(list_source_attachments(
                next(
                    p.name for p in self.root.iterdir()
                    if p.is_dir() and p.name != msg["intake_id"]
                    and (p / "metadata.json").exists()
                ),
                root=self.root,
            )),
            0,
        )

    def test_target_eml_real_run_creates_only_target_objects(self):
        eml = _store_pre_stage51(self.root, _store_eml)

        result = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=eml["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["created"], 3)  # MULTI_ATTACHMENT_EML has 3 attachments
        relationships = list_source_attachments(eml["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 3)

    def test_target_second_run_reports_already_present_without_writes(self):
        msg = _store_pre_stage51(self.root, _store_msg)
        first = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=msg["intake_id"]
        )
        self.assertEqual(first["created"], 2)
        relationships_after_first = list_source_attachments(msg["intake_id"], root=self.root)
        registry_mtime_before = (self.root / REGISTRY_FILENAME).stat().st_mtime_ns

        second = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=msg["intake_id"]
        )
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["already_present"], 2)
        self.assertEqual(second["processed"], 1)
        relationships_after_second = list_source_attachments(msg["intake_id"], root=self.root)
        self.assertEqual(
            [r["relationship_id"] for r in relationships_after_second],
            [r["relationship_id"] for r in relationships_after_first],
        )

    def test_nonexistent_intake_id_is_skipped_without_writes(self):
        missing = "0" * 64
        result = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=missing
        )
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["skip_reason"], "intake_not_found")
        self.assertEqual(result["created"], 0)
        self.assertFalse((self.root / REGISTRY_FILENAME).exists())

    def test_unsupported_document_type_is_skipped(self):
        from api.document_intake import store_pending_document

        with patch(
            "api.email_attachment_preservation.preserve_outlook_msg_attachments",
            return_value=[],
        ):
            pdf = store_pending_document(
                data=b"%PDF-1.4 targeting test\n",
                original_filename="source.pdf",
                content_type="application/pdf",
                title="Non-email PDF",
                institution_source="Civic Evidence Office",
                document_date="2026-08-06",
                category="Report",
                description="Unsupported type.",
                visibility="private",
                notes="none",
                actor="targeting-admin",
                uploaded_at="2026-08-06T10:00:00Z",
                root=self.root,
            )
        result = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=pdf["intake_id"]
        )
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["skip_reason"], "unsupported_document_type")
        self.assertEqual(result["created"], 0)

    def test_zero_attachment_target_is_skipped(self):
        from tests.test_outlook_msg_support import build_cfb, _utf16

        # A valid .msg with zero attachment groups.
        root_streams = {
            "__properties_version1.0": b"\x00" * 32,
            "__substg1.0_001A001F": _utf16("IPM.Note"),
            "__substg1.0_0037001F": _utf16("No attachments"),
            "__substg1.0_0C1A001F": _utf16("Sender"),
            "__substg1.0_0C1F001F": _utf16("sender@example.test"),
            "__substg1.0_1000001F": _utf16("Body."),
        }
        data = build_cfb(root_streams, {})
        with patch(
            "api.email_attachment_preservation.preserve_outlook_msg_attachments",
            return_value=[],
        ):
            msg = store_pending_document(
                data=data,
                original_filename="no-attachments.msg",
                content_type="application/vnd.ms-outlook",
                title="Zero attachment MSG",
                institution_source="Civic Evidence Office",
                document_date="2026-08-06",
                category="Email Correspondence",
                description="No attachments.",
                visibility="private",
                notes="none",
                actor="targeting-admin",
                uploaded_at="2026-08-06T10:00:00Z",
                root=self.root,
            )
        result = run_backfill(
            root=self.root, limit=100, dry_run=False, intake_id=msg["intake_id"]
        )
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["skip_reason"], "no_attachments")
        self.assertEqual(result["created"], 0)

    def test_targeted_dry_run_is_strictly_write_free(self):
        msg = _store_pre_stage51(self.root, _store_msg)
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}
        metadata_before = (self.root / msg["intake_id"] / "metadata.json").read_text()

        result = run_backfill(
            root=self.root, limit=100, dry_run=True, intake_id=msg["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["created"], 2)
        self.assertFalse((self.root / REGISTRY_FILENAME).exists())
        self.assertEqual(dirs_before, {p.name for p in self.root.iterdir() if p.is_dir()})
        self.assertEqual(
            metadata_before, (self.root / msg["intake_id"] / "metadata.json").read_text()
        )

    def test_no_unrelated_candidate_processed_when_intake_id_supplied(self):
        msg = _store_pre_stage51(self.root, _store_msg)
        # A second eligible candidate that must NOT be touched.
        other = _store_pre_stage51(self.root, lambda r: _store_eml(r, title="Untouched"))

        result = run_backfill(
            root=self.root, limit=100, dry_run=True, intake_id=msg["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        # The other candidate has no relationship rows.
        self.assertEqual(len(list_source_attachments(other["intake_id"], root=self.root)), 0)


if __name__ == "__main__":
    unittest.main()
