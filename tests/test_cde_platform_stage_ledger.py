import unittest
from dataclasses import replace
from pathlib import Path

from scripts.validate_cde_platform_stage_ledger import (
    REPOSITORY_ROOT,
    StageEntry,
    parse_ledger,
    validate_entries,
    validate_repository,
)


LEDGER = REPOSITORY_ROOT / "docs/releases/CDE_PLATFORM_STAGE_LEDGER.md"


class CDEPlatformStageLedgerTests(unittest.TestCase):
    def setUp(self):
        self.entries = parse_ledger(LEDGER)

    def test_repository_stage_documentation_is_consistent(self):
        self.assertEqual(validate_repository(), [])

    def test_duplicate_stage_identifier_fails(self):
        duplicate = replace(
            next(entry for entry in self.entries if entry.stage == "44"),
            title="Duplicate",
        )
        errors = validate_entries([*self.entries, duplicate])
        self.assertTrue(
            any(error.startswith("stage_identifier_duplicate") for error in errors)
        )
        self.assertIn("stage_root_duplicate: 44", errors)

    def test_lower_stage_after_latest_release_fails(self):
        lower = StageEntry(
            stage="43.1",
            title="Out-of-order stage",
            capability="canonical-record-classification",
            parent="43",
            merged="2026-08-03",
            merge_commit="0" * 40,
            pull_request="#306",
            release_note="CDE_PLATFORM_STAGE_43_1_OUT_OF_ORDER.md",
            status="Implemented · merged · deployed",
        )
        errors = validate_entries([*self.entries, lower])
        self.assertTrue(
            any(error.startswith("stage_chronology_not_monotonic") for error in errors)
        )

    def test_suffix_with_unrelated_parent_capability_fails(self):
        suffix_index = next(
            index for index, entry in enumerate(self.entries) if entry.stage == "44.1"
        )
        unrelated = replace(
            self.entries[suffix_index], capability="unrelated-capability"
        )
        entries = list(self.entries)
        entries[suffix_index] = unrelated
        errors = validate_entries(entries)
        self.assertTrue(
            any(
                error.startswith("suffix_parent_capability_mismatch")
                for error in errors
            )
        )

    def test_canonical_sequence_uses_corrected_stage_numbers(self):
        self.assertEqual(
            [entry.stage for entry in self.entries],
            ["40", "41", "42", "43", "44", "44.1", "45", "46", "47", "47.1", "48", "49", "51", "52", "53", "53.1"],
        )

    def test_pending_stage_must_be_terminal(self):
        pending = self.entries[-1]
        errors = validate_entries([pending, *self.entries[:-1]])
        self.assertIn("pending_stage_not_terminal: 53.1", errors)


if __name__ == "__main__":
    unittest.main()
