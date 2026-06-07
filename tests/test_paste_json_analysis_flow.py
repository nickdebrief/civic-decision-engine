import os
import unittest
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func

    def patch(self, *args, **kwargs):
        return lambda func: func


class FakeHTTPException(Exception):
    def __init__(self, status_code=None, detail=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeResponse:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}


def install_fastapi_stubs():
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = FakeAPIRouter
    fastapi.File = lambda default=None, **kwargs: default
    fastapi.Form = lambda default=None, **kwargs: default
    fastapi.Header = lambda default=None, **kwargs: default
    fastapi.HTTPException = FakeHTTPException
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.UploadFile = object

    responses = types.ModuleType("fastapi.responses")
    responses.HTMLResponse = FakeResponse
    responses.JSONResponse = FakeResponse
    responses.Response = FakeResponse

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)


class _SimpleModel:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, _to_model(value))

    def model_dump(self):
        return {
            key: _from_model(value)
            for key, value in self.__dict__.items()
        }

    @classmethod
    def model_validate(cls, payload):
        return cls(**payload)


class _CasesRequest(_SimpleModel):
    def __init__(self, cases=None, **kwargs):
        super().__init__(
            cases=[_SimpleModel(**case) if isinstance(case, dict) else case for case in (cases or [])],
            **kwargs,
        )


def _to_model(value):
    if isinstance(value, dict):
        return _SimpleModel(**value)
    if isinstance(value, list):
        return [_to_model(item) for item in value]
    return value


def _from_model(value):
    if isinstance(value, _SimpleModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_from_model(item) for item in value]
    return value


def install_model_stubs():
    models = types.ModuleType("api.models")
    models.CasesRequest = _CasesRequest
    models.TimelineRunResponse = _SimpleModel
    models.PatternRunResponse = _SimpleModel
    models.CivicCaseRequest = _SimpleModel
    models.CivicRunResponse = _SimpleModel
    models.RecordPayload = type("RecordPayload", (), {})
    models.RecordResponse = type("RecordResponse", (), {})
    sys.modules["api.models"] = models


def install_jsonschema_stub():
    jsonschema = types.ModuleType("jsonschema")

    class Draft7Validator:
        def __init__(self, *_args, **_kwargs):
            pass

        def iter_errors(self, *_args, **_kwargs):
            return []

    jsonschema.Draft7Validator = Draft7Validator
    sys.modules.setdefault("jsonschema", jsonschema)


VALID_CASE_TEXT = (
    "A local authority matter demonstrates institutional delay through prolonged "
    "inaction. Subsequent correspondence resulted in procedural deflection, with "
    "responsibility redirected rather than addressed. Multiple follow-up contacts "
    "produced repeated contact without resolution. The burden of progressing the "
    "matter was transferred to the complainant, constituting transfer of burden. "
    "The matter then escalated without substantive response, resulting in "
    "escalation without response."
)

EXPECTED_CONDITIONS = {
    "INSTITUTIONAL_DELAY",
    "PROCEDURAL_DEFLECTION",
    "REPEATED_CONTACT_WITHOUT_RESOLUTION",
    "TRANSFER_OF_BURDEN",
    "ESCALATION_WITHOUT_RESPONSE",
}


def lineage_version(response):
    lineage = response.run_metadata.lineage
    if isinstance(lineage, dict):
        return lineage["version"]
    return lineage.version


def result_conditions(response):
    return set(response.results[0].conditions)


def dominant_condition_ids(response):
    ids = set()
    for item in response.results[0].dominant_conditions:
        if isinstance(item, dict):
            ids.add(item["condition"])
        else:
            ids.add(item.condition)
    return ids


class PasteJsonAnalysisFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_fastapi_stubs()
        install_model_stubs()
        install_jsonschema_stub()
        cls.import_temp_dir = tempfile.TemporaryDirectory()
        os.environ["RECORDS_DB_PATH"] = str(
            Path(cls.import_temp_dir.name) / "records.db"
        )
        from api.analysis_compat import normalize_analysis_request
        from api.routes import pattern, timeline
        from api.routes.records import compute_verification_hash

        cls.normalize_analysis_request = staticmethod(normalize_analysis_request)
        cls.pattern = pattern
        cls.timeline = timeline
        cls.compute_verification_hash = staticmethod(compute_verification_hash)
        cls.HTTPException = FakeHTTPException

    @classmethod
    def tearDownClass(cls):
        cls.import_temp_dir.cleanup()

    def test_case_text_payload_normalizes_to_existing_cases_schema(self):
        request = self.normalize_analysis_request(
            {"case_text": VALID_CASE_TEXT, "institution_type": "LA"}
        )

        self.assertEqual(len(request.cases), 1)
        case = request.cases[0]
        self.assertEqual(case.case_description, VALID_CASE_TEXT)
        self.assertEqual(case.decision_trigger, VALID_CASE_TEXT)
        self.assertEqual(case.institutions, ["LA"])
        self.assertEqual(case.strike_reference, "Strike-LA-PASTE-JSON")

    def test_source_narrative_payload_normalizes_to_existing_cases_schema(self):
        request = self.normalize_analysis_request(
            {"source_narrative": VALID_CASE_TEXT, "institution_type": "LA"}
        )

        self.assertEqual(request.cases[0].case_description, VALID_CASE_TEXT)
        self.assertEqual(request.cases[0].institutions, ["LA"])

    def test_valid_case_text_payload_returns_timeline_and_pattern_analysis(self):
        payload = {"case_text": VALID_CASE_TEXT, "institution_type": "LA"}

        with patch.object(self.timeline, "save_run_snapshot"), patch.object(
            self.pattern, "save_run_snapshot"
        ):
            timeline_result = self.timeline.timeline_live(payload)
            pattern_result = self.pattern.pattern_live(payload)

        self.assertEqual(len(timeline_result.results), 1)
        self.assertEqual(len(pattern_result.results), 1)
        self.assertIsNotNone(timeline_result.results[0].trajectory)
        self.assertIsNotNone(pattern_result.results[0].system_state)
        self.assertEqual(lineage_version(timeline_result), "v11")
        self.assertEqual(lineage_version(pattern_result), "v11")
        self.assertTrue(EXPECTED_CONDITIONS.issubset(result_conditions(timeline_result)))
        self.assertTrue(
            EXPECTED_CONDITIONS.issubset(dominant_condition_ids(pattern_result))
        )

    def test_valid_source_narrative_payload_returns_timeline_and_pattern_analysis(self):
        payload = {"source_narrative": VALID_CASE_TEXT, "institution_type": "LA"}

        with patch.object(self.timeline, "save_run_snapshot"), patch.object(
            self.pattern, "save_run_snapshot"
        ):
            timeline_result = self.timeline.timeline_live(payload)
            pattern_result = self.pattern.pattern_live(payload)

        self.assertEqual(len(timeline_result.results), 1)
        self.assertEqual(len(pattern_result.results), 1)
        self.assertEqual(lineage_version(timeline_result), "v11")
        self.assertEqual(lineage_version(pattern_result), "v11")
        self.assertTrue(EXPECTED_CONDITIONS.issubset(result_conditions(timeline_result)))
        self.assertTrue(
            EXPECTED_CONDITIONS.issubset(dominant_condition_ids(pattern_result))
        )

    def test_canonical_condition_identifiers_are_detected(self):
        payload = {
            "case_text": " ".join(sorted(EXPECTED_CONDITIONS)),
            "institution_type": "LA",
        }

        with patch.object(self.timeline, "save_run_snapshot"), patch.object(
            self.pattern, "save_run_snapshot"
        ):
            timeline_result = self.timeline.timeline_live(payload)
            pattern_result = self.pattern.pattern_live(payload)

        self.assertTrue(EXPECTED_CONDITIONS.issubset(result_conditions(timeline_result)))
        self.assertTrue(
            EXPECTED_CONDITIONS.issubset(dominant_condition_ids(pattern_result))
        )
        self.assertEqual(lineage_version(timeline_result), "v11")
        self.assertEqual(lineage_version(pattern_result), "v11")

    def test_escalation_without_response_detection_remains_available(self):
        payload = {
            "case_text": (
                "The matter escalated without substantive response, resulting in "
                "escalation without response."
            ),
            "institution_type": "LA",
        }

        with patch.object(self.timeline, "save_run_snapshot"):
            timeline_result = self.timeline.timeline_live(payload)

        self.assertIn(
            "ESCALATION_WITHOUT_RESPONSE",
            result_conditions(timeline_result),
        )
        self.assertEqual(lineage_version(timeline_result), "v11")

    def test_invalid_empty_payload_returns_validation_error(self):
        with self.assertRaises(Exception) as timeline_ctx:
            self.timeline.timeline_live({})
        with self.assertRaises(Exception) as pattern_ctx:
            self.pattern.pattern_live({})

        self.assertEqual(timeline_ctx.exception.status_code, 422)
        self.assertEqual(pattern_ctx.exception.status_code, 422)

    def test_canonical_verification_hash_behavior_unchanged(self):
        verification_hash = self.compute_verification_hash(
            reference="Strike-LA-PASTE-JSON",
            generated_at="2026-06-06T00:00:00Z",
            finding="Paste JSON compatibility must not alter canonical hashing.",
            trajectory="Deteriorating",
            conditions=["Transfer of Burden", "Escalation Without Response"],
            system_state="Escalating",
        )

        self.assertEqual(
            verification_hash,
            self.compute_verification_hash(
                reference="Strike-LA-PASTE-JSON",
                generated_at="2026-06-06T00:00:00Z",
                finding="Paste JSON compatibility must not alter canonical hashing.",
                trajectory="Deteriorating",
                conditions=["Escalation Without Response", "Transfer of Burden"],
                system_state="Escalating",
            ),
        )

    def test_attachment_governance_routes_are_not_changed(self):
        with open("api/routes/admin_session.py", encoding="utf-8") as handle:
            admin_source = handle.read()
        with open("api/routes/records.py", encoding="utf-8") as handle:
            records_source = handle.read()

        self.assertIn(
            '"/api/admin/session/records/{reference}/attachments/{attachment_id}/visibility"',
            admin_source,
        )
        self.assertIn(
            '"/records/{reference}/attachments/manifest"',
            records_source,
        )
        self.assertNotIn('"/api/records/search"', records_source)


if __name__ == "__main__":
    unittest.main()
