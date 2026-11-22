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

    def test_malformed_container_and_boolean_fields_have_bounded_validation_failures(self):
        value = event()
        malformed_values = (
            {"operation": []},
            {"operation": {}},
            {"operation": True},
            {"phase": []},
            {"checkpoint": {}},
            {"category": []},
            {"terminal_outcome": {}},
            {"reconciliation_status": []},
            {"attribution": []},
        )
        for malformed in malformed_values:
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid"):
                    diagnostics.validate_failure_event_v1({**value, **malformed})

        with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid"):
            diagnostics.make_failure_event_v1(
                failure_event_id="evt-malformed-attribution",
                operation="renderer_invocation",
                phase="rendering",
                category="os_error",
                attribution=[],
            )

    def test_rfc3339_timestamps_are_strict_for_both_optional_fields(self):
        invalid_timestamps = (
            "2026-01-01Z",
            "2026-01-01 00:00:00Z",
            "2026-01-01",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00+25:00",
            "2026-02-30T00:00:00Z",
            "2026-01-01T24:00:00Z",
            "2026-01-01T00:00:00.Z",
            "2026/01/01T00:00:00Z",
            [],
            {},
            0,
            True,
        )
        for field in ("observed_at", "persisted_at"):
            for invalid in invalid_timestamps:
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid"):
                        event(**{field: invalid})

        valid_timestamps = (
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T12:34:56+05:30",
            "2026-01-01T12:34:56-07:00",
            "2026-01-01T00:00:00.123456Z",
            None,
        )
        for field in ("observed_at", "persisted_at"):
            for valid in valid_timestamps:
                with self.subTest(field=field, valid=valid):
                    value = event(**{field: valid})
                    self.assertEqual(value[field], valid)
                    self.assertEqual(
                        diagnostics.serialize_failure_event_v1(value),
                        diagnostics.serialize_failure_event_v1(dict(reversed(list(value.items())))),
                    )

    def test_legacy_adapter_cannot_project_invalid_timestamp(self):
        legacy = {
            "id": "evt-invalid-time",
            "failure_operation": "renderer_invocation",
            "failure_phase": "rendering",
            "failure_exception_category": "os_error",
            "observed_at": "2026-01-01Z",
        }
        with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid"):
            diagnostics.adapt_legacy_failure_event(
                legacy,
                source_identity="sha256:synthetic",
                schema_manifest_id="cf25-schema",
            )

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

    def test_provenance_is_a_bounded_opaque_identifier(self):
        value = event()
        for field in ("source_identity", "schema_manifest_id"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid"):
                    diagnostics.make_failure_event_v1(
                        failure_event_id="evt-private-provenance",
                        operation="renderer_invocation",
                        phase="rendering",
                        category="os_error",
                        **{field: "PRIVATE-SENTINEL /secret/path token=ABC"},
                    )
        self.assertEqual(
            diagnostics.make_failure_event_v1(
                failure_event_id="evt-pending-provenance",
                operation="renderer_invocation",
                phase="rendering",
                category="os_error",
            )["provenance"],
            {"schema_manifest_id": "pending", "source_identity": "pending"},
        )

    def test_event_and_attribution_identifiers_are_bounded_opaque_values(self):
        self.assertEqual(event(failure_event_id="evt-demo_01:attempt.2")["failure_event_id"], "evt-demo_01:attempt.2")
        self.assertEqual(event(attribution={
            "run_id": "run-01", "attempt_id": "attempt:2", "process_id": "process_3", "supervisor_id": None,
        })["attribution"]["process_id"], "process_3")

        unsafe = (
            "",
            "x" * 257,
            "/private/path",
            "private@example.test",
            "token=ABC",
            "traceback line 1",
            "line-one\nline-two",
            "{\"raw\":\"diagnostic\"}",
            [],
            {},
            7,
            True,
        )
        for field in ("failure_event_id", "run_id", "attempt_id", "process_id", "supervisor_id"):
            for unsafe_value in unsafe:
                with self.subTest(field=field, unsafe_value=unsafe_value):
                    with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid"):
                        if field == "failure_event_id":
                            event(failure_event_id=unsafe_value)
                        else:
                            attribution = {key: None for key in diagnostics.CANONICAL_ATTRIBUTION_FIELDS}
                            attribution[field] = unsafe_value
                            event(attribution=attribution)

    def test_identifier_rejection_is_bounded_across_producer_serializer_and_adapter(self):
        sentinel = "token=ABC /private/path private@example.test"
        with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid") as producer_error:
            event(failure_event_id=sentinel)
        self.assertNotIn(sentinel, str(producer_error.exception))

        direct = event()
        direct["failure_event_id"] = sentinel
        with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid") as serializer_error:
            diagnostics.serialize_failure_event_v1(direct)
        self.assertNotIn(sentinel, str(serializer_error.exception))

        legacy = {
            "id": sentinel,
            "failure_operation": "renderer_invocation",
            "failure_phase": "rendering",
            "failure_exception_category": "os_error",
            "run_id": sentinel,
        }
        before = dict(legacy)
        with self.assertRaisesRegex(ValueError, "canonical_failure_event_invalid") as adapter_error:
            diagnostics.adapt_legacy_failure_event(
                legacy, source_identity="sha256:synthetic", schema_manifest_id="cf25-schema",
            )
        self.assertEqual(legacy, before)
        self.assertNotIn(sentinel, str(adapter_error.exception))

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
        legacy["nested"] = {"values": ["preserve-me"]}
        rollback = diagnostics.rollback_failure_event(legacy_record=legacy)
        self.assertEqual(rollback, legacy)
        self.assertIsNot(rollback, legacy)
        rollback["nested"]["values"].append("detached")
        self.assertEqual(legacy["nested"], {"values": ["preserve-me"]})

    def test_milestone_retirement_is_not_time_based(self):
        pending = {name: False for name in diagnostics.LEGACY_SUPPORT_MILESTONES}
        self.assertFalse(diagnostics.legacy_retirement_eligible(pending))
        self.assertTrue(diagnostics.legacy_retirement_eligible({name: True for name in diagnostics.LEGACY_SUPPORT_MILESTONES}))


if __name__ == "__main__":
    unittest.main()
