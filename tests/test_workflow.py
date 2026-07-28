from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from systemc_tlm_agent.cli import command_init
from systemc_tlm_agent.extractors import extract_project, run_eda_tools
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
    @staticmethod
    def _complete_handoff(architecture: dict, evidence_id: str) -> None:
        architecture["tlm_handoff"].update(
            {
                "transaction_types": [{
                    "name": "packet_request",
                    "fields": [{"name": "length", "type": "unsigned", "width_bits": 16}],
                    "response": {"success": "completion", "errors": ["invalid_length"]},
                }],
                "functional_modules": [{
                    "name": "packet_service",
                    "responsibility": "Validate and complete packet requests.",
                    "evidence_ids": [evidence_id],
                    "endpoints": [{"name": "submit", "direction": "inbound", "transaction": "packet_request"}],
                    "operations": [{
                        "name": "process_packet",
                        "trigger_endpoint": "submit",
                        "effect": "Validate the packet request.",
                        "completion": "Return a completion response.",
                        "evidence_ids": [evidence_id],
                    }],
                    "state": {"states": ["idle", "active"], "initial": "idle", "concurrency": "One request at a time."},
                    "timing": {"service_latency_ns": 10},
                    "error_behavior": "Reject invalid lengths with an error response.",
                    "observables": ["completion response"],
                }],
                "channels": [],
                "acceptance_scenarios": [{
                    "name": "valid packet completes",
                    "given": "A valid packet request.",
                    "when": "submit receives the request.",
                    "then": "A completion response is returned after the service latency.",
                    "evidence_ids": [evidence_id],
                }],
            }
        )

    @patch("systemc_tlm_agent.extractors._run_tool")
    def test_eda_commands_support_current_verilator_and_spaced_paths(
        self, run_tool
    ) -> None:
        run_tool.return_value = {"status": "passed"}
        project = Path("/tmp/project")
        rtl = project / "Verilog Gen/design.sv"
        testbench = project / "Verilog Gen/design_test.sv"
        run_eda_tools(
            project_dir=project,
            rtl_files=[rtl],
            testbench_files=[testbench],
            top="TopModule",
            tools_dir=project / "tools",
        )
        commands = [call.args[0] for call in run_tool.call_args_list]
        self.assertIn(str(testbench), commands[0])
        self.assertIn("-elabuhdm", commands[0])
        self.assertEqual(commands[0][commands[0].index("-top") + 1], "TopModule")
        self.assertIn("--json-only", commands[1])
        self.assertNotIn("--xml-only", commands[1])
        self.assertNotIn(str(testbench), commands[1])
        self.assertIn(
            'read_verilog -sv "/tmp/project/Verilog Gen/design.sv"',
            commands[2][2],
        )
        self.assertNotIn(str(testbench), commands[2][2])

    @patch("systemc_tlm_agent.extractors._run_tool")
    def test_eda_tools_preserve_native_uhdm_database(self, run_tool) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            tools = project / "tools"
            rtl = project / "design.sv"
            rtl.write_text("module top; endmodule\n", encoding="utf-8")

            def execute(command, cwd, log):
                if command[0] == "surelog":
                    database = cwd / "slpp_all/surelog.uhdm"
                    database.parent.mkdir(parents=True)
                    database.write_bytes(b"native uhdm")
                return {"status": "passed", "returncode": 0}

            run_tool.side_effect = execute
            result = run_eda_tools(
                project_dir=project,
                rtl_files=[rtl],
                testbench_files=[],
                top="top",
                tools_dir=tools,
            )

            self.assertEqual(result["uhdm"]["status"], "passed")
            self.assertEqual(result["uhdm"]["database_size"], 11)
            self.assertTrue(
                Path(result["uhdm"]["database"]).is_file()
            )
            commands = [call.args[0] for call in run_tool.call_args_list]
            self.assertEqual(
                [command[0] for command in commands],
                ["surelog", "verilator", "yosys"],
            )
            self.assertFalse((tools / "uhdm.json").exists())

    def test_extract_allows_missing_rtl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            args = Args()
            args.project = str(project)
            args.name = "spec-only-ip"
            args.top = "spec_only_ip"
            args.rtl = []
            command_init(args)

            # Keep run_tools enabled to prove that absent RTL skips, rather
            # than invokes, all structural EDA integrations.
            summary = extract_project(project)
            self.assertFalse(summary["rtl_available"])
            self.assertEqual(summary["missing_inputs"], ["rtl"])

            rtl = load_json(project_paths(project)["facts"] / "rtl.json")
            self.assertEqual(rtl["files"], [])
            for tool in ("surelog", "verilator", "yosys"):
                self.assertEqual(rtl["tools"][tool]["status"], "skipped")
                self.assertEqual(
                    rtl["tools"][tool]["reason"], "no RTL inputs were provided"
                )

            create_architecture_draft(project)
            errors = validate_architecture(project)
            self.assertIn("tlm_handoff.functional_modules must not be empty", errors)

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
            self.assertTrue(validate_architecture(project))

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
            self._complete_handoff(architecture, evidence_id)
            dump_yaml(paths["contracts"], architecture)
            self.assertEqual(validate_architecture(project), [])

            approve(project, approver="unit-test")
            self.assertTrue(approval_is_valid(project)[0])
            generated = generate_model(project)
            self.assertEqual(generated["module_count"], 1)
            self.assertTrue((paths["model"] / "CMakeLists.txt").exists())
            self.assertTrue((paths["model"] / "implementation-handoff.yaml").exists())
            self.assertIn(
                "simple_target_socket_optional<PacketServiceModel> submit",
                (paths["model"] / "include" / "packet_service.hpp").read_text(),
            )

            architecture["categories"]["functional_intent"]["summary"] = "changed"
            dump_yaml(paths["contracts"], architecture)
            self.assertFalse(approval_is_valid(project)[0])
            with self.assertRaises(ValueError):
                generate_model(project)

    def test_v1_contract_cannot_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            args = Args()
            args.project = str(project)
            args.name = "handoff-gate"
            args.top = "handoff_gate"
            args.rtl = []
            command_init(args)
            extract_project(project, run_tools=False)
            create_architecture_draft(project)
            paths = project_paths(project)
            architecture = load_yaml(paths["contracts"])
            architecture["schema_version"] = 1
            dump_yaml(paths["contracts"], architecture)
            self.assertIn("schema_version must be 2 for approval", validate_architecture(project))

    def test_channel_must_resolve_tlm_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "top.sv").write_text("module handoff_gate(); endmodule\n")
            args = Args()
            args.project = str(project)
            args.name = "handoff-channel"
            args.top = "handoff_gate"
            args.rtl = ["top.sv"]
            command_init(args)
            extract_project(project, run_tools=False)
            create_architecture_draft(project)
            paths = project_paths(project)
            architecture = load_yaml(paths["contracts"])
            evidence_id = load_json(paths["facts"] / "rtl.json")["files"][0]["modules"][0]["evidence"]
            for key, _ in CONTRACT_CATEGORIES:
                architecture["categories"][key].update(
                    status="complete",
                    items=[{"statement": "defined", "evidence_ids": [evidence_id]}],
                )
            self._complete_handoff(architecture, evidence_id)
            architecture["tlm_handoff"]["channels"] = [{
                "name": "bad_channel",
                "from": {"module": "packet_service", "endpoint": "missing"},
                "to": {"module": "packet_service", "endpoint": "submit"},
                "transaction": "packet_request",
                "ordering": "in order",
                "ownership": "sender retains until completion",
                "backpressure": "not applicable",
                "completion": "response",
            }]
            dump_yaml(paths["contracts"], architecture)
            self.assertIn(
                "tlm_handoff.channels[1].from: unknown functional module endpoint",
                validate_architecture(project),
            )


if __name__ == "__main__":
    unittest.main()
