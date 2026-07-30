from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tlm_agent.extractors import extract_project
from tlm_agent.io import (
    dump_json,
    dump_yaml,
    file_digest,
    load_json,
    project_paths,
)
from tlm_agent.tool_producers import _inputs, finalize_tools, produce_uhdm


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

    def test_compile_sources_honor_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))
            ignored = project / "ignored.sv"
            ignored.write_text("module ignored; endmodule\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "name": "uhdm-fixture",
                "target_top": "top",
                "reference_top": "top",
                "rtl": ["top.sv"],
                "eda_compile": {
                    "sources": ["*.sv"],
                    "exclude_sources": ["ignored.sv"],
                    "include_dirs": [],
                    "defines": [],
                },
            }
            dump_yaml(project / "manifest.yaml", manifest)

            _, sources, _, _ = _inputs(project)

            self.assertEqual(sources, [rtl.resolve()])

    def test_directory_discovery_includes_svp_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            rtl_dir = project / "rtl"
            testbench_dir = project / "testbench"
            rtl_dir.mkdir()
            testbench_dir.mkdir()
            rtl = rtl_dir / "top.svp"
            testbench = testbench_dir / "top_tb.SVP"
            rtl.write_text("module top; endmodule\n", encoding="utf-8")
            testbench.write_text("module top_tb; endmodule\n", encoding="utf-8")
            dump_yaml(
                project / "manifest.yaml",
                {
                    "schema_version": 1,
                    "name": "svp-fixture",
                    "target_top": "top",
                    "reference_top": "top",
                    "rtl": ["rtl"],
                    "testbench": ["testbench"],
                    "eda_compile": {
                        "sources": ["rtl", "testbench"],
                        "include_dirs": [],
                        "defines": [],
                    },
                },
            )

            summary = extract_project(project, run_tools=False)
            _, sources, _, _ = _inputs(project)

            self.assertEqual(summary["rtl_file_count"], 1)
            self.assertEqual(summary["testbench_file_count"], 1)
            self.assertEqual(sources, [rtl.resolve(), testbench.resolve()])

    @patch("tlm_agent.tool_producers._version", return_value="1.84")
    @patch("tlm_agent.tool_producers.export_uhdm_structure")
    @patch("tlm_agent.tool_producers._run")
    def test_fixed_cli_sequence_and_markers(self, run, export, _version) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))

            def execute(command, cwd, log, **_kwargs):
                log.parent.mkdir(parents=True, exist_ok=True)
                if command[0] == "surelog":
                    database = cwd / "slpp_all" / "surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"native uhdm")
                    log.write_text("[  FATAL] : 0\n[  ERROR] : 0\n")
                elif command[0] == "uhdm-hier":
                    log.write_text(
                        "Design name: work\nInstance tree:\nwork@top (work@top top.sv:1:)\n"
                    )
                else:
                    log.write_text("")
                return {
                    "status": "failed" if command[0] == "surelog" else "passed",
                    "returncode": 4 if command[0] == "surelog" else 0,
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
                ["surelog", "uhdm-lint", "uhdm-hier"],
            )
            self.assertNotIn("-d", run.call_args_list[0].args[0])

    @patch("tlm_agent.tool_producers._version", return_value="1.84")
    @patch("tlm_agent.tool_producers.export_uhdm_structure")
    @patch("tlm_agent.tool_producers._run")
    def test_surelog_without_clean_summary_fails_gate(
        self, run, export, _version
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _ = self._project(Path(temporary))

            def execute(command, cwd, log, **_kwargs):
                log.parent.mkdir(parents=True, exist_ok=True)
                if command[0] == "surelog":
                    database = cwd / "slpp_all" / "surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"stale uhdm")
                    log.write_text("Surelog did not print a summary\n")
                else:
                    log.write_text("Usage:\n")
                return {"status": "passed", "returncode": 0}

            run.side_effect = execute
            result = produce_uhdm(project)

            self.assertEqual(result["tools"]["uhdm_elab"]["status"], "skipped")
            self.assertEqual(result["tools"]["uhdm"]["status"], "failed")
            export.assert_not_called()

    @patch("tlm_agent.tool_producers._version", return_value="1.84")
    @patch("tlm_agent.tool_producers.export_uhdm_structure")
    @patch("tlm_agent.tool_producers._run")
    def test_finalize_publishes_portable_uhdm_graph(
        self, run, export, _version
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))
            extract_project(project, run_tools=False)

            def execute(command, cwd, log, **_kwargs):
                log.parent.mkdir(parents=True, exist_ok=True)
                if command[0] == "surelog":
                    database = cwd / "slpp_all" / "surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"native uhdm")
                    log.write_text("[  FATAL] : 0\n[  ERROR] : 0\n")
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
            finalize_tools(project)

            manifest = load_json(paths["graph_manifest"])
            entities = [
                json.loads(line)
                for line in paths["graph_entities"].read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(manifest["status"], "ready")
            self.assertEqual(
                manifest["producers"]["cross_source"]["status"], "passed"
            )
            modules = [item for item in entities if item["type"] == "Module"]
            self.assertEqual([item["name"] for item in modules], ["top"])
            self.assertNotIn("/workspace/", str(modules))
