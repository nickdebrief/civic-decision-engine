import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path):
    return (REPO_ROOT / path).read_text(encoding="utf-8")


class AttachmentPrivacyRegressionTests(unittest.TestCase):
    def test_no_public_attachment_serving_routes_exist(self):
        source = read_repo_file("api/routes/records.py")
        route_patterns = re.findall(r"@router\.(get|post|put|patch|delete)\(([^)]*)\)", source)
        public_attachment_routes = [
            route
            for method, route in route_patterns
            if "attachment" in route
            and "/api/admin/records/{reference}/attachments" not in route
        ]

        self.assertEqual(public_attachment_routes, [])

    def test_no_public_records_search_route_exists(self):
        source = read_repo_file("api/routes/records.py")

        self.assertNotIn('"/api/records/search"', source)
        self.assertNotIn("'/api/records/search'", source)

    def test_semantic_indexing_does_not_reference_attachments(self):
        semantic_sources = "\n".join(
            [
                read_repo_file("api/record_indexing.py"),
                read_repo_file("api/semantic_search.py"),
                read_repo_file("scripts/backfill_record_embeddings.py"),
                read_repo_file("scripts/query_record_embeddings.py"),
            ]
        )
        forbidden_terms = (
            "record_attachments",
            "storage_path",
            "stored_filename",
            "document_date",
            "uploaded_at",
            "attachment_id",
            "file_size_bytes",
        )

        for term in forbidden_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, semantic_sources)

    def test_attachment_content_extraction_is_not_implemented(self):
        source = "\n".join(
            [
                read_repo_file("api/attachments.py"),
                read_repo_file("api/routes/records.py"),
            ]
        ).lower()
        forbidden_terms = (
            "ocr",
            "pytesseract",
            "pdfplumber",
            "pypdf",
            "extract_text",
            "attachment_text",
        )

        for term in forbidden_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, source)


if __name__ == "__main__":
    unittest.main()
