from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import (
    dump_yaml,
    file_digest,
    load_json,
    load_yaml,
    object_digest,
    project_paths,
)
from .query_evidence import all_evidence


# These eight categories are a deliberate modeling policy, not IP-specific
# design data. Their contents and evidence remain project-configurable.
CONTRACT_CATEGORIES = [
    ("functional_intent", "功能意图"),
    ("transaction_entry", "事务入口"),
    ("input_domain", "输入域"),
    ("algorithm_transform", "算法/变换"),
    ("data_flow", "数据流"),
    ("state_concurrency", "状态与并发"),
    ("boundaries_exceptions", "边界与异常"),
    ("observable_results", "可观察结果"),
]


def _validate_rtl_gate(paths: dict[str, Path], errors: list[str]) -> None:
    facts = load_json(paths["facts"] / "rtl.json")
    if not facts.get("design_rtl"):
        return
    if facts.get("schema_version") != 2:
        errors.append("RTL facts schema_version must be 2")
    if facts.get("status") != "ready":
        errors.append("RTL extraction requires a ready UHDM result")
    if facts.get("backend") != "uhdm":
        errors.append("RTL facts backend must be uhdm; no fallback is allowed")
    tools = facts.get("tools", {})
    for name in ("surelog", "uhdm_elab", "uhdm_lint", "uhdm_hier", "uhdm"):
        if tools.get(name, {}).get("status") != "passed":
            errors.append(f"RTL extraction gate {name} must pass")
    if not facts.get("files"):
        errors.append("RTL UHDM facts must contain at least one module definition")


def _rtl_traceability(paths: dict[str, Path]) -> list[dict[str, Any]]:
    facts = load_json(paths["facts"] / "rtl.json")
    modules = []
    seen = set()
    for file_facts in facts.get("files", []):
        for module in file_facts.get("modules", []):
            if module["name"] in seen:
                continue
            seen.add(module["name"])
            modules.append({"rtl_module": module["name"], "evidence_ids": [module["evidence"]]})
    return modules


