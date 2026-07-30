from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tlm_agent.extractors import extract_project
from tlm_agent.io import dump_yaml, load_json, load_yaml, project_paths
from tlm_agent.tool_producers import (
    _compile_inputs,
    _normalize_vcs_structure,
    _vcs_debug_arguments,
    finalize_tools,
    produce_vcs,
)


class VcsProducerTest(unittest.TestCase):
    def test_debug_access_defaults_and_explicit_override(self) -> None:
        self.assertEqual(
            _vcs_debug_arguments([]),
            ["-debug_access+all"],
        )
        self.assertEqual(
            _vcs_debug_arguments(["-debug_access+pp"]),
            [],
        )

    @staticmethod
    def _project(root: Path) -> tuple[Path, Path]:
        rtl = root / "top.sv"
        rtl.write_text(
            "package cfg_pkg; parameter int WIDTH = 8; endpackage\n"
            "module child(input logic clk); logic ready; endmodule\n"
            "module top(input logic clk); child u_child(.clk(clk)); endmodule\n",
            encoding="utf-8",
        )
        dump_yaml(
            root / "manifest.yaml",
            {
                "schema_version": 1,
                "name": "vcs-fixture",
                "target_top": "top",
                "reference_top": "top",
                "rtl": ["top.sv"],
                "eda_compile": {
                    "sources": ["top.sv"],
                    "include_dirs": [],
                    "defines": ["FEATURE=1"],
                    "vcs_args": ["-timescale=1ns/1ps"],
                },
                "graph": {
                    "rtl_extraction": {
                        "backend": "vcs-vpi",
                        "timeout_seconds": 60,
                    },
                    "spec_extraction": {"enabled": False},
                },
            },
        )
        return root, rtl

    @staticmethod
    def _raw(rtl: Path) -> dict:
        location = {"path": str(rtl), "line": 1}
        child = {
            "name": "top.u_child",
            "definition": "child",
            **location,
            "ports": [
                {
                    "name": "clk",
                    "direction": "input",
                    "size": 1,
                    **location,
                }
            ],
            "parameters": [],
            "signals": [{"name": "ready", "size": 1, **location}],
            "imports": [],
            "instances": [],
        }
        top = {
            "name": "top",
            "definition": "top",
            **location,
            "ports": [
                {
                    "name": "clk",
                    "direction": "input",
                    "size": 1,
                    **location,
                }
            ],
            "parameters": [],
            "signals": [],
            "imports": [{"name": "cfg_pkg", **location}],
            "instances": [child],
        }
        return {
            "top_modules": [top],
            "packages": [{"name": "cfg_pkg", **location}],
        }

    def test_normalizes_definition_and_elaborated_views(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))
            executable = project / "simv"
            executable.write_bytes(b"simv")

            structure = _normalize_vcs_structure(
                self._raw(rtl),
                reference_top="top",
                executable=executable,
            )

            self.assertEqual(structure["backend"], "vcs-vpi")
            self.assertEqual(
                [item["definition"] for item in structure["modules"]],
                ["work@child", "work@top"],
            )
            self.assertEqual(
                structure["top_modules"][0]["instances"][0]["name"],
                "u_child",
            )
            self.assertEqual(structure["packages"][0]["name"], "cfg_pkg")

    def test_nested_filelists_preserve_dependency_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            lists = project / "lists"
            rtl = project / "rtl"
            lists.mkdir()
            rtl.mkdir()
            package = rtl / "cfg.svp"
            top = rtl / "top.sv"
            extra = rtl / "extra.sv"
            for path in (package, top, extra):
                path.write_text("module fixture; endmodule\n", encoding="utf-8")
            nested = lists / "common.f"
            nested.write_text("../rtl/cfg.svp\n", encoding="utf-8")
            root = lists / "top.f"
            root.write_text(
                "-F lists/common.f\nrtl/top.sv\n",
                encoding="utf-8",
            )
            dump_yaml(
                project / "manifest.yaml",
                {
                    "target_top": "top",
                    "rtl": [],
                    "eda_compile": {
                        "filelists": ["lists/top.f"],
                        "sources": ["rtl/extra.sv"],
                    },
                },
            )

            inputs = _compile_inputs(project)
            summary = extract_project(project, run_tools=False)

            self.assertEqual(inputs.filelists, [root.resolve()])
            self.assertEqual(
                inputs.all_filelists,
                [root.resolve(), nested.resolve()],
            )
            self.assertEqual(
                inputs.source_files,
                [package.resolve(), top.resolve(), extra.resolve()],
            )
            self.assertEqual(summary["filelist_count"], 2)
            self.assertEqual(summary["rtl_file_count"], 3)
            self.assertTrue(summary["rtl_available"])

    @patch("tlm_agent.tool_producers._version", return_value="fixture-version")
    @patch("tlm_agent.tool_producers._vcs_home")
    @patch("tlm_agent.tool_producers._run")
    def test_vcs_flow_and_finalize_publish_graph(
        self, run, vcs_home, _version
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))
            filelist = project / "rtl.f"
            filelist.write_text("top.sv\n", encoding="utf-8")
            manifest = load_yaml(project / "manifest.yaml")
            manifest["eda_compile"]["filelists"] = ["rtl.f"]
            manifest["eda_compile"]["sources"] = []
            dump_yaml(project / "manifest.yaml", manifest)
            install = project / "vcs"
            (install / "include").mkdir(parents=True)
            (install / "include" / "vpi_user.h").write_text("", encoding="utf-8")
            vcs_home.return_value = install
            extract_project(project, run_tools=False)

            def execute(command, cwd, log, **kwargs):
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("", encoding="utf-8")
                if command[0].endswith("cc"):
                    Path(command[-1]).write_bytes(b"shared library")
                elif command[0] == "vcs":
                    output = Path(command[command.index("-o") + 1])
                    output.write_bytes(b"simv")
                else:
                    output = Path(kwargs["env"]["TLM_GRAPH_OUTPUT"])
                    output.write_text(
                        json.dumps(self._raw(rtl)), encoding="utf-8"
                    )
                return {
                    "status": "passed",
                    "returncode": 0,
                    "command": command,
                    "log": str(log),
                }

            run.side_effect = execute
            with patch("tlm_agent.tool_producers.shutil.which", return_value="/usr/bin/cc"):
                result = produce_vcs(project)
            finalized = finalize_tools(project)

            self.assertEqual(result["tools"]["rtl"]["status"], "passed")
            self.assertEqual(
                result["compile"]["filelists"],
                [str(filelist.resolve())],
            )
            self.assertEqual(
                result["compile"]["filelist_source_closure"],
                [str(rtl.resolve())],
            )
            vcs_command = run.call_args_list[1].args[0]
            filelist_index = vcs_command.index("-f")
            self.assertEqual(
                vcs_command[filelist_index + 1],
                str(filelist.resolve()),
            )
            self.assertNotIn(str(rtl.resolve()), vcs_command)
            self.assertIn("+define+FEATURE=1", vcs_command)
            self.assertEqual(vcs_command.count("-debug_access+all"), 1)
            self.assertIn("-timescale=1ns/1ps", vcs_command)
            self.assertTrue(
                any(
                    value.endswith(
                        "libtlm_graph_vpi.so:tlm_graph_register"
                    )
                    for value in vcs_command
                )
            )
            self.assertEqual(finalized["graph"]["status"], "ready")
            graph_manifest = load_json(project_paths(project)["graph_manifest"])
            self.assertEqual(
                graph_manifest["producers"]["rtl"]["status"], "passed"
            )
            entities = [
                json.loads(line)
                for line in project_paths(project)["graph_entities"]
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(
                sorted(item["name"] for item in entities if item["type"] == "Module"),
                ["child", "top"],
            )

    def test_rejects_wrong_top(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, rtl = self._project(Path(temporary))
            executable = project / "simv"
            executable.write_bytes(b"simv")
            with self.assertRaisesRegex(ValueError, "exactly top missing"):
                _normalize_vcs_structure(
                    self._raw(rtl),
                    reference_top="missing",
                    executable=executable,
                )


if __name__ == "__main__":
    unittest.main()
