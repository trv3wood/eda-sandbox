from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tlm_agent.cli import command_init
from tlm_agent.extractors import extract_project
from tlm_agent.graph.finalize import finalize_graph
from tlm_agent.graph.schema import entity, read_jsonl, relationship, write_jsonl
from tlm_agent.generator import generate_model
from tlm_agent.io import (
    dump_yaml,
    file_digest,
    load_json,
    load_yaml,
    object_digest,
    project_paths,
    resolve_inputs,
)
from tlm_agent.workflow import (
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
    def test_init_writes_spec_extraction_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            args = Args()
            args.project = str(project)
            args.name = "configured-ip"
            args.top = "configured_ip"
            args.rtl = []
            args.spec_llm_model = "test-model"
            args.spec_llm_base_url = "http://example.invalid/v1"
            args.spec_llm_base_url_env = "TEST_LLM_BASE_URL"
            args.spec_llm_api_key_env = "TEST_LLM_API_KEY"

            command_init(args)

            graph_config = load_yaml(project / "manifest.yaml")["graph"]
            self.assertEqual(
                graph_config["rtl_extraction"],
                {"backend": "vcs-vpi", "timeout_seconds": 1800},
            )
            config = graph_config["spec_extraction"]
            self.assertFalse(config["enabled"])
            self.assertEqual(config["provider"], "openai-compatible")
            self.assertEqual(config["model"], "test-model")
            self.assertEqual(config["base_url"], "http://example.invalid/v1")
            self.assertEqual(config["base_url_env"], "TEST_LLM_BASE_URL")
            self.assertEqual(config["api_key_env"], "TEST_LLM_API_KEY")
            self.assertEqual(config["batch_max_chars"], 24000)
            self.assertEqual(config["response_format"], "json_object")
            manifest = load_yaml(project / "manifest.yaml")
            self.assertEqual(manifest["eda_compile"]["filelists"], [])
            self.assertEqual(
                manifest["eda_compile"]["working_directory"], "."
            )

    def test_semantic_spec_extraction_is_optional_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "spec.md").write_text(
                "# DMA\n\nDMA transfers bytes.\n", encoding="utf-8"
            )
            args = Args()
            args.project = str(project)
            args.name = "functional-first-ip"
            args.top = "functional_first_ip"
            args.docx = ["spec.md"]
            args.rtl = []
            command_init(args)

            summary = extract_project(project)
            graph = load_json(project_paths(project)["graph_manifest"])

            self.assertEqual(summary["graph_status"], "ready")
            self.assertEqual(graph["producers"]["spec"]["status"], "skipped")
            self.assertEqual(
                graph["producers"]["spec"]["reason"],
                "semantic extraction disabled",
            )

            create_architecture_draft(project)
            text_unit_id = read_jsonl(
                project_paths(project)["graph"] / "text_units.jsonl"
            )[0]["id"]
            architecture = load_yaml(project_paths(project)["contracts"])
            architecture["categories"]["functional_intent"].update({
                "status": "complete",
                "items": [{
                    "statement": "DMA transfers bytes.",
                    "evidence_ids": [text_unit_id],
                }],
            })
            dump_yaml(project_paths(project)["contracts"], architecture)
            errors = validate_architecture(project)
            self.assertFalse(
                any(
                    f"unknown evidence ID {text_unit_id}" in error
                    for error in errors
                )
            )

    def test_approval_input_path_rebases_sources_in_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work_root = Path(temporary) / "workspace"
            source = work_root / "sources" / "ip" / "spec.md"
            source.parent.mkdir(parents=True)
            source.write_text("portable input\n", encoding="utf-8")
            project = work_root / "projects" / "ip-tlm"
            project.mkdir(parents=True)

            args = Args()
            args.project = str(project)
            args.name = "portable-ip"
            args.top = "portable_ip"
            args.docx = [str(source)]
            args.rtl = []
            command_init(args)
            extract_project(project)
            create_architecture_draft(project)

            paths = project_paths(project)
            graph_manifest = load_json(paths["graph_manifest"])
            graph_manifest["inputs"][0]["path"] = (
                "/host/workspace/sources/ip/spec.md"
            )
            from tlm_agent.io import dump_json
            dump_json(paths["graph_manifest"], graph_manifest)

            payload = approval_payload(project)
            self.assertEqual(
                payload["current_inputs"][0]["sha256"], file_digest(source)
            )

    def test_semantic_spec_extraction_can_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "spec.md").write_text(
                "# DMA\n\nDMA transfers bytes.\n", encoding="utf-8"
            )
            args = Args()
            args.project = str(project)
            args.name = "audited-ip"
            args.top = "audited_ip"
            args.docx = ["spec.md"]
            args.rtl = []
            command_init(args)
            manifest = load_yaml(project / "manifest.yaml")
            manifest["graph"]["spec_extraction"]["enabled"] = True
            dump_yaml(project / "manifest.yaml", manifest)

            extract_project(project, run_tools=False)
            graph = load_json(project_paths(project)["graph_manifest"])

            self.assertEqual(graph["status"], "pending")
            self.assertEqual(graph["producers"]["spec"]["status"], "pending")

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
        from tlm_agent.io import dump_json
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
            """#include \"packet_contract.hpp\"
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

struct TestInitiator : sc_core::sc_module {
    tlm_utils::simple_initiator_socket<TestInitiator> socket;
    explicit TestInitiator(sc_core::sc_module_name name)
        : sc_core::sc_module(name), socket(\"socket\") {}
};

struct TestTarget : sc_core::sc_module {
    tlm_utils::simple_target_socket<TestTarget> socket;
    explicit TestTarget(sc_core::sc_module_name name)
        : sc_core::sc_module(name), socket(\"socket\") {
        socket.register_b_transport(this, &TestTarget::b_transport);
    }
    void b_transport(tlm::tlm_generic_payload& payload, sc_core::sc_time&) {
        payload.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

int sc_main(int, char**) {
    TestInitiator initiator(\"initiator\");
    TestTarget target(\"target\");
    tlm::tlm_generic_payload payload;
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    initiator.socket.bind(target.socket);
    initiator.socket->b_transport(payload, delay);
    return PacketContract{1}.length == 1 ? 0 : 1;
}
""",
            encoding="utf-8",
        )
        dump_yaml(
            root / "testbench.yaml",
            {
                "schema_version": 2,
                "kind": "systemc_tlm",
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

            # A plain C++ unit test cannot satisfy a SystemC/TLM contract.
            test_source = paths["contract_testbench"] / "tests" / "packet_contract.cpp"
            systemc_source = test_source.read_text(encoding="utf-8")
            test_source.write_text("int main() { return 0; }\n", encoding="utf-8")
            errors = validate_architecture(project)
            self.assertTrue(any("SystemC/TLM" in error for error in errors))
            test_source.write_text(systemc_source, encoding="utf-8")
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
                "find_package(SystemCLanguage CONFIG QUIET)",
                (paths["model"] / "CMakeLists.txt").read_text(),
            )
            self.assertIn(
                "set(MODEL_CXX_STANDARD 14 CACHE STRING",
                (paths["model"] / "CMakeLists.txt").read_text(),
            )
            self.assertIn(
                "Set CMAKE_PREFIX_PATH or SYSTEMC_HOME.",
                (paths["model"] / "CMakeLists.txt").read_text(),
            )
            self.assertIn(
                "find_package(scc CONFIG QUIET)",
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
            from tlm_agent.io import dump_json
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