def create_architecture_draft(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    manifest = load_yaml(paths["manifest"])
    categories = {}
    for key, title in CONTRACT_CATEGORIES:
        categories[key] = {
            "title": title,
            "status": "unresolved",
            "summary": "",
            "items": [],
            "open_questions": [],
        }
    architecture = {
        "schema_version": 3,
        "project": manifest["name"],
        "top": manifest.get("target_top", manifest.get("top")),
        "status": "draft",
        "categories": categories,
        "model": {
            "abstraction": "loosely-timed-tlm-2.0",
            "language": "c++17",
            "scc_policy": "scc-first-adapter-isolated",
        },
        "tlm_handoff": {
            "policy": {
                "abstraction": "loosely-timed-tlm-2.0",
                "transport": "b_transport",
                "forbidden_detail": [
                    "clock edges",
                    "RTL signals and handshakes",
                    "pipeline-register behavior",
                    "cycle-by-cycle scheduling",
                ],
            },
            "transaction_types": [],
            "functional_modules": [],
            "channels": [],
            "acceptance_scenarios": [],
        },
        "rtl_traceability": _rtl_traceability(paths),
    }
    if not paths["contracts"].exists():
        dump_yaml(paths["contracts"], architecture)
    if not paths["conflicts"].exists():
        dump_yaml(paths["conflicts"], {"schema_version": 1, "conflicts": []})
    return architecture


def validate_architecture(project_dir: Path) -> list[str]:
    paths = project_paths(project_dir)
    architecture = load_yaml(paths["contracts"])
    errors = []
    _validate_rtl_gate(paths, errors)
    if architecture.get("schema_version") != 3:
        errors.append("schema_version must be 3 for approval")
    categories = architecture.get("categories", {})
    evidence_ids = {item["id"] for item in all_evidence(project_dir)}
    for key, _ in CONTRACT_CATEGORIES:
        category = categories.get(key)
        if not isinstance(category, dict):
            errors.append(f"missing category: {key}")
            continue
        status = category.get("status")
        if status not in {"complete", "not_applicable"}:
            errors.append(f"{key}: status must be complete or not_applicable")
        if status == "complete" and not category.get("items"):
            errors.append(f"{key}: complete category requires at least one item")
        for index, item in enumerate(category.get("items", []), start=1):
            if not item.get("statement"):
                errors.append(f"{key}.items[{index}]: statement is required")
            if not item.get("evidence_ids"):
                errors.append(f"{key}.items[{index}]: evidence_ids is required")
            for evidence_id in item.get("evidence_ids", []):
                if evidence_id not in evidence_ids:
                    errors.append(
                        f"{key}.items[{index}]: unknown evidence ID {evidence_id}"
                    )
    _validate_tlm_handoff(architecture, evidence_ids, errors)
    _validate_contract_testbench(project_dir, architecture, errors)

    conflicts = load_yaml(paths["conflicts"]) if paths["conflicts"].exists() else {}
    unresolved = [
        item
        for item in conflicts.get("conflicts", [])
        if item.get("status", "open") != "resolved"
    ]
    if unresolved:
        errors.append(f"{len(unresolved)} unresolved evidence conflict(s)")
    return errors


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_evidence_ids(
    values: Any, evidence_ids: set[str], path: str, errors: list[str]
) -> None:
    if not isinstance(values, list) or not values:
        errors.append(f"{path}: evidence_ids is required")
        return
    for evidence_id in values:
        if evidence_id not in evidence_ids:
            errors.append(f"{path}: unknown evidence ID {evidence_id}")


def _validate_tlm_handoff(
    architecture: dict[str, Any], evidence_ids: set[str], errors: list[str]
) -> None:
    handoff = architecture.get("tlm_handoff")
    if not isinstance(handoff, dict):
        errors.append("tlm_handoff is required")
        return
    policy = handoff.get("policy")
    if not isinstance(policy, dict):
        errors.append("tlm_handoff.policy is required")
    else:
        if policy.get("abstraction") != "loosely-timed-tlm-2.0":
            errors.append("tlm_handoff.policy.abstraction must be loosely-timed-tlm-2.0")
        if policy.get("transport") != "b_transport":
            errors.append("tlm_handoff.policy.transport must be b_transport")
        forbidden = policy.get("forbidden_detail")
        if not isinstance(forbidden, list) or not forbidden:
            errors.append("tlm_handoff.policy.forbidden_detail is required")

    transactions = handoff.get("transaction_types")
    if not isinstance(transactions, list) or not transactions:
        errors.append("tlm_handoff.transaction_types must not be empty")
        transactions = []
    transaction_names: set[str] = set()
    for index, transaction in enumerate(transactions, start=1):
        path = f"tlm_handoff.transaction_types[{index}]"
        if not isinstance(transaction, dict) or not _non_empty_text(transaction.get("name")):
            errors.append(f"{path}: name is required")
            continue
        name = transaction["name"]
        if name in transaction_names:
            errors.append(f"{path}: duplicate transaction name {name}")
        transaction_names.add(name)
        fields = transaction.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(f"{path}: fields must not be empty")
        else:
            for field_index, field in enumerate(fields, start=1):
                field_path = f"{path}.fields[{field_index}]"
                if not isinstance(field, dict) or not _non_empty_text(field.get("name")):
                    errors.append(f"{field_path}: name is required")
                if not isinstance(field, dict) or not _non_empty_text(field.get("type")):
                    errors.append(f"{field_path}: type is required")
                if isinstance(field, dict) and "width_bits" in field and (
                    not isinstance(field["width_bits"], int) or field["width_bits"] <= 0
                ):
                    errors.append(f"{field_path}: width_bits must be a positive integer")
        response = transaction.get("response")
        if not isinstance(response, dict) or not _non_empty_text(response.get("success")):
            errors.append(f"{path}: response.success is required")

    modules = handoff.get("functional_modules")
    if not isinstance(modules, list) or not modules:
        errors.append("tlm_handoff.functional_modules must not be empty")
        modules = []
    module_endpoints: dict[str, dict[str, dict[str, Any]]] = {}
    for index, module in enumerate(modules, start=1):
        path = f"tlm_handoff.functional_modules[{index}]"
        if not isinstance(module, dict) or not _non_empty_text(module.get("name")):
            errors.append(f"{path}: name is required")
            continue
        name = module["name"]
        if name in module_endpoints:
            errors.append(f"{path}: duplicate functional module name {name}")
        module_endpoints[name] = {}
        if not _non_empty_text(module.get("responsibility")):
            errors.append(f"{path}: responsibility is required")
        _validate_evidence_ids(module.get("evidence_ids"), evidence_ids, path, errors)
        endpoints = module.get("endpoints")
        if not isinstance(endpoints, list) or not endpoints:
            errors.append(f"{path}: endpoints must not be empty")
            endpoints = []
        for endpoint_index, endpoint in enumerate(endpoints, start=1):
            endpoint_path = f"{path}.endpoints[{endpoint_index}]"
            if not isinstance(endpoint, dict) or not _non_empty_text(endpoint.get("name")):
                errors.append(f"{endpoint_path}: name is required")
                continue
            endpoint_name = endpoint["name"]
            module_endpoints[name][endpoint_name] = endpoint
            if endpoint.get("direction") not in {"inbound", "outbound"}:
                errors.append(f"{endpoint_path}: direction must be inbound or outbound")
            if endpoint.get("transaction") not in transaction_names:
                errors.append(f"{endpoint_path}: transaction must name a transaction type")
        operations = module.get("operations")
        if not isinstance(operations, list) or not operations:
            errors.append(f"{path}: operations must not be empty")
        else:
            for operation_index, operation in enumerate(operations, start=1):
                operation_path = f"{path}.operations[{operation_index}]"
                if not isinstance(operation, dict):
                    errors.append(f"{operation_path}: must be a mapping")
                    continue
                for key in ("name", "trigger_endpoint", "effect", "completion"):
                    if not _non_empty_text(operation.get(key)):
                        errors.append(f"{operation_path}: {key} is required")
                if operation.get("trigger_endpoint") not in module_endpoints[name]:
                    errors.append(f"{operation_path}: trigger_endpoint must name a module endpoint")
                _validate_evidence_ids(operation.get("evidence_ids"), evidence_ids, operation_path, errors)
        state = module.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("states"), list) or not state["states"]:
            errors.append(f"{path}: state.states must not be empty")
        elif state.get("initial") not in state["states"]:
            errors.append(f"{path}: state.initial must name a declared state")
        if not isinstance(state, dict) or not _non_empty_text(state.get("concurrency")):
            errors.append(f"{path}: state.concurrency is required")
        timing = module.get("timing")
        if not isinstance(timing, dict) or not isinstance(timing.get("service_latency_ns"), int) or timing["service_latency_ns"] < 0:
            errors.append(f"{path}: timing.service_latency_ns must be a non-negative integer")
        if not _non_empty_text(module.get("error_behavior")):
            errors.append(f"{path}: error_behavior is required")
        if not isinstance(module.get("observables"), list) or not module["observables"]:
            errors.append(f"{path}: observables must not be empty")

    channels = handoff.get("channels")
    if not isinstance(channels, list):
        errors.append("tlm_handoff.channels must be a list")
        channels = []
    for index, channel in enumerate(channels, start=1):
        path = f"tlm_handoff.channels[{index}]"
        if not isinstance(channel, dict):
            errors.append(f"{path}: must be a mapping")
            continue
        for key in ("name", "transaction", "ordering", "ownership", "backpressure", "completion"):
            if not _non_empty_text(channel.get(key)):
                errors.append(f"{path}: {key} is required")
        if channel.get("transaction") not in transaction_names:
            errors.append(f"{path}: transaction must name a transaction type")
        for side, direction in (("from", "outbound"), ("to", "inbound")):
            endpoint = channel.get(side)
            if not isinstance(endpoint, dict):
                errors.append(f"{path}.{side}: module and endpoint are required")
                continue
            module = endpoint.get("module")
            name = endpoint.get("endpoint")
            known = module_endpoints.get(module, {}).get(name)
            if known is None:
                errors.append(f"{path}.{side}: unknown functional module endpoint")
            elif known.get("direction") != direction:
                errors.append(f"{path}.{side}: endpoint direction must be {direction}")
            elif known.get("transaction") != channel.get("transaction"):
                errors.append(f"{path}.{side}: endpoint transaction must match channel")

    scenarios = handoff.get("acceptance_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("tlm_handoff.acceptance_scenarios must not be empty")
    else:
        for index, scenario in enumerate(scenarios, start=1):
            path = f"tlm_handoff.acceptance_scenarios[{index}]"
            if not isinstance(scenario, dict):
                errors.append(f"{path}: must be a mapping")
                continue
            for key in ("id", "name", "given", "when", "then"):
                if not _non_empty_text(scenario.get(key)):
                    errors.append(f"{path}: {key} is required")
            test_ids = scenario.get("test_ids")
            if not isinstance(test_ids, list) or not test_ids:
                errors.append(f"{path}: test_ids must not be empty")
            _validate_evidence_ids(scenario.get("evidence_ids"), evidence_ids, path, errors)


def _safe_contract_path(root: Path, value: Any) -> Path | None:
    if not _non_empty_text(value):
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _validate_contract_testbench(
    project_dir: Path, architecture: dict[str, Any], errors: list[str]
) -> None:
    paths = project_paths(project_dir)
    manifest_path = paths["contract_test_manifest"]
    if not manifest_path.is_file():
        errors.append("contract testbench/testbench.yaml is required")
        return
    try:
        manifest = load_yaml(manifest_path)
    except (ValueError, FileNotFoundError) as exc:
        errors.append(f"contract testbench manifest is invalid: {exc}")
        return
    if manifest.get("schema_version") != 1:
        errors.append("contract testbench schema_version must be 1")
    root = paths["contract_testbench"]
    headers = manifest.get("public_headers")
    if not isinstance(headers, list) or not headers:
        errors.append("contract testbench public_headers must not be empty")
        headers = []
    for index, value in enumerate(headers, start=1):
        path = _safe_contract_path(root, value)
        if path is None or not path.is_file():
            errors.append(f"contract testbench public_headers[{index}] is invalid or missing")

    scenarios = architecture.get("tlm_handoff", {}).get("acceptance_scenarios", [])
    scenario_tests = {
        scenario.get("id"): set(scenario.get("test_ids", []))
        for scenario in scenarios
        if isinstance(scenario, dict) and _non_empty_text(scenario.get("id"))
    }
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("contract testbench tests must not be empty")
        tests = []
    seen: set[str] = set()
    manifest_coverage: dict[str, set[str]] = {}
    for index, test in enumerate(tests, start=1):
        prefix = f"contract testbench tests[{index}]"
        if not isinstance(test, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        test_id = test.get("id")
        if not _non_empty_text(test_id):
            errors.append(f"{prefix}.id is required")
            continue
        if test_id in seen:
            errors.append(f"{prefix}.id duplicates {test_id}")
        seen.add(test_id)
        source = _safe_contract_path(root, test.get("source"))
        if source is None or not source.is_file() or source.suffix not in {".cc", ".cpp", ".cxx"}:
            errors.append(f"{prefix}.source is invalid or missing")
        timeout = test.get("timeout_seconds", 30)
        if not isinstance(timeout, int) or timeout <= 0:
            errors.append(f"{prefix}.timeout_seconds must be a positive integer")
        scenario_ids = test.get("scenario_ids")
        if not isinstance(scenario_ids, list) or not scenario_ids:
            errors.append(f"{prefix}.scenario_ids must not be empty")
            continue
        for scenario_id in scenario_ids:
            if scenario_id not in scenario_tests:
                errors.append(f"{prefix}: unknown acceptance scenario {scenario_id}")
            manifest_coverage.setdefault(scenario_id, set()).add(test_id)
    for scenario_id, declared_tests in scenario_tests.items():
        actual = manifest_coverage.get(scenario_id, set())
        if not declared_tests:
            continue
        if declared_tests != actual:
            errors.append(
                f"acceptance scenario {scenario_id}: test_ids must exactly match testbench coverage"
            )


def _contract_testbench_payload(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    root = paths["contract_testbench"]
    if not root.is_dir():
        return {"files": []}
    return {
        "files": [
            {
                "path": str(path.relative_to(root)),
                "sha256": file_digest(path),
            }
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
    }


def approval_payload(project_dir: Path) -> dict[str, Any]:
    """Return all artifacts whose semantic change must invalidate approval."""
    paths = project_paths(project_dir)
    manifest = load_yaml(paths["manifest"])
    architecture = load_yaml(paths["contracts"])
    conflicts = load_yaml(paths["conflicts"])
    facts = {}
    for name in ("documents", "registers", "rtl", "summary"):
        facts[name] = load_json(paths["facts"] / f"{name}.json")
    return {
        "manifest": manifest,
        "facts": facts,
        "evidence": all_evidence(project_dir),
        "architecture": architecture,
        "conflicts": conflicts,
        "contract_testbench": _contract_testbench_payload(project_dir),
    }


def approve(project_dir: Path, *, approver: str) -> dict[str, Any]:
    errors = validate_architecture(project_dir)
    if errors:
        raise ValueError("architecture cannot be approved:\n- " + "\n- ".join(errors))
    paths = project_paths(project_dir)
    payload = approval_payload(project_dir)
    approval = {
        "schema_version": 2,
        "status": "approved",
        "approver": approver,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": object_digest(payload),
    }
    dump_yaml(paths["approval"], approval)
    return approval


def approval_is_valid(project_dir: Path) -> tuple[bool, str]:
    paths = project_paths(project_dir)
    if not paths["approval"].exists():
        return False, "approval.yaml is missing"
    approval = load_yaml(paths["approval"])
    expected = object_digest(approval_payload(project_dir))
    if approval.get("status") != "approved":
        return False, "approval status is not approved"
    if approval.get("content_sha256") != expected:
        return False, "approval is stale because inputs, facts, or contracts changed"
    validation_errors = validate_architecture(project_dir)
    if validation_errors:
        return (
            False,
            "approval is invalid because current architecture gates fail: "
            + validation_errors[0],
        )
    return True, "approval is valid"


def status(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    result: dict[str, Any] = {
        "manifest": paths["manifest"].exists(),
        "facts": (paths["facts"] / "summary.json").exists(),
        "contracts": paths["contracts"].exists(),
        "approval": False,
        "approval_reason": "not checked",
        "model": (paths["model"] / "CMakeLists.txt").exists(),
        "verification": paths["verification"].exists(),
    }
    if result["facts"]:
        summary = load_json(paths["facts"] / "summary.json")
        result["rtl_status"] = summary.get("rtl_status", "unknown")
    if result["contracts"] and result["facts"]:
        result["contract_errors"] = validate_architecture(project_dir)
    if paths["approval"].exists():
        valid, reason = approval_is_valid(project_dir)
        result["approval"] = valid
        result["approval_reason"] = reason
    return result
