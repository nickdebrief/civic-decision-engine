from __future__ import annotations

import hashlib
import unittest

from api import governed_report_diagnostics as diagnostics


def event(**changes):
    value = {
        "failure_event_id": "evt-synthetic-001",
        "operation": "renderer_invocation",
        "phase": "rendering",
        "checkpoint": None,
        "category": "os_error",
        "attribution": {"run_id": None, "attempt_id": "attempt-1", "process_id": None, "supervisor_id": None},
        "observed_at": "2026-11-21T17:00:00Z",
        "persisted_at": None,
        "terminal_outcome": "failed",
        "reconciliation_status": "recorded",
        "source_identity": "sha256:synthetic",
        "schema_manifest_id": "cf25-schema",
    }
    value.update(changes)
    return diagnostics.make_failure_event_v1(**value)


class FailureEventV1Tests(unittest.TestCase):
    def test_schema_identity_and_deterministic_serialization(self):
        value = event()
        self.assertEqual(value["schema_version"], diagnostics.CANONICAL_FAILURE_EVENT_SCHEMA_VERSION)
        self.assertEqual(diagnostics.serialize_failure_event_v1(value), diagnostics.serialize_failure_event_v1(dict(reversed(list(value.items())))))

    def test_missing_required_and_unknown_fields_are_rejected(self):
        value = event()
        with self.assertRaises(ValueError):
            diagnostics.validate_failure_event_v1({key: item for key, item in value.items() if key != "failure_event_id"})
        with self.assertRaises(ValueError):
            diagnostics.validate_failure_event_v1({**value, "raw_exception": "secret"})

    def test_unsupported_version_is_explicit(self):
        value = event()
        with self.assertRaisesRegex(ValueError, "unsupported_failure_event_schema_version"):
            diagnostics.validate_failure_event_v1({**value, "schema_version": "cde.n07.failure-event.v0"})
        self.assertEqual(diagnostics.consumer_version_status(diagnostics.CANONICAL_FAILURE_EVENT_SCHEMA_VERSION), "accepted")
        self.assertEqual(diagnostics.consumer_version_status(diagnostics.LEGACY_DIAGNOSTIC_CONTRACT), "legacy_adapter_required")

    def test_privacy_safe_producer_discards_exception_text(self):
        value = event(exception_message="token=ABC /private/path traceback private@example.test")
        rendered = diagnostics.serialize_failure_event_v1(value)
        for forbidden in ("token=ABC", "/private/path", "traceback", "private@example.test"):
            self.assertNotIn(forbidden, rendered)

    def test_adapter_is_non_destructive_and_rollback_returns_legacy_copy(self):
        legacy = {
            "id": "evt-legacy-1", "failure_operation": "renderer_invocation", "failure_phase": "rendering",
            "failure_checkpoint": "entered", "failure_exception_category": "os_error", "opaque": "preserve-me",
        }
        before = dict(legacy)
        source_identity = "sha256:" + hashlib.sha256(repr(sorted(legacy.items())).encode()).hexdigest()
        adapted = diagnostics.adapt_legacy_failure_event(legacy, source_identity=source_identity, schema_manifest_id="cf25-schema")
        self.assertEqual(legacy, before)
        self.assertEqual(adapted["provenance"]["source_identity"], source_identity)
        self.assertEqual(diagnostics.rollback_failure_event(legacy_record=legacy), legacy)
        self.assertIsNot(diagnostics.rollback_failure_event(legacy_record=legacy), legacy)

    def test_milestone_retirement_is_not_time_based(self):
        pending = {name: False for name in diagnostics.LEGACY_SUPPORT_MILESTONES}
        self.assertFalse(diagnostics.legacy_retirement_eligible(pending))
        self.assertTrue(diagnostics.legacy_retirement_eligible({name: True for name in diagnostics.LEGACY_SUPPORT_MILESTONES}))


if __name__ == "__main__":
    unittest.main()
