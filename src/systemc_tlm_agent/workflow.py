from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import dump_yaml, load_json, load_yaml, object_digest, project_paths
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


def _rtl_modules(paths: dict[str, Path]) -> list[dict[str, Any]]:
    facts = load_json(paths["facts"] / "rtl.json")
    modules = []
    seen = set()
    for file_facts in facts.get("files", []):
        for module in file_facts.get("modules", []):
            if module["name"] in seen:
                continue
            seen.add(module["name"])
            modules.append(
                {
                    "name": module["name"],
                    "rtl_evidence": [module["evidence"]],
                    "responsibility": "unresolved",
                    "latency_ns": 1,
                }
            )
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
        "schema_version": 1,
        "project": manifest["name"],
        "top": manifest.get("target_top", manifest.get("top")),
        "status": "draft",
        "categories": categories,
        "model": {
            # Current generator defaults. They are persisted in the contract so
            # an Architect can review or change them before approval.
            "abstraction": "loosely-timed-tlm-2.0",
            "language": "c++17",
            "scc_policy": "scc-first-adapter-isolated",
            "modules": _rtl_modules(paths),
        },
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
    modules = architecture.get("model", {}).get("modules", [])
    if not modules:
        errors.append("model.modules must not be empty")

    conflicts = load_yaml(paths["conflicts"]) if paths["conflicts"].exists() else {}
    unresolved = [
        item
        for item in conflicts.get("conflicts", [])
        if item.get("status", "open") != "resolved"
    ]
    if unresolved:
        errors.append(f"{len(unresolved)} unresolved evidence conflict(s)")
    return errors


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
    }


def approve(project_dir: Path, *, approver: str) -> dict[str, Any]:
    errors = validate_architecture(project_dir)
    if errors:
        raise ValueError("architecture cannot be approved:\n- " + "\n- ".join(errors))
    paths = project_paths(project_dir)
    payload = approval_payload(project_dir)
    approval = {
        "schema_version": 1,
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
    if result["contracts"] and result["facts"]:
        result["contract_errors"] = validate_architecture(project_dir)
    if paths["approval"].exists():
        valid, reason = approval_is_valid(project_dir)
        result["approval"] = valid
        result["approval_reason"] = reason
    return result
