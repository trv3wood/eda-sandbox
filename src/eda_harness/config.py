"""轻量任务验证配置的读取和校验。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


CATEGORIES = frozenset({"syntax", "lint", "build", "test", "differential", "custom"})
CHECK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _inside(root: Path, value: str, field: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{field} must be relative")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} escapes the task root") from exc
    return resolved


def load_config(root: Path, path: Path) -> dict[str, Any]:
    """读取并规范化 harness.yaml。"""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("harness config must be a YAML mapping")
    if raw.get("schema_version") != 1:
        raise ValueError("harness schema_version must be 1")
    workspace_value = raw.get("workspace", ".")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise ValueError("workspace must be a non-empty relative path")
    workspace = _inside(root, workspace_value, "workspace")
    if not workspace.is_dir():
        raise FileNotFoundError(f"workspace does not exist: {workspace}")

    allowed = raw.get("allowed_changes")
    if not isinstance(allowed, list) or not allowed or not all(
        isinstance(item, str) and item and not Path(item).is_absolute()
        and ".." not in Path(item).parts for item in allowed
    ):
        raise ValueError("allowed_changes must be a non-empty list of safe globs")

    checks = raw.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("checks must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(checks, 1):
        prefix = f"checks[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} must be a mapping")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not CHECK_ID_PATTERN.fullmatch(identifier):
            raise ValueError(
                f"{prefix}.id must use letters, digits, dot, underscore, or dash"
            )
        if identifier in identifiers:
            raise ValueError(f"duplicate check id: {identifier}")
        identifiers.add(identifier)
        category = item.get("category", "custom")
        if category not in CATEGORIES:
            raise ValueError(f"{prefix}.category is invalid")
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(value, str) and value for value in command
        ):
            raise ValueError(f"{prefix}.command must be a non-empty argv list")
        cwd_value = item.get("cwd", ".")
        if not isinstance(cwd_value, str) or not cwd_value:
            raise ValueError(f"{prefix}.cwd must be a relative path")
        cwd = _inside(workspace, cwd_value, f"{prefix}.cwd")
        if not cwd.is_dir():
            raise FileNotFoundError(f"{prefix}.cwd does not exist: {cwd}")
        timeout = item.get("timeout_seconds", 1800)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError(f"{prefix}.timeout_seconds must be a positive integer")
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"{prefix}.required must be boolean")
        dependencies = item.get("depends_on", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) and value for value in dependencies
        ):
            raise ValueError(f"{prefix}.depends_on must be a list of check IDs")
        normalized.append({
            "id": identifier,
            "category": category,
            "command": command,
            "cwd": str(cwd.relative_to(workspace)),
            "timeout_seconds": timeout,
            "required": required,
            "depends_on": dependencies,
        })
    known: set[str] = set()
    for item in normalized:
        unknown = set(item["depends_on"]) - known
        if unknown:
            raise ValueError(
                f"check {item['id']} depends on unknown or later checks: {sorted(unknown)}"
            )
        known.add(item["id"])
    return {
        "schema_version": 1,
        "workspace": str(workspace.relative_to(root.resolve())),
        "allowed_changes": allowed,
        "checks": normalized,
    }
