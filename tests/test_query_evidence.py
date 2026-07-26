from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from eda_query.core import query_bundle
from systemc_tlm_agent.cli import command_init
from systemc_tlm_agent.extractors import extract_project
from systemc_tlm_agent.io import dump_json, dump_yaml, load_yaml, project_paths
from systemc_tlm_agent.query_evidence import list_evidence, record_query_evidence
from systemc_tlm_agent.workflow import (
    CONTRACT_CATEGORIES,
    approval_is_valid,
    approve,
    create_architecture_draft,
)


class Args:
    backend = "local"
    docx: list[str] = []
    xlsx: list[str] = []
    rtl: list[str] = []


class QueryEvidenceTest(unittest.TestCase):
    bundle = Path(__file__).parent / "fixtures" / "eda_query"

    def _project(self, root: Path) -> Path:
        rtl = root / "top.sv"
        rtl.write_text("module packet_engine_top(input logic clk); endmodule\n")
        args = Args()
        args.project = str(root)
        args.name = "query-evidence"
        args.top = "packet_engine_top"
        args.rtl = ["top.sv"]
        command_init(args)
        extract_project(root, run_tools=False)
        create_architecture_draft(root)
        return root

    def test_record_is_idempotent_and_usable_by_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            result = query_bundle(
                self.bundle,
                backend="yosys",
                kind="ports",
                selectors={"module": "packet_engine_top"},
            )
            result_path = project / "query.json"
            dump_json(result_path, result)
            first = record_query_evidence(
                project, result_path, statement="The top has elaborated ports."
            )
            second = record_query_evidence(
                project, result_path, statement="The top has elaborated ports."
            )
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(second["status"], "existing")
            self.assertEqual(list_evidence(project)["query_count"], 1)

            paths = project_paths(project)
            architecture = load_yaml(paths["contracts"])
            for key, _ in CONTRACT_CATEGORIES:
                architecture["categories"][key].update(
                    status="complete",
                    items=[{
                        "statement": "query-backed contract",
                        "evidence_ids": [first["evidence"]["id"]],
                    }],
                )
            dump_yaml(paths["contracts"], architecture)
            approve(project, approver="test")
            self.assertTrue(approval_is_valid(project)[0])

            changed = query_bundle(self.bundle, backend="yosys", kind="modules")
            changed_path = project / "changed.json"
            dump_json(changed_path, changed)
            record_query_evidence(project, changed_path, statement="More EDA evidence.")
            self.assertFalse(approval_is_valid(project)[0])

    def test_rejects_tampering_and_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            result = query_bundle(self.bundle, backend="yosys", kind="modules")
            result["kind"] = "ports"
            path = project / "tampered.json"
            dump_json(path, result)
            with self.assertRaisesRegex(ValueError, "query_id"):
                record_query_evidence(project, path, statement="bad")

            copied_bundle = project / "bundle"
            shutil.copytree(self.bundle, copied_bundle)
            result = query_bundle(copied_bundle, backend="yosys", kind="modules")
            source_changed = project / "source-changed.json"
            dump_json(source_changed, result)
            yosys = copied_bundle / "tools" / "yosys.json"
            yosys.write_text(yosys.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source"):
                record_query_evidence(
                    project, source_changed, statement="stale source"
                )


if __name__ == "__main__":
    unittest.main()
