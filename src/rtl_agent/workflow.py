from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tlm_agent.graph.schema import read_jsonl
from tlm_agent.io import (
    dump_yaml,
    file_digest,
    load_json,
    load_yaml,
    object_digest,
    project_paths,
)

from .common import manifest_and_sources, safe_relative_path


RTL_MODES = frozenset({"interface", "hierarchy", "patch"})
RTL_LANGUAGE_STANDARDS = frozenset({"1800-2017", "1800-2023"})
EDIT_KINDS = frozenset({"process", "continuous_assign", "instance"})


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evidence_ids(paths: dict[str, Path]) -> set[str]:
    values = {
        item["id"]
        for item in read_jsonl(paths["graph_entities"])
        if item.get("source_refs")
    }
    values.update(
        item["id"]
        for item in read_jsonl(paths["graph"] / "text_units.jsonl")
        if item.get("source_path") and item.get("source_digest")
    )
    return values


def _module_evidence(paths: dict[str, Path], top: str) -> list[str]:
    return [
        item["id"]
        for item in read_jsonl(paths["graph_entities"])
        if item.get("type") == "Module" and item.get("name") == top
        and item.get("source_refs")
    ][:1]


def create_rtl_handoff_draft(
    project_dir: Path, *, mode: str = "interface", reset: bool = False
) -> dict[str, Any]:
    """创建不猜测接口或行为的 RTL handoff 草案。"""
    if mode not in RTL_MODES:
        raise ValueError(f"unsupported RTL mode: {mode}")
    paths = project_paths(project_dir)
    manifest = load_yaml(paths["manifest"])
    top = manifest.get("target_top", manifest.get("top"))
    evidence = _module_evidence(paths, top)
    handoff = {
        "schema_version": 1,
        "project": manifest["name"],
        "status": "draft",
        "policy": {
            "mode": mode,
            "language_standard": "1800-2017",
            "review_gate": "optional",
            "unsupported": [
                "complete-project reverse printing",
                "macro-expansion edits without a single writable source span",
                "package/class/interface/function/task/generate rewrites",
            ],
        },
        "target": {"top": top, "evidence_ids": evidence},
        "module_contracts": [],
        "requirements": [],
        "edit_targets": [],
        "structure_expectations": {
            "default": "preserve" if mode == "patch" else "declared-only",
            "allowed_deltas": [],
        },
        "acceptance_scenarios": [],
        "verification": {
            "lint": {"command": []},
            "compile": {"command": []},
            "simulation": {"tests": []},
        },
    }
    if reset or not paths["rtl_handoff"].exists():
        dump_yaml(paths["rtl_handoff"], handoff)
    if not paths["rtl_conflicts"].exists():
        dump_yaml(paths["rtl_conflicts"], {"schema_version": 1, "conflicts": []})
    return handoff


def _validate_evidence(
    values: Any, known: set[str], prefix: str, errors: list[str]
) -> None:
    if not isinstance(values, list) or not values:
        errors.append(f"{prefix}.evidence_ids must not be empty")
        return
    for value in values:
        if value not in known:
            errors.append(f"{prefix}: unknown evidence ID {value}")


