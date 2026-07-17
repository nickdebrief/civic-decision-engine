import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    load_pending_document,
    store_pending_document,
)


PDF_BYTES = b"%PDF-1.7\nfixture\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfixture"
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A fixture audio"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15fixture mp3 audio"
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt fixture wav audio"


def jpeg_bytes(marker: int, payload: bytes) -> bytes:
    return b"\xff\xd8\xff" + bytes([marker]) + b"\x00\x10" + payload + b"\xff\xd9"


JFIF_JPEG_BYTES = jpeg_bytes(0xE0, b"JFIF\x00baseline")
EXIF_JPEG_BYTES = jpeg_bytes(0xE1, b"Exif\x00\x00redacted")
ICC_JPEG_BYTES = jpeg_bytes(0xE2, b"ICC_PROFILE\x00redacted")
ADOBE_JPEG_BYTES = jpeg_bytes(0xEE, b"Adobe\x00redacted")
DQT_JPEG_BYTES = jpeg_bytes(0xDB, b"\x00" * 12)
PROGRESSIVE_JPEG_BYTES = jpeg_bytes(0xC2, b"progressive")
JP2_BYTES = b"\x00\x00\x00\x0cjP  \r\n\x87\n\x00\x00\x00\x14ftypjp2 \x00\x00\x00\x00jp2 "
TIFF_BYTES = b"II*\x00\x08\x00\x00\x00fixture"
HEIC_BYTES = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicfixture"
WEBP_BYTES = b"RIFF\x1a\x00\x00\x00WEBPVP8 fixture"


class JpegVariantIntakeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "intake"
        self.env = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "CDE_DOCUMENT_INTAKE_MAX_BYTES": "1048576",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, *, data: bytes, filename: str, content_type: str = "image/jpeg"):
        return store_pending_document(
            data=data,
            original_filename=filename,
            content_type=content_type,
            title="HR Walk-In Clinic Receipt — Standard Consultation",
            institution_source="HR Walk-In Clinic, Ennis, Co. Clare",
            document_date="2018-05-30",
            category="Receipt",
            description="Public version redacted before intake.",
            visibility="private",
            notes="Original redacted JPEG receipt preserved through intake.",
            reference_identifier="NM-RECEIPT-HR-20180530-001",
            actor="admin-user",
            root=self.root,
        )

    def test_jfif_exif_icc_adobe_and_quantization_jpeg_variants_are_accepted(self):
        cases = (
            ("baseline-jfif.jpg", JFIF_JPEG_BYTES),
            ("redacted-exif.jpg", EXIF_JPEG_BYTES),
            ("redacted-icc.jpg", ICC_JPEG_BYTES),
            ("redacted-adobe.jpg", ADOBE_JPEG_BYTES),
            ("redacted-dqt.jpg", DQT_JPEG_BYTES),
            ("redacted-progressive.jpg", PROGRESSIVE_JPEG_BYTES),
        )
        for filename, data in cases:
            with self.subTest(filename=filename):
                item = self._store(data=data, filename=filename)
                digest = hashlib.sha256(data).hexdigest()
                stored = load_pending_document(digest, root=self.root)
                self.assertEqual(item["document_type"], "jpeg")
                self.assertEqual(item["document_format"], "JPEG")
                self.assertEqual(item["content_type"], "image/jpeg")
                self.assertEqual(stored["sha256_hash"], digest)
                self.assertEqual(Path(stored["proposed_storage_location"]).read_bytes(), data)

    def test_jpg_jpeg_uppercase_and_non_authoritative_browser_mime_are_accepted(self):
        cases = (
            ("receipt.jpg", "image/jpeg"),
            ("receipt.jpeg", "image/jpg"),
            ("RECEIPT.JPG", "application/octet-stream"),
            ("RECEIPT.JPEG", "text/plain"),
        )
        for filename, content_type in cases:
            with self.subTest(filename=filename, content_type=content_type):
                item = self._store(
                    data=EXIF_JPEG_BYTES + filename.encode("utf-8"),
                    filename=filename,
                    content_type=content_type,
                )
                self.assertEqual(item["document_type"], "jpeg")
                self.assertEqual(item["original_filename"], filename)

    def test_spoofed_mismatched_and_malformed_jpegs_are_rejected(self):
        cases = (
            ("png-renamed.jpg", PNG_BYTES, "image/jpeg", "document_intake_file_type_mismatch"),
            ("jpeg-renamed.png", EXIF_JPEG_BYTES, "image/png", "document_intake_file_type_mismatch"),
            ("arbitrary.jpeg", b"not a jpeg", "image/jpeg", "document_intake_file_type_not_allowed"),
            ("truncated.jpeg", b"\xff\xd8\xff\xe1\x00\x10Exif", "image/jpeg", "document_intake_file_type_not_allowed"),
            ("redacted-jp2.jpeg", JP2_BYTES, "image/jpeg", "document_intake_file_type_not_allowed"),
            ("tiff-renamed.jpeg", TIFF_BYTES, "image/jpeg", "document_intake_file_type_not_allowed"),
            ("heic-renamed.jpeg", HEIC_BYTES, "image/jpeg", "document_intake_file_type_not_allowed"),
            ("webp-renamed.jpeg", WEBP_BYTES, "image/jpeg", "document_intake_file_type_not_allowed"),
        )
        for filename, data, content_type, error in cases:
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, error):
                self._store(data=data, filename=filename, content_type=content_type)

    def test_mismatch_failures_log_safe_diagnostic_fields(self):
        with self.assertLogs("api.document_intake", level="WARNING") as logs:
            with self.assertRaisesRegex(ValueError, "document_intake_file_type_mismatch"):
                self._store(data=PNG_BYTES, filename="png-renamed.jpg", content_type="image/jpeg")

        diagnostic = "\n".join(logs.output)
        self.assertIn("png-renamed.jpg", diagnostic)
        self.assertIn("extension=.jpg", diagnostic)
        self.assertIn("declared_content_type=image/jpeg", diagnostic)
        self.assertIn("expected_format=jpeg", diagnostic)
        self.assertIn("detected_format=png", diagnostic)
        self.assertIn("leading_signature_hex=", diagnostic)
        self.assertNotIn(str(self.root), diagnostic)

    def test_known_unsupported_jpeg_suffix_logs_detected_signature(self):
        with self.assertLogs("api.document_intake", level="WARNING") as logs:
            with self.assertRaisesRegex(ValueError, "document_intake_file_type_not_allowed"):
                self._store(data=JP2_BYTES, filename="redacted-jp2.jpeg", content_type="image/jpeg")

        diagnostic = "\n".join(logs.output)
        self.assertIn("redacted-jp2.jpeg", diagnostic)
        self.assertIn("extension=.jpeg", diagnostic)
        self.assertIn("detected_format=jpeg2000", diagnostic)
        self.assertIn("detected_mime_type=image/jp2", diagnostic)
        self.assertIn("leading_signature_hex=", diagnostic)
        self.assertNotIn(str(self.root), diagnostic)

    def test_existing_pdf_png_and_audio_validation_remains_unchanged(self):
        cases = (
            ("file.pdf", PDF_BYTES, "application/pdf", "pdf"),
            ("image.png", PNG_BYTES, "image/png", "png"),
            ("audio.m4a", M4A_BYTES, "audio/x-m4a", "m4a"),
            ("audio.mp3", MP3_BYTES, "audio/mpeg", "mp3"),
            ("audio.wav", WAV_BYTES, "audio/x-wav", "wav"),
        )
        for filename, data, content_type, expected_type in cases:
            with self.subTest(filename=filename):
                item = self._store(data=data, filename=filename, content_type=content_type)
                self.assertEqual(item["document_type"], expected_type)


if __name__ == "__main__":
    unittest.main()
