from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from rtl_agent.generator import apply_rtl_edits, generate_rtl
from rtl_agent.verifier import verify_rtl
from rtl_agent.workflow import (
    approve_rtl,
    create_rtl_handoff_draft,
    rtl_approval_is_valid,
    validate_rtl_handoff,
)
from tlm_agent.cli import command_init
from tlm_agent.extractors import extract_project
from tlm_agent.graph.schema import read_jsonl, write_jsonl
from tlm_agent.io import dump_json, dump_yaml, file_digest, load_yaml, project_paths


class Args:
    backend = "local"
    docx: list[str] = []
    xlsx: list[str] = []
    rtl: list[str] = []


def _project_with_spec(root: Path) -> tuple[Path, str]:
    spec = root / "spec.md"
    spec.write_text("# 接口\n\n模块接收输入并产生输出。\n", encoding="utf-8")
    args = Args()
    args.project = str(root)
    args.name = "image-control"
    args.top = "image_ctrl"
    args.docx = ["spec.md"]
    command_init(args)
    extract_project(root)
    evidence = read_jsonl(project_paths(root)["graph"] / "text_units.jsonl")[0]["id"]
    return root, evidence


def _complete_interface_handoff(project: Path, evidence: str, *, mode: str = "interface") -> dict:
    paths = project_paths(project)
    create_rtl_handoff_draft(project, mode=mode)
    handoff = load_yaml(paths["rtl_handoff"])
    handoff["status"] = "complete"
    handoff["target"]["evidence_ids"] = [evidence]
    handoff["module_contracts"] = [{
        "name": "image_ctrl",
        "evidence_ids": [evidence],
        "imports": [],
        "parameters": [{"declaration": "parameter int DATA_WIDTH = 32"}],
        "ports": [
            {"declaration": "input logic clk_i"},
            {"declaration": "input logic [DATA_WIDTH-1:0] data_i"},
            {"declaration": "output logic [DATA_WIDTH-1:0] data_o"},
        ],
        "signals": [],
        "instances": [],
    }]
    handoff["requirements"] = [{
        "id": "RTL-FUNC-001",
        "module": "image_ctrl",
        "statement": "按照规格实现数据传递。",
        "evidence_ids": [evidence],
    }]
    dump_yaml(paths["rtl_handoff"], handoff)
    return handoff


class RtlAgentTest(unittest.TestCase):
    def test_interface_generation_bounded_edit_and_stale_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, evidence = _project_with_spec(Path(temporary))
            _complete_interface_handoff(project, evidence)
            self.assertEqual(validate_rtl_handoff(project), [])
            approve_rtl(project, approver="unit-test")
            self.assertTrue(rtl_approval_is_valid(project)[0])

            result = generate_rtl(project)
            self.assertEqual(result["mode"], "interface")
            paths = project_paths(project)
            generated = paths["rtl_worktree"] / "rtl" / "image_ctrl.sv"
            text = generated.read_text(encoding="utf-8")
            self.assertIn("TODO[RTL-FUNC-001]", text)
            self.assertIn("Evidence:", text)

            generation = load_yaml(paths["rtl_generation"])
            target = generation["targets"][0]
            edits = project / "candidate-edits.json"
            dump_json(edits, {"edits": [{
                "target_id": target["id"],
                "base_sha256": target["text_sha256"],
                "replacement_text": "    assign data_o = data_i;",
                "requirement_ids": target["requirement_ids"],
            }]})
            applied = apply_rtl_edits(project, edits)
            self.assertEqual(applied["edit_count"], 1)
            self.assertIn("assign data_o = data_i", generated.read_text())
            self.assertIn("+    assign data_o", paths["rtl_patch"].read_text())

            report = verify_rtl(project)
            self.assertEqual(report["integrity"]["status"], "passed")
            self.assertEqual(report["status"], "blocked")

            handoff = load_yaml(paths["rtl_handoff"])
            handoff["requirements"][0]["statement"] = "changed"
            dump_yaml(paths["rtl_handoff"], handoff)
            self.assertFalse(rtl_approval_is_valid(project)[0])

    def test_hierarchy_uses_named_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, evidence = _project_with_spec(Path(temporary))
            handoff = _complete_interface_handoff(project, evidence, mode="hierarchy")
            handoff["module_contracts"][0]["signals"] = [
                {"declaration": "logic done"}
            ]
            handoff["module_contracts"][0]["instances"] = [{
                "module": "image_worker",
                "name": "u_worker",
                "parameter_bindings": [{"name": "WIDTH", "expression": "DATA_WIDTH"}],
                "connections": [
                    {"name": "clk_i", "expression": "clk_i"},
                    {"name": "done_o", "expression": "done"},
                ],
            }]
            dump_yaml(project_paths(project)["rtl_handoff"], handoff)
            self.assertEqual(validate_rtl_handoff(project), [])
            approve_rtl(project, approver="unit-test")
            generate_rtl(project)
            text = (project_paths(project)["rtl_worktree"] / "rtl" / "image_ctrl.sv").read_text()
            self.assertIn(".WIDTH(DATA_WIDTH)", text)
            self.assertIn(".done_o(done)", text)

    def test_patch_rejects_stale_source_and_edit_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, evidence = _project_with_spec(Path(temporary))
            source = project / "top.sv"
            source.write_text(
                "module image_ctrl(input logic a, output logic y);\n"
                "  always_comb begin\n    y = a;\n  end\nendmodule\n",
                encoding="utf-8",
            )
            data = source.read_bytes()
            start = data.index(b"always_comb")
            end = data.index(b"\nendmodule")
            node = {
                "id": "syn-test-process",
                "kind": "process",
                "syntax_kind": "AlwaysBlock",
                "path": "top.sv",
                "start_byte": start,
                "end_byte": end,
                "line": 2,
                "column": 3,
                "file_sha256": file_digest(source),
                "text_sha256": hashlib.sha256(data[start:end]).hexdigest(),
                "editable": True,
            }
            paths = project_paths(project)
            write_jsonl(paths["rtl_source_index"], [node])
            handoff = _complete_interface_handoff(project, evidence, mode="patch")
            handoff["edit_targets"] = [{
                "node_id": node["id"],
                "kind": "process",
                "requirement_ids": ["RTL-FUNC-001"],
            }]
            dump_yaml(paths["rtl_handoff"], handoff)
            self.assertEqual(validate_rtl_handoff(project), [])
            approve_rtl(project, approver="unit-test")
            generate_rtl(project)
            generation = load_yaml(paths["rtl_generation"])
            target = generation["targets"][0]
            edits = project / "bad-edits.json"
            dump_json(edits, {"edits": [{
                "target_id": target["id"],
                "base_sha256": "0" * 64,
                "replacement_text": "always_comb y = ~a;",
                "requirement_ids": ["RTL-FUNC-001"],
            }]})
            with self.assertRaisesRegex(ValueError, "stale base_sha256"):
                apply_rtl_edits(project, edits)

            source.write_text(source.read_text() + "// changed\n", encoding="utf-8")
            self.assertFalse(rtl_approval_is_valid(project)[0])


if __name__ == "__main__":
    unittest.main()
