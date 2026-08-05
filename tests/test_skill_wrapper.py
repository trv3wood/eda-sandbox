from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillWrapperTest(unittest.TestCase):
    def test_both_skills_expose_the_shared_harness(self) -> None:
        for skill in ("modeling-systemc-tlm", "modeling-systemverilog"):
            wrapper = ROOT / "skills" / skill / "scripts" / "eda-harness"
            result = subprocess.run(
                [str(wrapper), "--help"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("discover", result.stdout)

    def test_vcs_role_executes_directly_and_translates_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            result = subprocess.run(
                [
                    str(ROOT / "scripts" / "eda-run"),
                    "--work", str(work), "vcs", "python3", "-c",
                    "import sys; print(sys.argv[1])", "/workspace/project",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(result.stdout.strip(), str(work / "project"))


if __name__ == "__main__":
    unittest.main()