def _validate_argv(value: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not all(_text(item) for item in value):
        errors.append(f"{prefix} must be a list of non-empty argv strings")


def validate_rtl_handoff(project_dir: Path) -> list[str]:
    paths = project_paths(project_dir)
    errors: list[str] = []
    if not paths["graph_manifest"].is_file():
        return ["canonical graph is missing; rerun extract"]
    graph = load_json(paths["graph_manifest"])
    if graph.get("status") != "ready" or graph.get("validation", {}).get("errors"):
        errors.append("canonical graph must be ready and valid")
    if not paths["rtl_handoff"].is_file():
        return [*errors, "rtl-handoff.yaml is missing; run architect"]
    handoff = load_yaml(paths["rtl_handoff"])
    if handoff.get("schema_version") != 1:
        errors.append("rtl_handoff.schema_version must be 1")
    if handoff.get("status") != "complete":
        errors.append("rtl_handoff.status must be complete")
    policy = handoff.get("policy", {})
    mode = policy.get("mode") if isinstance(policy, dict) else None
    if mode not in RTL_MODES:
        errors.append("rtl_handoff.policy.mode must be interface, hierarchy, or patch")
    if policy.get("language_standard") not in RTL_LANGUAGE_STANDARDS:
        errors.append("rtl_handoff.policy.language_standard is unsupported")
    if policy.get("review_gate", "optional") not in {"optional", "required"}:
        errors.append("rtl_handoff.policy.review_gate must be optional or required")
    if not isinstance(policy.get("unsupported"), list) or not policy["unsupported"]:
        errors.append("rtl_handoff.policy.unsupported must not be empty")

    known_evidence = _evidence_ids(paths)
    target = handoff.get("target")
    if not isinstance(target, dict) or not _text(target.get("top")):
        errors.append("rtl_handoff.target.top is required")
    elif target["top"] != graph.get("target_top"):
        errors.append("rtl_handoff.target.top must match canonical graph target_top")
    if isinstance(target, dict):
        _validate_evidence(target.get("evidence_ids"), known_evidence, "target", errors)

    modules = handoff.get("module_contracts")
    if not isinstance(modules, list) or not modules:
        errors.append("rtl_handoff.module_contracts must not be empty")
        modules = []
    module_names: set[str] = set()
    for index, module in enumerate(modules, 1):
        prefix = f"module_contracts[{index}]"
        if not isinstance(module, dict) or not _text(module.get("name")):
            errors.append(f"{prefix}.name is required")
            continue
        name = module["name"]
        if name in module_names:
            errors.append(f"{prefix}.name duplicates {name}")
        module_names.add(name)
        _validate_evidence(module.get("evidence_ids"), known_evidence, prefix, errors)
        for key in ("imports", "parameters", "ports", "signals", "instances"):
            if not isinstance(module.get(key, []), list):
                errors.append(f"{prefix}.{key} must be a list")
        ports = module.get("ports", [])
        if not ports:
            errors.append(f"{prefix}.ports must not be empty")
        for item_index, item in enumerate([*module.get("parameters", []), *ports, *module.get("signals", [])], 1):
            if not isinstance(item, dict) or not _text(item.get("declaration")):
                errors.append(f"{prefix}.declarations[{item_index}].declaration is required")
        for instance_index, instance in enumerate(module.get("instances", []), 1):
            item_prefix = f"{prefix}.instances[{instance_index}]"
            if not isinstance(instance, dict):
                errors.append(f"{item_prefix} must be a mapping")
                continue
            for key in ("module", "name"):
                if not _text(instance.get(key)):
                    errors.append(f"{item_prefix}.{key} is required")
            for key in ("parameter_bindings", "connections"):
                if not isinstance(instance.get(key, []), list):
                    errors.append(f"{item_prefix}.{key} must be a list")
            for binding in [*instance.get("parameter_bindings", []), *instance.get("connections", [])]:
                if not isinstance(binding, dict) or not _text(binding.get("name")) or not _text(binding.get("expression")):
                    errors.append(f"{item_prefix} bindings require name and expression")
    if isinstance(target, dict) and _text(target.get("top")) and target["top"] not in module_names:
        errors.append("rtl_handoff.target.top must name a module_contract")

    requirements = handoff.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        errors.append("rtl_handoff.requirements must not be empty")
        requirements = []
    requirement_ids: set[str] = set()
    for index, requirement in enumerate(requirements, 1):
        prefix = f"requirements[{index}]"
        if not isinstance(requirement, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        identifier = requirement.get("id")
        if not _text(identifier) or not str(identifier).startswith("RTL-"):
            errors.append(f"{prefix}.id must start with RTL-")
        elif identifier in requirement_ids:
            errors.append(f"{prefix}.id duplicates {identifier}")
        else:
            requirement_ids.add(identifier)
        module_name = requirement.get("module", target.get("top") if isinstance(target, dict) else None)
        if module_name not in module_names:
            errors.append(f"{prefix}.module must name a module_contract")
        if not _text(requirement.get("statement")):
            errors.append(f"{prefix}.statement is required")
        _validate_evidence(requirement.get("evidence_ids"), known_evidence, prefix, errors)

    source_nodes = {
        item["id"]: item for item in read_jsonl(paths["rtl_source_index"])
    }
    edit_targets = handoff.get("edit_targets")
    if not isinstance(edit_targets, list):
        errors.append("rtl_handoff.edit_targets must be a list")
        edit_targets = []
    if mode == "patch" and not edit_targets:
        errors.append("patch mode requires at least one edit_target")
    if mode in {"interface", "hierarchy"} and edit_targets:
        errors.append(f"{mode} mode edit_targets must be empty; generated TODO regions are used")
    seen_targets: set[str] = set()
    for index, target_item in enumerate(edit_targets, 1):
        prefix = f"edit_targets[{index}]"
        if not isinstance(target_item, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        node_id = target_item.get("node_id")
        node = source_nodes.get(node_id)
        if node is None:
            errors.append(f"{prefix}.node_id is unknown")
            continue
        if node_id in seen_targets:
            errors.append(f"{prefix}.node_id duplicates {node_id}")
        seen_targets.add(node_id)
        if node.get("kind") not in EDIT_KINDS or not node.get("editable"):
            errors.append(f"{prefix}.node_id is not an editable MVP syntax kind")
        if target_item.get("kind") != node.get("kind"):
            errors.append(f"{prefix}.kind must match the source index")
        ids = target_item.get("requirement_ids")
        if not isinstance(ids, list) or not ids or any(item not in requirement_ids for item in ids):
            errors.append(f"{prefix}.requirement_ids must name known requirements")

    expectations = handoff.get("structure_expectations")
    if not isinstance(expectations, dict) or expectations.get("default") not in {"preserve", "declared-only"}:
        errors.append("structure_expectations.default is invalid")
    elif not isinstance(expectations.get("allowed_deltas"), list):
        errors.append("structure_expectations.allowed_deltas must be a list")

    scenarios = handoff.get("acceptance_scenarios")
    if not isinstance(scenarios, list):
        errors.append("acceptance_scenarios must be a list")
    else:
        for index, scenario in enumerate(scenarios, 1):
            prefix = f"acceptance_scenarios[{index}]"
            if not isinstance(scenario, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            for key in ("id", "given", "when", "then"):
                if not _text(scenario.get(key)):
                    errors.append(f"{prefix}.{key} is required")
            if not isinstance(scenario.get("test_ids", []), list):
                errors.append(f"{prefix}.test_ids must be a list")
            _validate_evidence(scenario.get("evidence_ids"), known_evidence, prefix, errors)

    verification = handoff.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification is required")
    else:
        for gate in ("lint", "compile"):
            item = verification.get(gate)
            if not isinstance(item, dict):
                errors.append(f"verification.{gate} must be a mapping")
            else:
                _validate_argv(item.get("command", []), f"verification.{gate}.command", errors)
        simulation = verification.get("simulation", {})
        tests = simulation.get("tests", []) if isinstance(simulation, dict) else None
        if not isinstance(tests, list):
            errors.append("verification.simulation.tests must be a list")
        else:
            for index, test in enumerate(tests, 1):
                if not isinstance(test, dict) or not _text(test.get("id")):
                    errors.append(f"verification.simulation.tests[{index}].id is required")
                elif isinstance(test, dict):
                    _validate_argv(test.get("command", []), f"verification.simulation.tests[{index}].command", errors)

    conflicts = load_yaml(paths["rtl_conflicts"]) if paths["rtl_conflicts"].is_file() else {}
    unresolved = [
        item for item in conflicts.get("conflicts", [])
        if item.get("status", "open") != "resolved"
    ]
    if unresolved:
        errors.append(f"{len(unresolved)} unresolved RTL evidence conflict(s)")
    return errors


def _current_graph_payload(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    graph = load_json(paths["graph_manifest"])
    current_inputs = []
    for item in graph.get("inputs", []):
        value = Path(item["path"])
        resolved = value if value.is_absolute() else project_dir / value
        if not resolved.is_file():
            raise ValueError(f"graph input is missing: {item['path']}")
        current_inputs.append({"path": item["path"], "sha256": file_digest(resolved)})
    if current_inputs != graph.get("inputs"):
        raise ValueError("canonical graph is stale because an input changed")
    artifacts = {}
    for name, record in graph.get("artifacts", {}).items():
        path = paths["graph"] / safe_relative_path(name)
        if not path.is_file() or file_digest(path) != record.get("sha256"):
            raise ValueError(f"canonical graph artifact changed: {name}")
        artifacts[name] = record["sha256"]
    return {"manifest": graph, "current_inputs": current_inputs, "artifacts": artifacts}


def rtl_approval_payload(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    index_records = read_jsonl(paths["rtl_source_index"])
    indexed_files: dict[str, str] = {}
    for item in index_records:
        recorded = item.get("file_sha256")
        source_value = item.get("path")
        if not _text(source_value):
            raise ValueError("source index path is missing")
        existing = indexed_files.setdefault(str(source_value), recorded)
        if existing != recorded:
            raise ValueError(f"source index has conflicting file digests: {source_value}")
    current_source_files = []
    for value, recorded in sorted(indexed_files.items()):
        path = Path(value)
        source = path if path.is_absolute() else project_dir / path
        if not source.is_file() or file_digest(source) != recorded:
            raise ValueError(f"source index is stale because {value} changed")
        current_source_files.append({"path": value, "sha256": recorded})
    source_index = (
        {"sha256": file_digest(paths["rtl_source_index"])}
        if paths["rtl_source_index"].is_file() else {"sha256": None}
    )
    test_manifest = (
        load_yaml(paths["rtl_test_manifest"])
        if paths["rtl_test_manifest"].is_file() else None
    )
    return {
        "project_manifest": load_yaml(paths["manifest"]),
        "graph": _current_graph_payload(project_dir),
        "source_index": source_index,
        "current_source_files": current_source_files,
        "rtl_handoff": load_yaml(paths["rtl_handoff"]),
        "rtl_conflicts": load_yaml(paths["rtl_conflicts"]),
        "rtl_test_manifest": test_manifest,
    }


def approve_rtl(project_dir: Path, *, approver: str) -> dict[str, Any]:
    errors = validate_rtl_handoff(project_dir)
    if errors:
        raise ValueError("RTL handoff cannot be approved:\n- " + "\n- ".join(errors))
    approval = {
        "schema_version": 1,
        "status": "approved",
        "approver": approver,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": object_digest(rtl_approval_payload(project_dir)),
    }
    dump_yaml(project_paths(project_dir)["rtl_approval"], approval)
    return approval


def rtl_approval_is_valid(project_dir: Path) -> tuple[bool, str]:
    path = project_paths(project_dir)["rtl_approval"]
    if not path.is_file():
        return False, "rtl-approval.yaml is missing"
    approval = load_yaml(path)
    try:
        expected = object_digest(rtl_approval_payload(project_dir))
    except (FileNotFoundError, ValueError) as exc:
        return False, f"RTL approval is stale: {exc}"
    if approval.get("status") != "approved":
        return False, "RTL approval status is not approved"
    if approval.get("content_sha256") != expected:
        return False, "RTL approval is stale because inputs, graph, source index, or handoff changed"
    errors = validate_rtl_handoff(project_dir)
    if errors:
        return False, f"RTL approval gates fail: {errors[0]}"
    return True, "RTL approval is valid"


def _checkpoint_is_valid(project_dir: Path) -> tuple[bool, str]:
    path = project_paths(project_dir)["rtl_checkpoint"]
    if not path.is_file():
        return False, "rtl-checkpoint.yaml is missing"
    checkpoint = load_yaml(path)
    try:
        expected = object_digest(rtl_approval_payload(project_dir))
    except (FileNotFoundError, ValueError) as exc:
        return False, f"RTL checkpoint is stale: {exc}"
    if checkpoint.get("status") != "checkpointed":
        return False, "RTL checkpoint status is invalid"
    if checkpoint.get("content_sha256") != expected:
        return False, "RTL checkpoint is stale because inputs, graph, source index, or handoff changed"
    errors = validate_rtl_handoff(project_dir)
    if errors:
        return False, f"RTL checkpoint gates fail: {errors[0]}"
    return True, "automatic RTL checkpoint is valid"


def rtl_gate_is_valid(project_dir: Path) -> tuple[bool, str]:
    """检查人工审批或自动 checkpoint，required 策略只接受人工审批。"""
    handoff_path = project_paths(project_dir)["rtl_handoff"]
    if not handoff_path.is_file():
        return False, "rtl-handoff.yaml is missing"
    handoff = load_yaml(handoff_path)
    review_gate = handoff.get("policy", {}).get("review_gate", "optional")
    approved, approval_reason = rtl_approval_is_valid(project_dir)
    if approved:
        return True, approval_reason
    if review_gate == "required":
        return False, f"named RTL approval is required: {approval_reason}"
    return _checkpoint_is_valid(project_dir)


def ensure_rtl_gate(project_dir: Path) -> tuple[bool, str]:
    """为 optional review 流程创建内容 checkpoint；不替代 required 审批。"""
    valid, reason = rtl_gate_is_valid(project_dir)
    if valid:
        return valid, reason
    paths = project_paths(project_dir)
    handoff = load_yaml(paths["rtl_handoff"])
    if handoff.get("policy", {}).get("review_gate", "optional") == "required":
        return False, reason
    errors = validate_rtl_handoff(project_dir)
    if errors:
        return False, "RTL checkpoint cannot be created: " + errors[0]
    checkpoint = {
        "schema_version": 1,
        "status": "checkpointed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": object_digest(rtl_approval_payload(project_dir)),
    }
    dump_yaml(paths["rtl_checkpoint"], checkpoint)
    return True, "automatic RTL checkpoint created"


def rtl_status(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    valid, reason = rtl_gate_is_valid(project_dir)
    approved, approval_reason = rtl_approval_is_valid(project_dir)
    return {
        "manifest": paths["manifest"].is_file(),
        "graph": paths["graph_manifest"].is_file(),
        "source_index": paths["rtl_source_index"].is_file(),
        "handoff": paths["rtl_handoff"].is_file(),
        "handoff_errors": validate_rtl_handoff(project_dir) if paths["rtl_handoff"].is_file() else [],
        "gate": valid,
        "gate_reason": reason,
        "named_approval": approved,
        "named_approval_reason": approval_reason,
        "checkpoint": paths["rtl_checkpoint"].is_file(),
        "generated": paths["rtl_generation"].is_file(),
        "verification": paths["rtl_verification"].is_file(),
    }
