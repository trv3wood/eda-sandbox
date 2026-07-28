from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path

from systemc_tlm_model_packager.packager import package_model


class PackageModelTests(unittest.TestCase):
    def test_package_uses_generated_gitignore_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            model = project / "model"
            (model / "src").mkdir(parents=True)
            (model / "build-contract").mkdir()
            testbench = project / ".systemc-agent" / "contracts" / "testbench"
            (testbench / "tests").mkdir(parents=True)
            (testbench / "build-contract").mkdir()
            (model / ".gitignore").write_text(
                "/build-contract/\n*.log\n", encoding="utf-8"
            )
            (model / "src" / "dma.cpp").write_text("// source\n", encoding="utf-8")
            (model / "build-contract" / "model_smoke").write_text(
                "binary", encoding="utf-8"
            )
            (model / "verify.log").write_text("log\n", encoding="utf-8")
            (testbench / "tests" / "dma_contract.cpp").write_text(
                "// contract\n", encoding="utf-8"
            )
            (testbench / "build-contract" / "contract_test").write_text(
                "binary", encoding="utf-8"
            )
            (testbench / "contract.log").write_text("log\n", encoding="utf-8")

            result = package_model(project)

            self.assertEqual(result["file_count"], 3)
            self.assertEqual(result["ignored_count"], 4)
            with tarfile.open(result["archive"], "r:gz") as archive:
                self.assertEqual(archive.getnames(), [
                    "model/.gitignore",
                    "model/src/dma.cpp",
                    "contracts/testbench/tests/dma_contract.cpp",
                ])


if __name__ == "__main__":
    unittest.main()
