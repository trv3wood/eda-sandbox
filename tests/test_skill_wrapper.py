from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillWrapperTest(unittest.TestCase):
    def test_skills_expose_the_shared_harness(self) -> None:
        for skill in (
            "eda-tool-assistant",
            "cycle-systemc-modeling",
            "modeling-systemc-tlm",
            "modeling-systemverilog",
        ):
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

    def test_vcs_is_not_an_eda_run_role(self) -> None:
        result = subprocess.run(
            [str(ROOT / "scripts" / "eda-run"), "vcs", "vcs", "-ID"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("unknown role: vcs", result.stdout)


if __name__ == "__main__":
    unittest.main()
