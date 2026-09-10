"""Stage 78B2A internal procedural-pathway rendering materialization tests."""

from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import os
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from api import record_governed_reports as reports
from api import report_rendering
from tests.test_stage78b_pathway_report_specification import (
    FIXED_TIME,
    RECORD,
    _all_table_counts,
    _create_pathway_report,
    _fresh_connection,
    _populate_projection,
)

ENGINE = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline"


def _approve_for_generation(conn: sqlite3.Connection, report_id: int) -> None:
    with patch.dict(os.environ, {"CDE_GOVERNED_REPORT_REVIEW_MODE": "sole_administrator"}):
        current = report_id
        for status, key in (
            ("assembly_reviewed", "assembly"),
            ("privacy_reviewed", "privacy"),
            ("redaction_reviewed", "redaction"),
            ("approved_for_generation", "approval"),
        ):
            item = reports.confirm_creator_gate(
                conn,
                report_id=current,
                resulting_status=status,
                rationale=f"{status} confirmed",
                actor="creator",
                actor_role="administrator",
                acknowledged=True,
                idempotency_key=f"{key}-gate",
            )
            current = item["id"]


def _fake_artifacts(target: Path) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for fmt in ("html", "docx"):
        path = target / f"report.{fmt}"
        path.write_text(f"{fmt} pathway render", encoding="utf-8")
        artifacts.append({
            "format": fmt,
            "path": str(path),
            "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "renderer_version": reports.PUBLICATION_ENGINE_VERSION,
        })
    return {"diagnostics": [], "artifacts": artifacts}


