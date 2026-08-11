"""轻量任务验证配置的读取和校验。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


CATEGORIES = frozenset({"syntax", "lint", "build", "test", "differential", "custom"})
CHECK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CYCLE_COMMAND_ROLES = (
    "reference_build",
    "model_build",
    "model_test",
    "stimulus",
    "reference_run",
    "model_run",
)
CYCLE_PLACEHOLDERS = frozenset({
    "{run_dir}", "{seed}", "{cycles}", "{stimulus}", "{trace}",
})
CYCLE_REQUIRED_PLACEHOLDERS = {
    "reference_build": {"{run_dir}"},
    "model_build": {"{run_dir}"},
    "model_test": {"{run_dir}"},
    "stimulus": {"{seed}", "{cycles}", "{stimulus}"},
    "reference_run": {"{run_dir}", "{stimulus}", "{trace}"},
    "model_run": {"{run_dir}", "{stimulus}", "{trace}"},
}
FORBIDDEN_MODEL_COMMANDS = re.compile(
    r"(?:^|[/_-])(?:verilator|verilated|vcs|xrun|vsim|qrun|iverilog)(?:$|[/_.-])",
    re.IGNORECASE,
)


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
        "checks": normalized,
    }


def _cycle_command(workspace: Path, role: str, raw: Any) -> dict[str, Any]:
    """校验 cycle harness 的一个固定角色命令。"""
    if not isinstance(raw, dict):
        raise ValueError(f"commands.{role} must be a mapping")
    command = raw.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(value, str) and value for value in command
    ):
        raise ValueError(f"commands.{role}.command must be a non-empty argv list")
    present: set[str] = set()
    for value in command:
        placeholders = set(re.findall(r"\{[^{}]+\}", value))
        present.update(placeholders)
        unknown = placeholders - CYCLE_PLACEHOLDERS
        if unknown:
            raise ValueError(
                f"commands.{role}.command uses unknown placeholders: {sorted(unknown)}"
            )
    missing = CYCLE_REQUIRED_PLACEHOLDERS[role] - present
    if missing:
        raise ValueError(
            f"commands.{role}.command is missing placeholders: {sorted(missing)}"
        )
    if role in {"model_build", "model_test", "model_run"} and any(
        FORBIDDEN_MODEL_COMMANDS.search(value) for value in command
    ):
        raise ValueError(f"commands.{role} references a forbidden RTL simulator")
    cwd_value = raw.get("cwd", ".")
    if not isinstance(cwd_value, str) or not cwd_value:
        raise ValueError(f"commands.{role}.cwd must be a relative path")
    cwd = _inside(workspace, cwd_value, f"commands.{role}.cwd")
    if not cwd.is_dir():
        raise FileNotFoundError(f"commands.{role}.cwd does not exist: {cwd}")
    timeout = raw.get("timeout_seconds", 1800)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError(f"commands.{role}.timeout_seconds must be a positive integer")
    return {
        "command": command,
        "cwd": str(cwd.relative_to(workspace)),
        "timeout_seconds": timeout,
    }


def load_cycle_config(root: Path, path: Path) -> dict[str, Any]:
    """读取并校验 cycle-harness.yaml。"""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("cycle harness config must be a YAML mapping")
    if raw.get("schema_version") != 1:
        raise ValueError("cycle harness schema_version must be 1")

    workspace_value = raw.get("workspace", ".")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise ValueError("workspace must be a non-empty relative path")
    workspace = _inside(root, workspace_value, "workspace")
    if not workspace.is_dir():
        raise FileNotFoundError(f"workspace does not exist: {workspace}")

    def relative_file(field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a non-empty relative path")
        resolved = _inside(workspace, value, field)
        if not resolved.is_file():
            raise FileNotFoundError(f"{field} does not exist: {resolved}")
        return str(resolved.relative_to(workspace))

    evidence = relative_file("evidence")
    source_manifest = relative_file("source_manifest")
    model_sources_raw = raw.get("model_sources")
    if not isinstance(model_sources_raw, list) or not model_sources_raw:
        raise ValueError("model_sources must be a non-empty list")
    model_sources: list[str] = []
    for index, value in enumerate(model_sources_raw, 1):
        if not isinstance(value, str) or not value:
            raise ValueError(f"model_sources[{index}] must be a relative path")
        resolved = _inside(workspace, value, f"model_sources[{index}]")
        if not resolved.is_file():
            raise FileNotFoundError(f"model source does not exist: {resolved}")
        model_sources.append(str(resolved.relative_to(workspace)))
    if len(set(model_sources)) != len(model_sources):
        raise ValueError("model_sources must be unique")
    model_binary = raw.get("model_binary")
    if not isinstance(model_binary, str) or not model_binary.startswith("{run_dir}/"):
        raise ValueError("model_binary must be a path below {run_dir}")
    if set(re.findall(r"\{[^{}]+\}", model_binary)) != {"{run_dir}"}:
        raise ValueError("model_binary only supports the {run_dir} placeholder")
    binary_suffix = Path(model_binary.removeprefix("{run_dir}/"))
    if binary_suffix.is_absolute() or ".." in binary_suffix.parts:
        raise ValueError("model_binary must stay below {run_dir}")

    top = raw.get("top")
    if not isinstance(top, str) or not top:
        raise ValueError("top must be a non-empty string")
    for name in ("clock", "reset"):
        value = raw.get(name)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("name"), str)
            or not value["name"]
        ):
            raise ValueError(f"{name}.name must be a non-empty string")
    if raw["clock"].get("edge") not in {"rising", "falling"}:
        raise ValueError("clock.edge must be rising or falling")
    if raw["reset"].get("active") not in {"high", "low"}:
        raise ValueError("reset.active must be high or low")
    sample_phase = raw.get("sample_phase")
    if not isinstance(sample_phase, str) or not sample_phase:
        raise ValueError("sample_phase must be a non-empty string")

    observables_raw = raw.get("observables")
    if not isinstance(observables_raw, list) or not observables_raw:
        raise ValueError("observables must be a non-empty list")
    observables: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(observables_raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"observables[{index}] must be a mapping")
        name = item.get("name")
        width = item.get("width")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"observables[{index}].name must be unique and non-empty")
        if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
            raise ValueError(f"observables[{index}].width must be a positive integer")
        names.add(name)
        observables.append({"name": name, "width": width})

    directed = raw.get("directed")
    if not isinstance(directed, dict):
        raise ValueError("directed must be a mapping")
    directed_seed = directed.get("seed", 0)
    directed_cycles = directed.get("cycles")
    if (
        not isinstance(directed_seed, int)
        or isinstance(directed_seed, bool)
        or not 0 <= directed_seed < 2**63
    ):
        raise ValueError("directed.seed must be a non-negative 63-bit integer")
    if (
        not isinstance(directed_cycles, int)
        or isinstance(directed_cycles, bool)
        or directed_cycles <= 0
    ):
        raise ValueError("directed.cycles must be a positive integer")

    random_config = raw.get("random")
    if not isinstance(random_config, dict):
        raise ValueError("random must be a mapping")
    public_seeds = random_config.get("public_seeds")
    if not isinstance(public_seeds, list) or len(public_seeds) < 10 or not all(
        isinstance(seed, int)
        and not isinstance(seed, bool)
        and 0 <= seed < 2**63
        for seed in public_seeds
    ):
        raise ValueError(
            "random.public_seeds must contain at least 10 non-negative 63-bit integers"
        )
    if len(set(public_seeds)) != len(public_seeds):
        raise ValueError("random.public_seeds must be unique")
    cycles_per_seed = random_config.get("cycles_per_seed", 1000)
    if (
        not isinstance(cycles_per_seed, int)
        or isinstance(cycles_per_seed, bool)
        or cycles_per_seed < 1000
    ):
        raise ValueError("random.cycles_per_seed must be at least 1000")
    fresh_seed_count = random_config.get("fresh_seed_count", 10)
    if (
        not isinstance(fresh_seed_count, int)
        or isinstance(fresh_seed_count, bool)
        or fresh_seed_count < 10
    ):
        raise ValueError("random.fresh_seed_count must be at least 10")

    commands_raw = raw.get("commands")
    if not isinstance(commands_raw, dict):
        raise ValueError("commands must be a mapping")
    missing = set(CYCLE_COMMAND_ROLES) - set(commands_raw)
    extra = set(commands_raw) - set(CYCLE_COMMAND_ROLES)
    if missing or extra:
        raise ValueError(
            f"commands must define exactly {list(CYCLE_COMMAND_ROLES)}; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    commands = {
        role: _cycle_command(workspace, role, commands_raw[role])
        for role in CYCLE_COMMAND_ROLES
    }
    for role in ("model_test", "model_run"):
        if commands[role]["command"][0] != model_binary:
            raise ValueError(f"commands.{role} must execute model_binary directly")
    return {
        "schema_version": 1,
        "workspace": str(workspace.relative_to(root.resolve())),
        "evidence": evidence,
        "source_manifest": source_manifest,
        "model_sources": model_sources,
        "model_binary": model_binary,
        "top": top,
        "clock": {"name": raw["clock"]["name"], "edge": raw["clock"]["edge"]},
        "reset": {"name": raw["reset"]["name"], "active": raw["reset"]["active"]},
        "sample_phase": sample_phase,
        "observables": observables,
        "directed": {"seed": directed_seed, "cycles": directed_cycles},
        "random": {
            "public_seeds": public_seeds,
            "cycles_per_seed": cycles_per_seed,
            "fresh_seed_count": fresh_seed_count,
        },
        "commands": commands,
    }
