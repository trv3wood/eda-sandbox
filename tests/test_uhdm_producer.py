from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from systemc_tlm_agent.extractors import extract_project
from systemc_tlm_agent.io import (
    dump_json,
    dump_yaml,
    file_digest,
    load_json,
    project_paths,
)
from systemc_tlm_agent.tool_producers import finalize_tools, produce_uhdm


class UhdmProducerTest(unittest.TestCase):
    @staticmethod
    def _project(root: Path) -> tuple[Path, Path]:
        rtl = root / "top.sv"
        rtl.write_text("module top; endmodule\n", encoding="utf-8")
        dump_yaml(
            root / "manifest.yaml",
            {
                "schema_version": 1,
                "name": "uhdm-fixture",
                "target_top": "top",
                "reference_top": "top",
                "rtl": ["top.sv"],
                "eda_compile": {
                    "sources": ["top.sv"],
                    "include_dirs": [],
                    "defines": [],
                },
            },
        )
        return root, rtl

    @staticmethod
    def _structure(database: Path, rtl: Path) -> dict:
        location = {
            "path": str(rtl),
            "sha256": file_digest(rtl),
            "line": 1,
        }
        module = {
            "name": "work@top",
            "definition": "work@top",
            **location,
            "ports": [],
            "parameters": [],
            "instances": [],
        }
        return {
            "schema_version": 1,
            "backend": "uhdm-python-vpi",
            "database": {
                "path": str(database),
                "sha256": file_digest(database),
                "size": database.stat().st_size,
            },
            "reference_top": "top",
            "top_modules": [module],
            "modules": [module],
        }

    @patch("systemc_tlm_agent.tool_producers._version", return_value="1.84")
    @patch("systemc_tlm_agent.tool_producers.export_uhdm_structure")
    @patch("systemc_tlm_agent.tool_producers._run")
    def test_fixed_cli_sequence_and_markers(self, run, export, _version) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))

            def execute(command, cwd, log):
                log.parent.mkdir(parents=True, exist_ok=True)
                if command[0] == "surelog":
                    database = cwd / "slpp_all" / "surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"native uhdm")
                    log.write_text("surelog passed\n")
                elif command[0] == "uhdm-dump":
                    log.write_text(
                        "Restored design Pre-Elab:\n"
                        "Restored design Post-Elab:\n"
                    )
                elif command[0] == "uhdm-hier":
                    log.write_text(
                        "Design name: work\nInstance tree:\nwork@top (work@top top.sv:1:)\n"
                    )
                else:
                    log.write_text("")
                return {
                    "status": "passed",
                    "returncode": 0,
                    "command": command,
                    "log": str(log),
                }

            run.side_effect = execute

            def make_structure(database, sources, reference_top):
                self.assertEqual(reference_top, "top")
                return self._structure(database, rtl)

            export.side_effect = make_structure
            result = produce_uhdm(project)

            self.assertEqual(result["tools"]["uhdm"]["status"], "passed")
            self.assertEqual(
                [call.args[0][0] for call in run.call_args_list],
                ["surelog", "uhdm-dump", "uhdm-lint", "uhdm-hier"],
            )
            self.assertIn("--elab", run.call_args_list[1].args[0])

    @patch("systemc_tlm_agent.tool_producers._version", return_value="1.84")
    @patch("systemc_tlm_agent.tool_producers.export_uhdm_structure")
    @patch("systemc_tlm_agent.tool_producers._run")
    def test_dump_zero_exit_without_markers_fails_gate(
        self, run, export, _version
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _ = self._project(Path(temporary))

            def execute(command, cwd, log):
                log.parent.mkdir(parents=True, exist_ok=True)
                if command[0] == "surelog":
                    database = cwd / "slpp_all" / "surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"stale uhdm")
                log.write_text("Usage:\n")
                return {"status": "passed", "returncode": 0}

            run.side_effect = execute
            result = produce_uhdm(project)

            self.assertEqual(result["tools"]["uhdm_elab"]["status"], "failed")
            self.assertEqual(result["tools"]["uhdm"]["status"], "failed")
            export.assert_not_called()

    @patch("systemc_tlm_agent.tool_producers._version", return_value="1.84")
    @patch("systemc_tlm_agent.tool_producers.export_uhdm_structure")
    @patch("systemc_tlm_agent.tool_producers._run")
    def test_finalize_publishes_portable_uhdm_facts(
        self, run, export, _version
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))
            extract_project(project, run_tools=False)

            def execute(command, cwd, log):
                log.parent.mkdir(parents=True, exist_ok=True)
                if command[0] == "surelog":
                    database = cwd / "slpp_all" / "surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"native uhdm")
                    log.write_text("surelog passed\n")
                elif command[0] == "uhdm-dump":
                    log.write_text(
                        "Restored design Pre-Elab:\n"
                        "Restored design Post-Elab:\n"
                    )
                elif command[0] == "uhdm-hier":
                    log.write_text(
                        "Design name: work\nInstance tree:\nwork@top (work@top top.sv:1:)\n"
                    )
                else:
                    log.write_text("")
                return {"status": "passed", "returncode": 0}

            run.side_effect = execute

            def make_structure(database, sources, reference_top):
                return self._structure(database, rtl)

            export.side_effect = make_structure
            produce_uhdm(project)
            paths = project_paths(project)
            dump_json(
                paths["tools"] / "producer-rtl.json",
                {
                    "schema_version": 1,
                    "producer": "rtl",
                    "inputs": [{"path": str(rtl), "sha256": file_digest(rtl)}],
                    "tools": {
                        "verilator": {"status": "passed"},
                        "yosys": {"status": "passed"},
                    },
                },
            )

            finalize_tools(project)

            facts = load_json(paths["facts"] / "rtl.json")
            self.assertEqual(facts["status"], "ready")
            self.assertEqual(facts["backend"], "uhdm")
            self.assertEqual(facts["files"][0]["path"], "top.sv")
            self.assertEqual(facts["files"][0]["modules"][0]["name"], "top")
            self.assertNotIn("/workspace/", str(facts["top_modules"]))
            self.assertEqual(
                len(paths["evidence"].read_text().splitlines()), 1
            )