def _install_adapter_fakes(validation_module: types.ModuleType | None = None) -> None:
    renderers = types.ModuleType("renderers")
    sys.modules.setdefault("renderers", renderers)
    for name, cls_name in (
        ("renderers.docx_renderer", "DocxRenderer"),
        ("renderers.html_renderer", "HtmlRenderer"),
    ):
        module = types.ModuleType(name)
        setattr(module, cls_name, type(cls_name, (), {"__init__": lambda self, *a, **k: None, "render": lambda self, *a, **k: None}))
        if cls_name == "HtmlRenderer":
            module.HtmlOutputConfig = type("HtmlOutputConfig", (), {"__init__": lambda self, *a, **k: None})
        sys.modules[name] = module
    pdf = types.ModuleType("renderers.pdf_renderer")
    pdf.PdfRenderer = type("PdfRenderer", (), {})
    pdf.discover_tool = lambda _tool: None
    sys.modules["renderers.pdf_renderer"] = pdf
    base = types.ModuleType("themes.base")
    base.EffectiveTheme = type("EffectiveTheme", (), {"__init__": lambda self, *a, **k: None})
    base.PageTheme = type("PageTheme", (), {"__init__": lambda self, *a, **k: None})
    base.ResolvedAsset = type("ResolvedAsset", (), {"__init__": lambda self, *a, **k: None})
    base.Theme = type("Theme", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["themes.base"] = base
    handbook = types.ModuleType("themes.handbook")
    handbook.HANDBOOK_THEME = types.SimpleNamespace(page=None, title_page=None, volume_page=None, chapter_opening=None)
    sys.modules["themes.handbook"] = handbook
    registry = types.ModuleType("themes.registry")
    registry.CHAPTER_OPENING_TEMPLATES = {}
    registry.PUBLICATION_PROFILES = {"digital": object()}
    registry.TITLE_PAGE_TEMPLATES = {}
    registry.VOLUME_PAGE_TEMPLATES = {}
    registry.get_page_profile = lambda *_a, **_k: None
    registry.get_publication_profile = lambda *_a, **_k: None
    registry.get_theme = lambda *_a, **_k: None
    sys.modules["themes.registry"] = registry
    validation = validation_module or types.ModuleType("output_validation")
    validation.audit_html = getattr(validation, "audit_html", lambda _path: types.SimpleNamespace(text=""))
    validation.docx_text = getattr(validation, "docx_text", lambda _path: ("", []))
    validation.source_text_blocks = getattr(
        validation,
        "source_text_blocks",
        lambda book: [getattr(block, "text", "") for chapter in book.blocks for section in chapter.blocks for block in section.blocks if getattr(block, "text", "")],
    )
    validation.validate_cross_format_equivalence = getattr(validation, "validate_cross_format_equivalence", lambda *a, **k: (types.SimpleNamespace(ok=True), []))
    validation.validate_docx_output = getattr(validation, "validate_docx_output", lambda *a, **k: (types.SimpleNamespace(ok=True), []))
    validation.validate_html_output = getattr(validation, "validate_html_output", lambda *a, **k: (types.SimpleNamespace(ok=True), []))
    sys.modules["output_validation"] = validation


def _load_adapter(validation_module: types.ModuleType | None = None):
    _install_adapter_fakes(validation_module)
    path = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline" / "report_adapter.py"
    return _load_adapter_from(path)


def _load_adapter_from(path: Path):
    spec = importlib.util.spec_from_file_location("stage78b2a_report_adapter", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Stage78BPathwayRenderMaterializationTests(unittest.TestCase):
    def test_promoted_artifact_must_match_validated_descriptor(self) -> None:
        specification = {"publication_engine_version": report_rendering.ENGINE_VERSION}
        digest = report_rendering.canonical_json(specification)
        digest = __import__("hashlib").sha256(digest.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            source_bytes = b"validated-byte-content"
            descriptor = {"format": "docx", "sha256": __import__("hashlib").sha256(source_bytes).hexdigest(), "size_bytes": len(source_bytes), "renderer_version": "test"}
            class Process:
                returncode = 0
                def communicate(self, timeout=None): return "", ""
            def launch(command, **_kwargs):
                Path(command[3]).mkdir(exist_ok=True)
                (Path(command[3]) / "report.docx").write_bytes(source_bytes)
                Path(command[4]).write_text("{}")
                return Process()
            result = {"ok": True, "phase": "result_serialization", "code": "completed", "cleanup": "passed", "specification_digest": digest, "artifacts": [descriptor], "diagnostics": []}
            with patch("api.report_rendering.subprocess.Popen", side_effect=launch), patch("api.report_rendering._read_adapter_result", return_value=result):
                good = report_rendering.render_frozen_report(specification, digest, output)
            self.assertEqual(good["artifacts"][0]["sha256"], descriptor["sha256"])
            self.assertEqual(good["artifacts"][0]["size_bytes"], descriptor["size_bytes"])
        for replacement in (b"x" * len(source_bytes), b"different-size"):
            with self.subTest(replacement=replacement):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "output"
                    class Process:
                        returncode = 0
                        def communicate(self, timeout=None): return "", ""
                    def launch(command, **_kwargs):
                        Path(command[3]).mkdir(exist_ok=True)
                        (Path(command[3]) / "report.docx").write_bytes(source_bytes)
                        Path(command[4]).write_text("{}")
                        return Process()
                    result = {"ok": True, "phase": "result_serialization", "code": "completed", "cleanup": "passed", "specification_digest": digest, "artifacts": [descriptor], "diagnostics": []}
                    real_copy = report_rendering.shutil.copy2
                    def replace_after_validation(_source, destination, *args, **kwargs):
                        Path(destination).write_bytes(replacement)
                        return str(destination)
                    with patch("api.report_rendering.subprocess.Popen", side_effect=launch), patch("api.report_rendering._read_adapter_result", return_value=result), patch("api.report_rendering.shutil.copy2", side_effect=replace_after_validation):
                        with self.assertRaises(report_rendering.AdapterFailure):
                            report_rendering.render_frozen_report(specification, digest, output)
                    self.assertFalse((output / "report.docx").exists())
    def setUp(self) -> None:
        self.conn = _fresh_connection()
        _populate_projection(self.conn)
        self.report = _create_pathway_report(self.conn)
        self.specification = copy.deepcopy(self.report["versions"][0]["specification"])

    def tearDown(self) -> None:
        self.conn.close()

    def test_full_pathway_materialization_is_deterministic_and_bounded(self) -> None:
        before = _all_table_counts(self.conn)
        first = reports.materialize_pathway_render_model(self.conn, self.specification)
        second = reports.materialize_pathway_render_model(self.conn, self.specification)
        self.assertEqual(first, second)
        self.assertEqual(before, _all_table_counts(self.conn))
        self.assertEqual(first["render_model_contract"], reports.PATHWAY_RENDER_MODEL_CONTRACT)
        self.assertEqual(first["report_type"], reports.PATHWAY_REPORT_TYPE)
        self.assertEqual(first["projection_digest"], self.specification["pathway_projection"]["projection_digest"])
        self.assertGreater(first["row_count"], 10)
        encoded = reports.canonical_json(first)
        self.assertNotIn("object_id", encoded)
        self.assertNotIn("parent_id", encoded)
        self.assertNotIn("display_label", encoded)
        self.assertNotIn("request_payload_json", encoded)
        self.assertNotIn('"actor"', encoded)
        self.assertNotIn('"actor_role"', encoded)
        self.assertNotIn('"reviewed_by"', encoded)

    def test_section_order_and_source_mapping_are_stable(self) -> None:
        model = reports.materialize_pathway_render_model(self.conn, self.specification)
        titles = [section["title"] for section in model["sections"]]
        self.assertEqual(titles[0], "Report identity and scope")
        self.assertLess(titles.index("Authority and mandate"), titles.index("Determinations and reasons"))
        self.assertLess(titles.index("Determinations and reasons"), titles.index("Remedies"))
        self.assertLess(titles.index("Scoped gaps"), titles.index("Provenance and limitations"))
        section_rows = {section["title"]: section["rows"] for section in model["sections"]}
        self.assertTrue(any(row["object_kind"] == "decision_authority" for row in section_rows["Authority and mandate"]))
        self.assertTrue(any(row["object_kind"] == "procedural_notice" for row in section_rows["Notice and participation"]))
        self.assertTrue(any(row["object_kind"] == "governed_remedy" for row in section_rows["Remedies"]))

    def test_render_object_kind_allowlist_matches_stage78a_projection_contract(self) -> None:
        projection = reports._projection_module()
        self.assertEqual(set(reports._PATHWAY_RENDER_OBJECT_KINDS), set(projection.KIND_RANK))
        for object_kind in sorted(projection.KIND_RANK):
            with self.subTest(object_kind=object_kind):
                self.assertEqual(reports._pathway_render_object_kind(object_kind), object_kind)
                self.assertIn(reports._PATHWAY_SECTION_MAP[object_kind], reports._PATHWAY_SECTION_ORDER)

    def test_materialization_rejects_unknown_or_altered_object_kind_before_fallback(self) -> None:
        projection = reports._projection_module().project_pathway(self.conn, RECORD)
        row = copy.deepcopy(projection["rows"][0])
        governed_identity = reports._logical_identity_for_projection_row(self.conn, row)
        compact = next(
            item for item in self.specification["pathway_projection"]["rows"]
            if item["governed_logical_identity"] == governed_identity
        )
        for object_kind in ("", " ", " governed_observation", "governed_observation ", "Governed_observation", "unknown_private_row_kind"):
            with self.subTest(object_kind=object_kind):
                candidate = copy.deepcopy(row)
                candidate["object_kind"] = object_kind
                with self.assertRaisesRegex(ValueError, "^governed_report_pathway_render_model_invalid$") as raised:
                    reports._pathway_render_row(self.conn, candidate, compact)
                self.assertNotIn("unknown_private_row_kind", str(raised.exception))
        self.assertIsNone(reports._PATHWAY_SECTION_MAP.get("unknown_private_row_kind"))

    def test_status_epistemic_chronology_and_history_are_preserved(self) -> None:
        model = reports.materialize_pathway_render_model(self.conn, self.specification)
        rows = [row for section in model["sections"] for row in section["rows"]]
        determination = next(row for row in rows if row["object_kind"] == "governed_determination")
        self.assertEqual(determination["epistemic_label"], "attributed_determination")
        self.assertTrue(determination["does_not_establish"]["does_not_establish_cde_endorsement"])
        self.assertIn("reasons_status", determination["limitations"])
        notice = next(row for row in rows if row["object_kind"] == "procedural_notice")
        self.assertIn("basis", notice["chronology"])
        self.assertIn("precision", notice["chronology"])
        self.assertIn("ordering_relation", notice["chronology"])
        implementation = next(row for row in rows if row["object_kind"] == "implementation_event")
        self.assertTrue(implementation["does_not_establish"]["does_not_establish_completion"])

    def test_unavailable_families_and_scoped_gap_wording_are_materialized(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, title TEXT, description TEXT, status TEXT, version TEXT, is_latest INTEGER)")
            conn.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, 1)", (RECORD, "Record", "Description", "active", "1"))
            conn.commit()
            report = _create_pathway_report(conn, key="absent-families")
            model = reports.materialize_pathway_render_model(conn, report["versions"][0]["specification"])
            self.assertIn("stage62", model["unavailable_families"])
            self.assertTrue(any(gap["statement"].startswith("No governed notice record") for gap in model["gaps"]))
        finally:
            conn.close()

    def test_partial_family_fails_closed_before_materialization(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, title TEXT, description TEXT, status TEXT, version TEXT, is_latest INTEGER)")
            conn.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, 1)", (RECORD, "Record", "Description", "active", "1"))
            conn.execute("CREATE TABLE record_governed_remedies (id INTEGER PRIMARY KEY)")
            conn.commit()
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_schema_incomplete"):
                _create_pathway_report(conn, key="partial-family")
        finally:
            conn.close()

    def test_generation_passes_bounded_render_model_to_renderer(self) -> None:
        _approve_for_generation(self.conn, self.report["id"])
        seen = {}

        def fake_render(spec, digest, target, governance_qualification=None, pathway_render_model=None):
            seen["model"] = pathway_render_model
            return _fake_artifacts(Path(target))

        with tempfile.TemporaryDirectory(prefix="stage78b2a-render-") as directory:
            with patch("api.report_rendering.render_frozen_report", side_effect=fake_render):
                reports.generate_report(
                    self.conn,
                    report_id=self.report["id"],
                    actor="worker",
                    actor_role="system_worker",
                    idempotency_key="pathway-render",
                    output_dir=Path(directory) / "out",
                )
        self.assertIsNotNone(seen["model"])
        self.assertEqual(seen["model"]["render_model_contract"], reports.PATHWAY_RENDER_MODEL_CONTRACT)
        self.assertEqual(seen["model"]["projection_digest"], self.specification["pathway_projection"]["projection_digest"])

    def test_drift_before_rendering_rejects_without_renderer_invocation(self) -> None:
        _approve_for_generation(self.conn, self.report["id"])
        self.conn.execute("UPDATE record_governed_procedural_notices SET status='superseded' WHERE idempotency_key='notice-1'")
        with patch("api.report_rendering.render_frozen_report") as renderer:
            with self.assertRaisesRegex(ValueError, "governed_report_pathway_projection_digest_drift"):
                reports.generate_report(self.conn, report_id=self.report["id"], actor="worker", actor_role="system_worker", idempotency_key="pre-render-drift")
        renderer.assert_not_called()

    def test_drift_after_rendering_rejects_and_cleans_output(self) -> None:
        _approve_for_generation(self.conn, self.report["id"])

        def fake_render(_spec, _digest, target, governance_qualification=None, pathway_render_model=None):
            self.conn.execute("UPDATE record_governed_procedural_notices SET status='superseded' WHERE idempotency_key='notice-1'")
            return _fake_artifacts(Path(target))

        with tempfile.TemporaryDirectory(prefix="stage78b2a-post-render-") as directory:
            target = Path(directory) / "out"
            with patch("api.report_rendering.render_frozen_report", side_effect=fake_render):
                with self.assertRaises(reports.GovernedReportGenerationFailure) as raised:
                    reports.generate_report(self.conn, report_id=self.report["id"], actor="worker", actor_role="system_worker", idempotency_key="post-render-drift", output_dir=target)
            self.assertEqual(raised.exception.code, "governed_report_generation_source_changed")
            self.assertFalse(target.exists())

    def test_adapter_accepts_pathway_model_and_rejects_malformed_model(self) -> None:
        adapter = _load_adapter()
        model = reports.materialize_pathway_render_model(self.conn, self.specification)
        book = adapter.make_book(self.specification, pathway_render_model=model)
        rendered = "\n".join(block.text for chapter in book.blocks for section in chapter.blocks for block in section.blocks if hasattr(block, "text"))
        self.assertIn("Canonical Record:", rendered)
        self.assertIn("Projection:", rendered)
        self.assertIn("does_not_establish", rendered)
        malformed = dict(model)
        malformed.pop("sections")
        with self.assertRaises(adapter.AdapterFailure) as raised:
            adapter.make_book(self.specification, pathway_render_model=malformed)
        self.assertEqual(raised.exception.code, "adapter_model_invalid")

    def test_adapter_rejects_unknown_or_altered_object_kind_after_materialization(self) -> None:
        adapter = _load_adapter()
        model = reports.materialize_pathway_render_model(self.conn, self.specification)
        values = ("", " ", " governed_observation", "governed_observation ", "Governed_observation", "unknown_private_row_kind")
        for object_kind in values:
            with self.subTest(object_kind=object_kind):
                mutated = copy.deepcopy(model)
                for section in mutated["sections"]:
                    for row in section["rows"]:
                        if "object_kind" in row:
                            row["object_kind"] = object_kind
                            break
                    else:
                        continue
                    break
                with self.assertRaises(adapter.AdapterFailure) as raised:
                    adapter.make_book(self.specification, pathway_render_model=mutated)
                self.assertEqual(raised.exception.code, "adapter_model_invalid")
                self.assertNotIn("unknown_private_row_kind", str(raised.exception))

    def test_adapter_rejects_database_free_authority_refresh_attempts(self) -> None:
        adapter = _load_adapter()
        model = reports.materialize_pathway_render_model(self.conn, self.specification)
        with patch("sqlite3.connect", side_effect=AssertionError("database access forbidden")):
            book = adapter.make_book(self.specification, pathway_render_model=model)
        self.assertEqual(book.version, reports.PATHWAY_SPECIFICATION_SCHEMA_VERSION)

    def test_pathway_model_for_canonical_report_is_rejected_by_adapter_boundary(self) -> None:
        adapter = _load_adapter()
        spec = {
            "title": "Canonical",
            "purpose": "Purpose",
            "specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION,
            "report_type": "canonical_record_report",
            "sections": [{"order": 0, "title": "Section", "blocks": []}],
            "selected_documents": [],
            "selected_associations": [],
            "exclusions": [],
            "qualifications": [],
        }
        model = reports.materialize_pathway_render_model(self.conn, self.specification)
        with self.assertRaises(adapter.AdapterFailure):
            adapter.make_book(spec, pathway_render_model=model)

    def test_pathway_validator_source_anchor_ignores_permissive_normal_stub(self) -> None:
        stub = types.ModuleType("output_validation")
        stub.__file__ = str(Path(tempfile.gettempdir()) / "wrong_output_validation.py")
        for name in (
            "canonical_pathway_units",
            "pathway_docx_frame_contract",
            "pathway_trusted_pdf_conversion_binding",
            "validate_pathway_output_equivalence",
        ):
            setattr(stub, name, lambda *args, **kwargs: types.SimpleNamespace(ok=True))

        adapter = _load_adapter(stub)

        self.assertIsNot(adapter._output_validation, stub)
        self.assertEqual(Path(adapter._output_validation.__file__).resolve(), (ENGINE / "output_validation.py").resolve())
        self.assertIs(adapter.validate_pathway_output_equivalence, adapter._output_validation.validate_pathway_output_equivalence)

    def test_pathway_validator_source_anchor_ignores_forged_private_cache(self) -> None:
        private_name = "_stage78_pathway_output_validation"
        calls = []
        forged = types.ModuleType(private_name)
        forged.__file__ = str((ENGINE / "output_validation.py").resolve())

        def permissive(*_args, **_kwargs):
            calls.append("called")
            return types.SimpleNamespace(ok=True)

        permissive.__module__ = private_name
        for name in (
            "canonical_pathway_units",
            "pathway_docx_frame_contract",
            "pathway_trusted_pdf_conversion_binding",
            "validate_pathway_output_equivalence",
        ):
            setattr(forged, name, permissive)
        original = sys.modules.get(private_name)
        sys.modules[private_name] = forged
        try:
            adapter = _load_adapter()
        finally:
            if original is None:
                sys.modules.pop(private_name, None)
            else:
                sys.modules[private_name] = original

        self.assertEqual(calls, [])
        self.assertIsNot(adapter._output_validation, forged)
        self.assertIs(adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY, adapter._output_validation)
        self.assertEqual(Path(adapter._output_validation.__file__).resolve(), (ENGINE / "output_validation.py").resolve())
        result, _audit = adapter.validate_pathway_output_equivalence({}, specification={})
        self.assertFalse(result.ok)

    def test_pathway_validator_source_anchor_ignores_forged_private_spec_origin(self) -> None:
        private_name = "_stage78_pathway_output_validation"
        calls = []
        forged = types.ModuleType(private_name)
        forged.__spec__ = importlib.machinery.ModuleSpec(private_name, loader=None, origin=str((ENGINE / "output_validation.py").resolve()))

        def permissive(*_args, **_kwargs):
            calls.append("called")
            return types.SimpleNamespace(ok=True)

        permissive.__module__ = private_name
        for name in (
            "canonical_pathway_units",
            "pathway_docx_frame_contract",
            "pathway_trusted_pdf_conversion_binding",
            "validate_pathway_output_equivalence",
        ):
            setattr(forged, name, permissive)
        original = sys.modules.get(private_name)
        sys.modules[private_name] = forged
        try:
            adapter = _load_adapter()
        finally:
            if original is None:
                sys.modules.pop(private_name, None)
            else:
                sys.modules[private_name] = original

        self.assertEqual(calls, [])
        self.assertIsNot(adapter._output_validation, forged)
        self.assertIs(adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY, adapter._output_validation)
        self.assertEqual(Path(adapter._output_validation.__file__).resolve(), (ENGINE / "output_validation.py").resolve())

    def test_pathway_validator_later_private_cache_substitution_is_ignored(self) -> None:
        adapter = _load_adapter()
        private_name = adapter._PATHWAY_OUTPUT_VALIDATION_MODULE_NAME
        authority = adapter._pathway_output_validation_module()
        replacement = types.ModuleType(private_name)
        replacement.__file__ = str((ENGINE / "output_validation.py").resolve())
        original = sys.modules.get(private_name)
        try:
            sys.modules[private_name] = replacement
            self.assertIs(adapter._pathway_output_validation_module(), authority)
        finally:
            if original is None:
                sys.modules.pop(private_name, None)
            else:
                sys.modules[private_name] = original

    def test_pathway_validator_fails_closed_for_invalid_sibling_source(self) -> None:
        adapter = _load_adapter()

        def load_from(source: str | None) -> None:
            with tempfile.TemporaryDirectory(prefix="stage78-validator-source-") as directory:
                root = Path(directory)
                fake_adapter = root / "report_adapter.py"
                fake_adapter.write_text("# synthetic adapter source\n", encoding="utf-8")
                if source is not None:
                    (root / "output_validation.py").write_text(source, encoding="utf-8")
                adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY = None
                adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY_FUNCTIONS = None
                with patch.object(adapter, "__file__", str(fake_adapter)):
                    adapter._pathway_output_validation_module()

        private_name = "_stage78_pathway_output_validation"
        authority = adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY
        functions = adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY_FUNCTIONS
        original = sys.modules.pop(private_name, None)
        try:
            with self.assertRaisesRegex(ImportError, "stage78_pathway_output_validation_unavailable"):
                load_from(None)
            with self.assertRaisesRegex(ImportError, "stage78_pathway_output_validation_unavailable"):
                load_from("raise RuntimeError('boom')\n")
            self.assertNotIn(private_name, sys.modules)
            with self.assertRaisesRegex(ImportError, "stage78_pathway_output_validation_unavailable"):
                load_from("def canonical_pathway_units():\n    return None\n")
            with self.assertRaisesRegex(ImportError, "stage78_pathway_output_validation_unavailable"):
                load_from(
                    "canonical_pathway_units = 1\n"
                    "def pathway_docx_frame_contract():\n    return None\n"
                    "def pathway_trusted_pdf_conversion_binding():\n    return None\n"
                    "def validate_pathway_output_equivalence():\n    return None\n"
                )
        finally:
            adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY = authority
            adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY_FUNCTIONS = functions
            sys.modules.pop(private_name, None)
            if original is not None:
                sys.modules[private_name] = original

    def test_pathway_validator_resolution_is_repeatable_real_authority(self) -> None:
        adapter = _load_adapter()
        first = adapter._pathway_output_validation_module()
        second = adapter._pathway_output_validation_module()

        self.assertIs(first, second)
        self.assertEqual(Path(first.__file__).resolve(), (ENGINE / "output_validation.py").resolve())
        for name in adapter._PATHWAY_OUTPUT_VALIDATION_REQUIRED:
            value = getattr(first, name)
            self.assertTrue(callable(value))
            self.assertEqual(value.__module__, first.__name__)

    def test_pathway_validator_concurrent_first_resolution_returns_one_authority(self) -> None:
        adapter = _load_adapter()
        adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY = None
        adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY_FUNCTIONS = None
        sys.modules.pop(adapter._PATHWAY_OUTPUT_VALIDATION_MODULE_NAME, None)
        results = []
        errors = []

        def resolve() -> None:
            try:
                results.append(adapter._pathway_output_validation_module())
            except Exception as exc:  # pragma: no cover - assertion reports the collected exception
                errors.append(exc)

        threads = [threading.Thread(target=resolve) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result is results[0] for result in results))
        self.assertIs(adapter._PATHWAY_OUTPUT_VALIDATION_AUTHORITY, results[0])


if __name__ == "__main__":
    unittest.main()
