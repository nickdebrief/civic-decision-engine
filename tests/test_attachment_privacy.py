import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path):
    return (REPO_ROOT / path).read_text(encoding="utf-8")


class AttachmentPrivacyRegressionTests(unittest.TestCase):
    def test_no_public_attachment_serving_or_mutation_routes_exist(self):
        source = read_repo_file("api/routes/records.py")
        route_patterns = re.findall(r"@router\.(get|post|put|patch|delete)\(([^)]*)\)", source)
        allowed_public_metadata_routes = {
            "/records/{reference}/attachments",
            "/records/{reference}/attachments/manifest",
        }
        public_attachment_routes = [
            (method, route.split(",", 1)[0].strip().strip('"\''))
            for method, route in route_patterns
            if "attachment" in route
            and "/api/admin/records/{reference}/attachments" not in route
        ]
        unexpected_routes = [
            (method, route)
            for method, route in public_attachment_routes
            if method != "get" or route not in allowed_public_metadata_routes
        ]

        self.assertEqual(unexpected_routes, [])
        self.assertEqual(
            {route for _, route in public_attachment_routes},
            allowed_public_metadata_routes,
        )

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
