from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from systemc_tlm_agent.cli import command_init
from systemc_tlm_agent.extractors import extract_project
from systemc_tlm_agent.generator import generate_model
from systemc_tlm_agent.io import dump_yaml, load_json, load_yaml, project_paths
from systemc_tlm_agent.workflow import (
    CONTRACT_CATEGORIES,
    approval_is_valid,
    approve,
    create_architecture_draft,
    validate_architecture,
)


class Args:
    backend = "local"
    docx: list[str] = []
    xlsx: list[str] = []


class WorkflowTest(unittest.TestCase):
    def test_approval_gate_and_generation(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "packet_engine"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            rtl_dir = project / "rtl"
            rtl_dir.symlink_to((fixture / "rtl").resolve(), target_is_directory=True)
            args = Args()
            args.project = str(project)
            args.name = "packet-engine"
            args.top = "packet_engine_top"
            # RTL directories are searched recursively for both .v and .sv.
            args.rtl = ["rtl"]
            command_init(args)

            summary = extract_project(project, run_tools=False)
            self.assertEqual(summary["rtl_module_count"], 8)
            create_architecture_draft(project)
            self.assertEqual(len(validate_architecture(project)), 8)

            paths = project_paths(project)
            architecture = load_yaml(paths["contracts"])
            evidence_id = load_json(paths["facts"] / "rtl.json")["files"][0]["modules"][0][
                "evidence"
            ]
            for key, _ in CONTRACT_CATEGORIES:
                architecture["categories"][key].update(
                    {
                        "status": "complete",
                        "summary": "fixture contract",
                        "items": [
                            {
                                "statement": f"{key} is defined by the synthetic fixture",
                                "evidence_ids": [evidence_id],
                            }
                        ],
                    }
                )
            dump_yaml(paths["contracts"], architecture)
            self.assertEqual(validate_architecture(project), [])

            approve(project, approver="unit-test")
            self.assertTrue(approval_is_valid(project)[0])
            generated = generate_model(project)
            self.assertEqual(generated["module_count"], 7)
            self.assertTrue((paths["model"] / "CMakeLists.txt").exists())

            architecture["categories"]["functional_intent"]["summary"] = "changed"
            dump_yaml(paths["contracts"], architecture)
            self.assertFalse(approval_is_valid(project)[0])
            with self.assertRaises(ValueError):
                generate_model(project)


if __name__ == "__main__":
    unittest.main()
