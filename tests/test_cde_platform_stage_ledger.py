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
            ["40", "41", "42", "43", "44", "44.1", "45", "46", "47", "47.1", "48", "49", "51", "52", "53", "53.1", "54", "55", "56", "57", "58", "59", "60", "61", "61.1", "61.2", "62", "62.1", "63", "64", "64.1", "65", "66", "66.1", "67", "67.1", "68", "69", "70", "71", "72"],
        )

    def test_stage_72_is_closed_after_verified_deployment(self):
        entry = next(item for item in self.entries if item.stage == "72")
        self.assertEqual(entry.title, "Governed Decision Pathway")
        self.assertEqual(entry.status, "Implemented · merged · deployed")
        self.assertEqual(entry.merge_commit, "365f660257fe80ad539eb2050e4c641cd1bfd923")
        self.assertEqual(entry.pull_request, "[#380](https://github.com/nickdebrief/civic-decision-engine/pull/380)")

    def test_stage_71_is_closed_after_verified_deployment(self):
        entry = next(item for item in self.entries if item.stage == "71")
        self.assertEqual(entry.status, "Implemented · merged · deployed")
        self.assertEqual(entry.merge_commit, "d4e5a39d0e7e67bc03ec4297bf508d087d3e4463")
        self.assertEqual(entry.pull_request, "[#377](https://github.com/nickdebrief/civic-decision-engine/pull/377)")

    def test_stage_68_is_closed_after_verified_deployment(self):
        entry = next(item for item in self.entries if item.stage == "68")
        self.assertEqual(entry.status, "Implemented · merged · deployed")
        self.assertEqual(entry.merge_commit, "d5cfdd4a1f64f6af1031b757b1c481e88cd1cdb2")
        self.assertEqual(entry.pull_request, "[#367](https://github.com/nickdebrief/civic-decision-engine/pull/367)")

    def test_pending_stage_must_be_terminal(self):
        pending = StageEntry(
            stage="53.2",
            title="Synthetic pending stage",
            capability="email-attachment-preservation",
            parent="53",
            merged="—",
            merge_commit="—",
            pull_request="—",
            release_note="CDE_PLATFORM_STAGE_53_2_SYNTHETIC_PENDING.md",
            status="Implemented · pending merge · pending deployment",
        )
        errors = validate_entries([*self.entries[:-1], pending, self.entries[-1]])
        self.assertIn("pending_stage_not_terminal: 53.2", errors)

    def test_stage_67_1_is_closed_after_verified_deployment(self):
        entry = next(item for item in self.entries if item.stage == "67.1")
        self.assertEqual(entry.status, "Implemented · merged · deployed")
        self.assertEqual(entry.merge_commit, "ba47640eb78244b5404e43dd998d80add71fb41b")
        self.assertEqual(entry.pull_request, "[#365](https://github.com/nickdebrief/civic-decision-engine/pull/365)")

    def test_stage_69_is_closed_after_verified_deployment(self):
        entry = next(item for item in self.entries if item.stage == "69")
        self.assertEqual(entry.status, "Implemented · merged · deployed")
        self.assertEqual(entry.merge_commit, "4f64e2bf046dd88134afe96eea7996826071bc17")
        self.assertEqual(entry.pull_request, "[#370](https://github.com/nickdebrief/civic-decision-engine/pull/370)")

    def test_stage_70_is_merged_and_deployed(self):
        entry = next(item for item in self.entries if item.stage == "70")
        self.assertEqual(entry.status, "Implemented · merged · deployed")
        self.assertEqual(entry.merge_commit, "92dad4ab9669c44431af759f6791141988c74844")
        self.assertEqual(entry.pull_request, "[#372](https://github.com/nickdebrief/civic-decision-engine/pull/372)")


if __name__ == "__main__":
    unittest.main()
