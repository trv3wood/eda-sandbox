from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from systemc_tlm_agent.cli import command_init
from systemc_tlm_agent.extractors import _evidence, extract_project
from systemc_tlm_agent.generator import generate_model
from systemc_tlm_agent.io import (
    dump_json,
    dump_yaml,
    load_json,
    load_yaml,
    object_digest,
    project_paths,
)
from systemc_tlm_agent.workflow import (
    CONTRACT_CATEGORIES,
    approval_payload,
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
    def _publish_uhdm_fixture(project: Path, module_name: str) -> str:
        paths = project_paths(project)
        rtl = load_json(paths["facts"] / "rtl.json")
        source = Path(rtl["design_rtl"][0])
        evidence = _evidence(
            kind="rtl",
            path=source,
            project_dir=project,
            locator=f"line:1/module:{module_name}",
            text=f"UHDM module definition {module_name}",
            extractor="uhdm-python-vpi/1",
        )
        tools = {
            name: {"status": "passed"}
            for name in (
                "surelog",
                "uhdm_elab",
                "uhdm_lint",
                "uhdm_hier",
                "uhdm",
                "verilator",
                "yosys",
            )
        }
        rtl.update(
            {
                "schema_version": 2,
                "status": "ready",
                "backend": "uhdm",
                "files": [
                    {
                        "path": str(source),
                        "modules": [
                            {
                                "name": module_name,
                                "definition": f"work@{module_name}",
                                "line": 1,
                                "ports": [],
                                "parameters": [],
                                "instances": [],
                                "evidence": evidence.id,
                            }
                        ],
                    }
                ],
                "tools": tools,
            }
        )
        dump_json(paths["facts"] / "rtl.json", rtl)
        paths["evidence"].write_text(
            json.dumps(asdict(evidence), sort_keys=True) + "\n", encoding="utf-8"
        )
        return evidence.id

    @staticmethod
    def _write_contract_testbench(project: Path, scenario_id: str, test_id: str) -> None:
        root = project_paths(project)["contract_testbench"]
        (root / "include").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "include" / "packet_contract.hpp").write_text(
            "#pragma once\nstruct PacketContract { unsigned length; };\n",
            encoding="utf-8",
        )
        (root / "tests" / "packet_contract.cpp").write_text(
            "#include \"packet_contract.hpp\"\nint main() { return PacketContract{1}.length == 1 ? 0 : 1; }\n",
            encoding="utf-8",
        )
        dump_yaml(
            root / "testbench.yaml",
            {
                "schema_version": 1,
                "public_headers": ["include/packet_contract.hpp"],
                "tests": [{
                    "id": test_id,
                    "source": "tests/packet_contract.cpp",
                    "timeout_seconds": 10,
                    "scenario_ids": [scenario_id],
                }],
            },
        )

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
                    "id": "valid_packet",
                    "name": "valid packet completes",
                    "given": "A valid packet request.",
                    "when": "submit receives the request.",
                    "then": "A completion response is returned after the service latency.",
                    "evidence_ids": [evidence_id],
                    "test_ids": ["packet_contract"],
                }],
            }
        )

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
            for tool in ("surelog", "uhdm_elab", "uhdm_hier", "verilator", "yosys"):
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
            self.assertEqual(summary["rtl_file_count"], 8)
            self.assertEqual(summary["rtl_status"], "pending")
            evidence_id = self._publish_uhdm_fixture(project, "packet_engine_top")
            create_architecture_draft(project)
            self.assertTrue(validate_architecture(project))

            paths = project_paths(project)
            architecture = load_yaml(paths["contracts"])
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
            self._write_contract_testbench(project, "valid_packet", "packet_contract")
            dump_yaml(paths["contracts"], architecture)
            self.assertEqual(validate_architecture(project), [])

            approve(project, approver="unit-test")
            self.assertTrue(approval_is_valid(project)[0])
            generated = generate_model(project)
            self.assertEqual(generated["module_count"], 1)
            self.assertTrue((paths["model"] / "CMakeLists.txt").exists())
            self.assertTrue((paths["model"] / "implementation-handoff.yaml").exists())
            self.assertIn("/build/", (paths["model"] / ".gitignore").read_text())
            self.assertIn(
                "add_test(NAME contract::packet_contract",
                (paths["model"] / "CMakeLists.txt").read_text(),
            )
            self.assertIn(
                "simple_target_socket_optional<PacketServiceModel> submit",
                (paths["model"] / "include" / "packet_service.hpp").read_text(),
            )

            # Even a matching approval hash cannot bypass a newly introduced
            # architecture gate (for example, legacy facts without UHDM).
            rtl_facts = load_json(paths["facts"] / "rtl.json")
            rtl_facts["status"] = "pending"
            dump_json(paths["facts"] / "rtl.json", rtl_facts)
            approval = load_yaml(paths["approval"])
            approval["content_sha256"] = object_digest(approval_payload(project))
            dump_yaml(paths["approval"], approval)
            valid, reason = approval_is_valid(project)
            self.assertFalse(valid)
            self.assertIn("current architecture gates fail", reason)

            rtl_facts["status"] = "ready"
            dump_json(paths["facts"] / "rtl.json", rtl_facts)
            approve(project, approver="unit-test")
            architecture["categories"]["functional_intent"]["summary"] = "changed"
            dump_yaml(paths["contracts"], architecture)
            self.assertFalse(approval_is_valid(project)[0])
            with self.assertRaises(ValueError):
                generate_model(project)

            architecture["categories"]["functional_intent"]["summary"] = "fixture contract"
            dump_yaml(paths["contracts"], architecture)
            approve(project, approver="unit-test")
            test_source = paths["contract_testbench"] / "tests" / "packet_contract.cpp"
            test_source.write_text(test_source.read_text() + "// changed\n", encoding="utf-8")
            self.assertFalse(approval_is_valid(project)[0])

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
            self.assertIn("schema_version must be 3 for approval", validate_architecture(project))

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
            evidence_id = self._publish_uhdm_fixture(project, "handoff_gate")
            create_architecture_draft(project)
            paths = project_paths(project)
            architecture = load_yaml(paths["contracts"])
            for key, _ in CONTRACT_CATEGORIES:
                architecture["categories"][key].update(
                    status="complete",
                    items=[{"statement": "defined", "evidence_ids": [evidence_id]}],
                )
            self._complete_handoff(architecture, evidence_id)
            self._write_contract_testbench(project, "valid_packet", "packet_contract")
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

    def test_pending_rtl_blocks_architecture_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "top.sv").write_text("module top; endmodule\n")
            args = Args()
            args.project = str(project)
            args.name = "pending-uhdm"
            args.top = "top"
            args.rtl = ["top.sv"]
            command_init(args)
            extract_project(project, run_tools=False)
            create_architecture_draft(project)

            errors = validate_architecture(project)

            self.assertIn("RTL extraction requires a ready UHDM result", errors)
            self.assertIn(
                "RTL facts backend must be uhdm; no fallback is allowed", errors
            )


if __name__ == "__main__":
    unittest.main()
