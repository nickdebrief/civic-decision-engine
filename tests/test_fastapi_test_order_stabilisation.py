import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STAGE62 = "tests/test_stage62_governed_pattern_observation.py"
STAGE661 = "tests/test_stage66_1_deliberate_authority_classification.py"


class FastAPITestOrderStabilisationTests(unittest.TestCase):
    def run_pytest_order(self, first, second):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = dict(os.environ)
            env["RECORDS_DB_PATH"] = str(Path(temp_dir) / "records.db")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--disable-warnings",
                    "--ignore=test_cases/test_cases.py",
                    first,
                    second,
                ],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("passed", result.stdout)

    def test_stage62_then_stage661_in_fresh_process(self):
        self.run_pytest_order(STAGE62, STAGE661)

    def test_stage661_then_stage62_in_fresh_process(self):
        self.run_pytest_order(STAGE661, STAGE62)

    def test_stage661_import_does_not_import_admin_route(self):
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import tests.test_stage66_1_deliberate_authority_classification; "
                    "assert 'api.routes.admin_session' not in sys.modules"
                ),
            ],
            cwd=REPOSITORY_ROOT,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)


if __name__ == "__main__":
    unittest.main()
