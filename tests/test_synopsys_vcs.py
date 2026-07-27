from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from systemc_tlm_agent.io import dump_json, dump_yaml, load_yaml, project_paths
from systemc_tlm_agent.tool_producers import finalize_tools, produce_vcs


class SynopsysVcsTest(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        (root / "rtl.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        (root / "tb.sv").write_text("module tb; dut u_dut(); endmodule\n", encoding="utf-8")
        dump_yaml(root / "manifest.yaml", {
            "name": "vcs-fixture",
            "target_top": "dut",
            "rtl": ["rtl.sv"],
            "testbench": ["tb.sv"],
            "eda_compile": {"sources": ["rtl.sv"], "include_dirs": [], "defines": []},
            "synopsys_vcs": {
                "sim_top": "tb",
                "compile_args": ["-timescale=1ns/1ps"],
                "run_args": ["+smoke"],
                "fsdb_path": "waves/test.fsdb",
                "fsdb_index_command": ["site-fsdb-index", "{fsdb}", "{output}"],
            },
        })
        return root

    def test_submits_sync_lsf_job_and_validates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            paths = project_paths(project)

            def run(command: list[str], **_: object) -> types.SimpleNamespace:
                (project / "waves").mkdir()
                (project / "waves/test.fsdb").write_bytes(b"fsdb")
                dump_json(paths["tools"] / "vcs-work" / "vcs-index.json", {
                    "schema_version": 1,
                    "format": "vcs-json",
                    "modules": [{"name": "dut"}],
                    "signals": [{"module": "dut", "name": "clk", "width": 1}],
                })
                return types.SimpleNamespace(returncode=0, stdout="Job <42> is submitted")

            with (
                patch("systemc_tlm_agent.tool_producers.shutil.which", return_value="/usr/bin/bsub"),
                patch("systemc_tlm_agent.tool_producers.subprocess.run", side_effect=run) as call,
            ):
                result = produce_vcs(project)

            command = call.call_args.args[0]
            self.assertEqual(command[:4], ["bsub", "-q", "sim", "-K"])
            self.assertEqual(result["tools"]["vcs"]["status"], "passed")
            script = Path(result["tools"]["vcs"]["script"]).read_text(encoding="utf-8")
            self.assertIn("vcs -sverilog -full64 -top tb", script)
            self.assertIn("site-fsdb-index", script)
            self.assertIn("waves/test.fsdb", script)

    def test_rejects_escape_and_invalid_index_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            manifest = load_yaml(project / "manifest.yaml")
            manifest["synopsys_vcs"]["fsdb_path"] = "../test.fsdb"
            dump_yaml(project / "manifest.yaml", manifest)
            with self.assertRaisesRegex(ValueError, "stay within"):
                produce_vcs(project)
            manifest["synopsys_vcs"]["fsdb_path"] = "waves/test.fsdb"
            manifest["synopsys_vcs"]["fsdb_index_command"] = ["index", "--in={fsdb}"]
            dump_yaml(project / "manifest.yaml", manifest)
            with self.assertRaisesRegex(ValueError, "must contain"):
                produce_vcs(project)

    def test_finalize_requires_vcs_result_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            paths = project_paths(project)
            paths["facts"].mkdir(parents=True)
            dump_json(paths["facts"] / "rtl.json", {"tools": {}})
            for producer in ("uhdm", "rtl"):
                dump_json(paths["tools"] / f"producer-{producer}.json", {"tools": {}})
            with self.assertRaisesRegex(ValueError, "vcs"):
                finalize_tools(project)
            dump_json(paths["tools"] / "producer-vcs.json", {"tools": {"vcs": {"status": "passed"}}})
            self.assertEqual(finalize_tools(project)["status"], "finalized")


if __name__ == "__main__":
    unittest.main()
