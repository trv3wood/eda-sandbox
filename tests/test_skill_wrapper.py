from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class SkillWrapperTest(unittest.TestCase):
    def test_claude_symlink_resolves_repository_root(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = repository / "skills" / "modeling-systemc-tlm"
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installed = home / ".claude" / "skills" / source.name
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment.pop("SYSTEMC_TLM_AGENT_ROOT", None)
            environment.pop("PYTHONPATH", None)
            installation = subprocess.run(
                [
                    str(repository / "scripts" / "install-modeling-skill.sh"),
                    "--target",
                    "claude",
                    "--mode",
                    "link",
                ],
                cwd=repository,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(installation.returncode, 0, installation.stderr)

            result = subprocess.run(
                [str(installed / "scripts" / "systemc-tlm-agent"), "--help"],
                cwd=home,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("systemc-tlm-agent", result.stdout)

    def test_explicit_root_supports_copied_wrapper(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        wrapper = (
            repository
            / "skills"
            / "modeling-systemc-tlm"
            / "scripts"
            / "systemc-tlm-agent"
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "systemc-tlm-agent"
            copied.write_bytes(wrapper.read_bytes())
            copied.chmod(0o755)
            environment = os.environ.copy()
            environment["SYSTEMC_TLM_AGENT_ROOT"] = str(repository)
            environment.pop("PYTHONPATH", None)

            result = subprocess.run(
                [str(copied), "--help"],
                cwd=temporary,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("systemc-tlm-agent", result.stdout)


if __name__ == "__main__":
    unittest.main()
