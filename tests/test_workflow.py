from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from systemc_tlm_agent.cli import command_init
from systemc_tlm_agent.extractors import extract_project
from systemc_tlm_agent.graph_finalize import finalize_graph
from systemc_tlm_agent.graph_schema import entity, relationship, write_jsonl
from systemc_tlm_agent.generator import generate_model
from systemc_tlm_agent.io import (
    dump_yaml,
    file_digest,
    load_json,
    load_yaml,
    object_digest,
    project_paths,
    resolve_inputs,
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
        manifest = load_yaml(paths["manifest"])
        source = resolve_inputs(
            project,
            manifest["rtl"],
            directory_suffixes={".v", ".sv"},
        )[0]
        source_ref = {
            "source_path": str(source),
            "source_digest": file_digest(source),
            "locator": "line:1",
            "line": 1,
        }
        provenance = {
            "extractor": "uhdm-python-vpi-graph/1",
            "deterministic": True,
            "source_backed": True,
        }
        file_entity = entity(
            entity_type="File",
            name=source.name,
            properties={"path": str(source), "sha256": file_digest(source)},
            source_refs=[source_ref],
            provenance=provenance,
        )
        module = entity(
            entity_type="Module",
            name=module_name,
            properties={"definition": f"work@{module_name}"},
            source_refs=[source_ref],
            provenance=provenance,
        )
        instance = entity(
            entity_type="Instance",
            name=module_name,
            properties={
                "path": module_name,
                "definition": module_name,
                "is_top": True,
            },
            source_refs=[source_ref],
            provenance=provenance,
        )
        edges = [
            relationship(
                relation_type="OF",
                source_id=instance["id"],
                target_id=module["id"],
                source_refs=[source_ref],
                provenance=provenance,
            ),
            relationship(
                relation_type="LOCATED_IN",
                source_id=module["id"],
                target_id=file_entity["id"],
                source_refs=[source_ref],
                provenance=provenance,
            ),
            relationship(
                relation_type="LOCATED_IN",
                source_id=instance["id"],
                target_id=file_entity["id"],
                source_refs=[source_ref],
                provenance=provenance,
            ),
        ]
        write_jsonl(
            paths["graph"] / "rtl_entities.jsonl",
            [file_entity, module, instance],
        )
        write_jsonl(paths["graph"] / "rtl_relationships.jsonl", edges)
        manifest = load_json(paths["graph_manifest"])
        manifest["producers"]["rtl"] = {"status": "passed"}
        from systemc_tlm_agent.io import dump_json
        dump_json(paths["graph_manifest"], manifest)
        finalize_graph(project, structure=None, sources=[source])
        return module["id"]

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

            graph = load_json(project_paths(project)["graph_manifest"])
            self.assertEqual(graph["status"], "ready")
            self.assertEqual(graph["producers"]["rtl"]["status"], "skipped")

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
            # architecture gate (for example, a graph marked pending).
            graph_manifest = load_json(paths["graph_manifest"])
            graph_manifest["status"] = "pending"
            from systemc_tlm_agent.io import dump_json
            dump_json(paths["graph_manifest"], graph_manifest)
            approval = load_yaml(paths["approval"])
            approval["content_sha256"] = object_digest(approval_payload(project))
            dump_yaml(paths["approval"], approval)
            valid, reason = approval_is_valid(project)
            self.assertFalse(valid)
            self.assertIn("current architecture gates fail", reason)

            graph_manifest["status"] = "ready"
            dump_json(paths["graph_manifest"], graph_manifest)
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
            self.assertIn(
                "schema_version must be 4 for graph-backed approval",
                validate_architecture(project),
            )

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

            self.assertIn("canonical graph must be ready", errors)
            self.assertIn("RTL graph producer must pass or be explicitly skipped", errors)


if __name__ == "__main__":
    unittest.main()
