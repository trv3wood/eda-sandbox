from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tlm_agent.io import dump_yaml, project_paths
from tlm_agent.verifier import verify_project


class VerifierTest(unittest.TestCase):
    def test_podman_mounts_project_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "external-project"
            paths = project_paths(project)
            paths["model"].mkdir(parents=True)
            (paths["model"] / "CMakeLists.txt").write_text("", encoding="utf-8")
            dump_yaml(paths["contract_test_manifest"], {"tests": []})
            with patch("tlm_agent.verifier.shutil.which", return_value="/usr/bin/podman-compose"), \
                 patch("tlm_agent.verifier._execute", return_value={"status": "passed"}) as execute:
                result = verify_project(project, backend="podman")

            command = execute.call_args.args[0]
            self.assertIn("--volume", command)
            self.assertIn(f"{project.resolve()}:/project", command)
            self.assertIn("cd /project", command[-1])
            self.assertEqual(result["backend"], "podman")

    @patch.dict("tlm_agent.verifier.os.environ", {"EDA_CXX_STANDARD": "17"})
    @patch("tlm_agent.verifier._execute")
    @patch("tlm_agent.verifier.shutil.which", return_value=None)
    def test_local_uses_sdk_cxx_standard(self, _which, execute) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            paths = project_paths(project)
            paths["model"].mkdir(parents=True)
            (paths["model"] / "CMakeLists.txt").write_text("", encoding="utf-8")
            dump_yaml(paths["contract_test_manifest"], {"tests": []})
            execute.side_effect = [
                {"status": "failed", "returncode": 1, "output": ""},
            ]
            verify_project(project, backend="local")

            configure_command = execute.call_args.args[0]
            self.assertIn("-DMODEL_CXX_STANDARD=17", configure_command)


if __name__ == "__main__":
    unittest.main()
