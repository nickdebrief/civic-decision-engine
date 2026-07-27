import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.document_intake import (
    intake_document_file,
    store_streaming_mbox_pending_document,
    update_intake_status,
    validate_document_file,
)
from tests.test_admin_session import FakeRequest, FakeUploadFile, install_fastapi_stubs
from tests.test_mbox_archive_support import mbox, message

install_fastapi_stubs()

from api.routes import admin_session, documents


class ChunkedReader:
    def __init__(self, data: bytes, *, max_chunk: int = 4096):
        self._handle = io.BytesIO(data)
        self.max_chunk = max_chunk
        self.read_sizes: list[int] = []

    def seek(self, offset: int):
        return self._handle.seek(offset)

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            size = self.max_chunk
        return self._handle.read(min(size, self.max_chunk))


class StreamingMBOXIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "stream-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "CDE_DOCUMENT_INTAKE_MAX_BYTES": "512",
                "MAX_STREAMING_MBOX_UPLOAD_BYTES": str(4 * 1024 * 1024),
                "STREAMING_MBOX_CHUNK_BYTES": "2048",
                "STREAMING_MBOX_MIN_FREE_BYTES": "0",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _large_mbox(self) -> bytes:
        messages = [
            message(
                subject=f"Streaming mailbox message {index}",
                message_id=f"<stream-{index}@example.test>",
                body=("Chunked body text for governed streaming ingestion. " * 30) + str(index),
            )
            for index in range(1, 4)
        ]
        return mbox(*messages)

    def _store(self, data: bytes | None = None, **overrides):
        values = {
            "file_handle": ChunkedReader(self._large_mbox() if data is None else data, max_chunk=3072),
            "original_filename": "large-apple-mail.mbox",
            "content_type": "application/octet-stream",
            "title": "Large Apple Mail Export",
            "institution_source": "Apple Mail",
            "document_date": "2026-07-27",
            "category": "Mailbox Archive",
            "description": "Large mailbox archive admitted through governed streaming intake.",
            "visibility": "private",
            "notes": "Streaming intake test note.",
            "reference_identifier": "STREAM-MBOX-001",
            "keywords": "streaming, mbox",
            "actor": "stream-admin",
            "uploaded_at": "2026-07-27T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_streaming_mbox_pending_document(**values)

    def test_valid_large_mbox_streamed_in_chunks_enters_pending_intake(self):
        data = self._large_mbox()
        reader = ChunkedReader(data, max_chunk=1024)
        item = self._store(data, file_handle=reader)

        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["document_type"], "mbox")
        self.assertEqual(item["intake_mode"], "governed_streaming_mbox")
        self.assertEqual(item["sha256_hash"], hashlib.sha256(data).hexdigest())
        self.assertEqual(item["file_size_bytes"], len(data))
        self.assertTrue(all(size == 2048 for size in reader.read_sizes[:-1]))
        self.assertIn("Governed Streaming Mailbox Intake", item["status_history"][0]["note"])
        metadata = item["email_metadata"]
        self.assertEqual(metadata["intake_mode"], "governed_streaming_mbox")
        self.assertEqual(metadata["streaming_chunk_bytes"], 2048)
        self.assertEqual(metadata["message_count"], 3)
        self.assertEqual([message["message_index"] for message in metadata["messages"]], [1, 2, 3])
        self.assertEqual([message["subject_decoded"] for message in metadata["messages"]], [
            "Streaming mailbox message 1",
            "Streaming mailbox message 2",
            "Streaming mailbox message 3",
        ])
        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), data)

    def test_existing_synchronous_mbox_limit_remains_unchanged(self):
        data = self._large_mbox()
        with self.assertRaisesRegex(ValueError, "document_intake_file_too_large"):
            validate_document_file(data, "large-apple-mail.mbox", "application/octet-stream")
        item = self._store(data)
        self.assertEqual(item["document_type"], "mbox")

    def test_streaming_limits_empty_and_exact_limit(self):
        with self.assertRaisesRegex(ValueError, "streaming_mbox_empty"):
            self._store(b"")

        data = self._large_mbox()
        with patch.dict(os.environ, {"MAX_STREAMING_MBOX_UPLOAD_BYTES": str(len(data))}):
            item = self._store(data)
        self.assertEqual(item["file_size_bytes"], len(data))

        with patch.dict(os.environ, {"MAX_STREAMING_MBOX_UPLOAD_BYTES": str(len(data) - 1)}):
            with self.assertRaisesRegex(ValueError, "streaming_mbox_file_too_large"):
                self._store(data)

    def test_validation_failure_cleans_temporary_file_and_creates_no_document(self):
        with self.assertRaisesRegex(ValueError, "document_intake_invalid_mbox"):
            self._store(b"Apple Mail table of contents")
        temp_root = self.root / "_streaming_mbox_tmp"
        leftovers = [path for path in temp_root.iterdir() if path.name.endswith(".upload")]
        self.assertEqual(leftovers, [])
        governed_dirs = [path for path in self.root.iterdir() if path.is_dir() and path.name != "_streaming_mbox_tmp"]
        self.assertEqual(governed_dirs, [])

    def test_streaming_rejects_invalid_extension_fake_content_and_duplicates(self):
        data = self._large_mbox()
        with self.assertRaisesRegex(ValueError, "streaming_mbox_invalid_extension"):
            self._store(data, original_filename="mbox")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_mismatch|document_intake_invalid_mbox"):
            self._store(b"%PDF-1.7\nrenamed\n%%EOF\n", original_filename="renamed.mbox")
        self._store(data)
        with self.assertRaisesRegex(ValueError, "document_intake_duplicate"):
            self._store(data)

    def test_disk_space_and_concurrency_are_bounded(self):
        with patch("api.document_intake.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(ValueError, "streaming_mbox_insufficient_storage"):
                self._store()

        temp_root = self.root / "_streaming_mbox_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        (temp_root / ".streaming-mbox.lock").write_text("locked", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "streaming_mbox_concurrent_job_limit"):
            self._store()

    def test_admin_ui_and_route_create_streaming_pending_document(self):
        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("stream-admin")
            }
        )
        page = admin_session.admin_document_intake_page(request).content
        self.assertIn("Governed Streaming Mailbox Intake", page)
        self.assertIn("/api/admin/session/streaming-mbox-intake", page)
        self.assertIn(admin_session.STREAMING_MBOX_FILE_ACCEPT, page)
        self.assertIn("Maximum governed streaming MBOX upload size: 4 MB", page)
        self.assertIn("ordinary synchronous Document Intake", page)

        data = self._large_mbox()
        response = admin_session.admin_streaming_mbox_intake_upload(
            request,
            title="Route Streaming MBOX",
            institution_source="Apple Mail",
            document_date="2026-07-27",
            category="Mailbox Archive",
            description="Created through route.",
            visibility="private",
            notes="Route note.",
            reference_identifier="ROUTE-MBOX",
            keywords="route, streaming",
            file=FakeUploadFile(
                data,
                filename="route-streaming.mbox",
                content_type="application/octet-stream",
            ),
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("Route Streaming MBOX", response.content)
        self.assertIn("Governed Streaming Mailbox Intake", response.content)

    def test_streaming_route_requires_admin_and_public_access_still_requires_publication(self):
        with self.assertRaises(Exception) as unauthenticated:
            admin_session.admin_streaming_mbox_intake_upload(
                FakeRequest(),
                title="Blocked",
                institution_source="Apple Mail",
                document_date="2026-07-27",
                category="Mailbox Archive",
                description="Blocked.",
                visibility="private",
                notes="Blocked.",
                file=FakeUploadFile(self._large_mbox(), filename="blocked.mbox"),
            )
        self.assertIn("admin_session_unauthorized", str(unauthenticated.exception))

        item = self._store()
        with self.assertRaises(Exception):
            documents.public_document_page(item["intake_id"])

        for status in ("under_review", "approved", "published"):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="stream-admin",
                note=f"{status} note",
                root=self.root,
            )
        public_page = documents.public_document_page(item["intake_id"]).content
        self.assertIn("Governed Streaming Mailbox Intake", public_page)
        self.assertIn("Streaming upload completed", public_page)
        self.assertIn("Mailbox Overview", public_page)


if __name__ == "__main__":
    unittest.main()
