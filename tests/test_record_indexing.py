import hashlib
import json
import unittest

from api.record_indexing import (
    build_indexable_text,
    build_indexed_fields,
    build_snippet,
    indexed_fields_hash,
    indexed_fields_json,
    parse_conditions,
)


class RecordIndexingTests(unittest.TestCase):
    def sample_record(self):
        return {
            "reference": "Strike-LA-20260521-001",
            "generated_at": "2026-05-21T10:00:00Z",
            "finding": "Institutional delay has become structurally visible.",
            "trajectory": "Deteriorating",
            "conditions_json": json.dumps(
                ["Institutional Delay", "Transfer of Burden"]
            ),
            "system_state": "Transition to Escalation",
            "generated_by": "Civic Decision Engine",
            "source_narrative": "This private narrative must not be indexed.",
            "report_json": json.dumps({"raw": "This report payload must not be indexed."}),
            "raw_input": "This arbitrary raw input must not be indexed.",
        }

    def test_build_indexed_fields_uses_only_canonical_public_fields(self):
        fields = build_indexed_fields(self.sample_record())

        self.assertEqual(
            set(fields.keys()),
            {
                "reference",
                "generated_at",
                "finding",
                "trajectory",
                "conditions",
                "system_state",
                "generated_by",
            },
        )
        self.assertEqual(fields["reference"], "Strike-LA-20260521-001")
        self.assertEqual(
            fields["conditions"], ["Institutional Delay", "Transfer of Burden"]
        )

    def test_indexable_text_excludes_private_and_raw_fields(self):
        text = build_indexable_text(self.sample_record())

        self.assertIn("Strike-LA-20260521-001", text)
        self.assertIn("Institutional delay has become structurally visible.", text)
        self.assertIn("Institutional Delay", text)
        self.assertNotIn("private narrative", text)
        self.assertNotIn("report payload", text)
        self.assertNotIn("arbitrary raw input", text)

    def test_indexed_fields_json_excludes_private_and_raw_fields(self):
        payload = indexed_fields_json(self.sample_record())

        self.assertIn("Institutional Delay", payload)
        self.assertNotIn("source_narrative", payload)
        self.assertNotIn("report_json", payload)
        self.assertNotIn("raw_input", payload)
        self.assertNotIn("private narrative", payload)
        self.assertNotIn("report payload", payload)
        self.assertNotIn("arbitrary raw input", payload)

    def test_indexed_fields_hash_is_deterministic(self):
        record = self.sample_record()

        self.assertEqual(indexed_fields_hash(record), indexed_fields_hash(record))

    def test_indexed_fields_hash_derives_from_indexed_fields_json(self):
        record = self.sample_record()
        payload = indexed_fields_json(record)
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        self.assertEqual(indexed_fields_hash(record), expected)

    def test_indexed_fields_hash_ignores_non_indexed_fields(self):
        record = self.sample_record()
        changed = dict(record)
        changed["source_narrative"] = "A different private narrative."
        changed["report_json"] = json.dumps({"raw": "Different report payload."})
        changed["raw_input"] = "Different arbitrary raw input."

        self.assertEqual(indexed_fields_hash(record), indexed_fields_hash(changed))

    def test_parse_conditions_handles_invalid_json(self):
        self.assertEqual(parse_conditions({"conditions_json": "not json"}), [])
        self.assertEqual(parse_conditions({"conditions_json": {"bad": "shape"}}), [])

    def test_build_snippet_uses_indexable_text_only(self):
        record = self.sample_record()

        canonical_snippet = build_snippet(record, "Institutional delay")
        private_snippet = build_snippet(record, "private narrative")

        self.assertIn("Institutional delay", canonical_snippet)
        self.assertNotIn("private narrative", private_snippet)


if __name__ == "__main__":
    unittest.main()
