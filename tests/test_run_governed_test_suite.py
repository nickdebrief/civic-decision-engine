import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_governed_test_suite.py"
SPEC = importlib.util.spec_from_file_location("governed_suite_under_test", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class GovernedSuiteTests(unittest.TestCase):
    def make_root(self, modules=("tests.test_alpha", "tests.test_beta")):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "tests").mkdir()
        (root / "scripts").mkdir()
        (root / "scripts" / "run_isolated_tests.py").write_text("# synthetic\n")
        for module in modules:
            (root / (module.replace(".", "/") + ".py")).write_text(
                "import unittest\n\nclass SyntheticTests(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
            )
        return temp, root

    def manifest(self, root, tracked, untracked=()):
        return runner.governed_entries(root, tracked=set(tracked), untracked=set(untracked))

    def test_root_derivation_does_not_depend_on_cwd(self):
        self.assertEqual(runner.repository_root(), SCRIPT.parent.parent)

    def test_complete_manifest_is_sorted_and_classified(self):
        temp, root = self.make_root()
        with temp, patch.object(runner, "GOVERNED_TRACKED_MODULES", frozenset({"tests.test_alpha", "tests.test_beta"})), patch.object(runner, "REAL_ASGI_MODULES", frozenset({"tests.test_alpha"})), patch.object(runner, "LEGACY_FASTAPI_STUB_MODULES", frozenset({"tests.test_beta"})):
            entries, excluded = self.manifest(root, {"tests.test_beta", "tests.test_alpha"})
        self.assertEqual([(item.module, item.classification, item.framework) for item in entries], [("tests.test_alpha", "real_asgi", "unittest"), ("tests.test_beta", "legacy_fastapi_stub", "unittest")])
        self.assertEqual(excluded, ())

    def test_manifest_rejects_duplicates_cross_partition_missing_and_escape(self):
        with self.assertRaisesRegex(runner.ManifestError, "duplicate"):
            runner.manifest_entries(["tests.test_a", "tests.test_a"])
        with patch.object(runner, "REAL_ASGI_MODULES", frozenset({"tests.test_a"})), patch.object(runner, "LEGACY_FASTAPI_STUB_MODULES", frozenset({"tests.test_a"})):
            with self.assertRaisesRegex(runner.ManifestError, "cross_partition"):
                runner.manifest_entries(["tests.test_a"])
        with self.assertRaisesRegex(runner.ManifestError, "invalid"):
            runner.module_path(Path("/tmp"), "tests.bad-name")
        with self.assertRaisesRegex(runner.ManifestError, "invalid"):
            runner.module_path(Path("/tmp"), "tests..escape")

    def test_inventory_rejects_missing_tracked_unknown_untracked_and_missing_file(self):
        temp, root = self.make_root(("tests.test_alpha",))
        with temp, patch.object(runner, "GOVERNED_TRACKED_MODULES", frozenset({"tests.test_alpha"})):
            with self.assertRaisesRegex(runner.ManifestError, "tracked_inventory"):
                self.manifest(root, set())
            with self.assertRaisesRegex(runner.ManifestError, "unclassified_untracked"):
                self.manifest(root, {"tests.test_alpha"}, {"tests.test_other"})
            (root / "tests" / "test_alpha.py").unlink()
            with self.assertRaisesRegex(runner.ManifestError, "module_missing"):
                self.manifest(root, {"tests.test_alpha"})

    def test_known_untracked_candidate_is_excluded_not_governed(self):
        temp, root = self.make_root()
        with temp, patch.object(runner, "GOVERNED_TRACKED_MODULES", frozenset({"tests.test_alpha", "tests.test_beta"})), patch.object(runner, "EXCLUDED_UNTRACKED_MODULES", frozenset({"tests.test_stage78"})):
            entries, excluded = self.manifest(root, {"tests.test_alpha", "tests.test_beta"}, {"tests.test_stage78"})
        self.assertEqual([entry.module for entry in entries], ["tests.test_alpha", "tests.test_beta"])
        self.assertEqual(excluded, ("tests.test_stage78",))

    def test_dry_run_executes_no_child_and_is_bounded(self):
        calls, output = [], []
        entries = (runner.Entry("tests.test_alpha", "neutral", "unittest"),)
        status = runner.run_suite(Path("/synthetic"), entries, dry_run=True, run_process=lambda *args, **kwargs: calls.append(args), output=output.append)
        self.assertEqual(status, 0)
        self.assertEqual(calls, [])
        self.assertEqual(output, ["[1/1] neutral unittest tests.test_alpha target=tests.test_alpha", "dry-run modules=1"])

    def test_child_uses_launcher_list_shell_false_and_preserves_environment(self):
        calls, output = [], []
        def fake_child(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0)
        entries = (runner.Entry("tests.test_alpha", "neutral", "unittest"), runner.Entry("tests.test_beta", "legacy_fastapi_stub", "unittest"))
        status = runner.run_suite(Path("/synthetic"), entries, dry_run=False, run_process=fake_child, output=output.append)
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][1:3], ["/synthetic/scripts/run_isolated_tests.py", "unittest"])
        self.assertEqual(calls[0][1]["shell"], False)
        self.assertEqual(calls[0][1]["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("RECORDS_DB_PATH", runner.run_suite.__code__.co_consts)
        self.assertEqual(output[-1], "final passed_modules=2 failed_modules=0")

    def test_failure_containment_and_infrastructure_stop_before_next_child(self):
        entries = (runner.Entry("tests.test_alpha", "neutral", "unittest"), runner.Entry("tests.test_beta", "neutral", "unittest"))
        for status in (1, 5, 97):
            calls = []
            result = runner.run_suite(Path("/synthetic"), entries, dry_run=False, run_process=lambda *args, **kwargs: (calls.append(args) or SimpleNamespace(returncode=status)), output=lambda _value: None)
            self.assertEqual(result, status)
            self.assertEqual(len(calls), 1)
        result = runner.run_suite(Path("/synthetic"), entries, dry_run=False, run_process=lambda *args, **kwargs: SimpleNamespace(), output=lambda _value: None)
        self.assertEqual(result, runner.ORCHESTRATOR_STATUS)

    def test_manifest_check_mode_never_starts_children(self):
        temp, root = self.make_root(("tests.test_alpha",))
        with temp, patch.object(runner, "repository_root", return_value=root), patch.object(runner, "GOVERNED_TRACKED_MODULES", frozenset({"tests.test_alpha"})), patch.object(runner, "git_test_modules", side_effect=[{"tests.test_alpha"}, set()]):
            self.assertEqual(runner.main(["--manifest-check"]), 0)

    def test_framework_validation_rejects_invalid_mismatch_and_empty_sources(self):
        temp, root = self.make_root(("tests.test_pytest", "tests.test_empty"))
        with temp:
            (root / "tests" / "test_pytest.py").write_text("def test_visible():\n    pass\n")
            (root / "tests" / "test_empty.py").write_text("VALUE = 1\n")
            with self.assertRaisesRegex(runner.ManifestError, "framework_invalid"):
                runner.validate_source_framework(root, runner.Entry("tests.test_pytest", "neutral", "other"))
            with self.assertRaisesRegex(runner.ManifestError, "framework_source_mismatch"):
                runner.validate_source_framework(root, runner.Entry("tests.test_pytest", "neutral", "unittest"))
            with self.assertRaisesRegex(runner.ManifestError, "framework_no_tests"):
                runner.validate_source_framework(root, runner.Entry("tests.test_empty", "neutral", "unittest"))

    def test_pytest_child_uses_repository_relative_path(self):
        calls = []
        entry = runner.Entry("tests.test_stage71_1_procedural_time_ui", "neutral", "pytest")
        result = runner.run_suite(
            Path("/synthetic"), (entry,), dry_run=False,
            run_process=lambda command, **kwargs: (calls.append((command, kwargs)) or SimpleNamespace(returncode=0)),
            output=lambda _value: None,
        )
        self.assertEqual(result, 0)
        self.assertEqual(calls[0][0][1:], ["/synthetic/scripts/run_isolated_tests.py", "pytest", "tests/test_stage71_1_procedural_time_ui.py"])
        self.assertFalse(calls[0][1]["shell"])

    def test_stage71_is_explicitly_pytest(self):
        self.assertEqual(runner.framework_for("tests.test_stage71_1_procedural_time_ui"), "pytest")

    def test_transitioned_modules_are_tracked_once_with_preserved_execution_properties(self):
        transitioned = {
            "tests.test_canonical_public_origin": ("real_asgi", "unittest", 19),
            "tests.test_run_governed_test_suite": ("neutral", "unittest", 77),
        }
        entries = runner.manifest_entries(runner.GOVERNED_TRACKED_MODULES)
        self.assertEqual(len(entries), 132)
        self.assertEqual(len({entry.module for entry in entries}), 132)
        self.assertFalse(hasattr(runner, "CANDIDATE_GOVERNED_MODULES"))
        self.assertEqual(
            runner.EXCLUDED_UNTRACKED_MODULES,
            frozenset({"tests.test_stage78b_pathway_output_equivalence"}),
        )
        for module, (classification, framework, ordinal) in transitioned.items():
            self.assertIn(module, runner.GOVERNED_TRACKED_MODULES)
            entry = entries[ordinal - 1]
            self.assertEqual((entry.module, entry.classification, entry.framework), (module, classification, framework))
            self.assertEqual(entry.module, module)

    def test_live_tracked_inventory_matches_governed_authority(self):
        root = runner.repository_root()
        tracked = runner.git_test_modules(
            root,
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "tests"],
        )
        self.assertEqual(tracked, set(runner.GOVERNED_TRACKED_MODULES))

    def test_tracked_transition_mismatch_fails_closed(self):
        temp, root = self.make_root(("tests.test_alpha", "tests.test_transitioned"))
        with temp, patch.object(runner, "GOVERNED_TRACKED_MODULES", frozenset({"tests.test_alpha"})):
            with self.assertRaisesRegex(runner.ManifestError, "tracked_inventory"):
                self.manifest(root, {"tests.test_alpha", "tests.test_transitioned"})


if __name__ == "__main__":
    unittest.main()
