"""Cycle-accurate SystemC 的证据校验与 RTL 差分门禁。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from .state import STATE_DIR


LOCATION_PATTERN = re.compile(r"^(.+):(\d+)$")
FORBIDDEN_MODEL_PATTERNS = {
    "Verilator runtime": re.compile(r"\bverilated(?:\.h|_vcd|_fst)?\b", re.IGNORECASE),
    "reference trace": re.compile(r"reference[_-]?trace", re.IGNORECASE),
    "external process": re.compile(r"\b(?:system|popen|exec[lvpe]*)\s*\("),
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_location(workspace: Path, value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be path:line")
    match = LOCATION_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(f"{field} must be path:line")
    path = (workspace / match.group(1)).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"{field} escapes workspace") from exc
    if not path.is_file():
        raise FileNotFoundError(f"{field} does not exist: {path}")
    line = int(match.group(2))
    line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    if line <= 0 or line > line_count:
        raise ValueError(f"{field} line is outside file: {value}")


def validate_evidence(workspace: Path, path: Path, top: str) -> dict[str, Any]:
    """校验证据条目和所有文件引用。"""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("cycle evidence schema_version must be 1")
    if raw.get("top") != top:
        raise ValueError("cycle evidence top does not match cycle harness")
    semantics = raw.get("semantics")
    if not isinstance(semantics, list) or not semantics:
        raise ValueError("cycle evidence semantics must be a non-empty list")
    identifiers: set[str] = set()
    for index, item in enumerate(semantics, 1):
        prefix = f"semantics[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} must be a mapping")
        identifier = item.get("id")
        claim = item.get("claim")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError(f"{prefix}.id must be unique and non-empty")
        if not isinstance(claim, str) or not claim:
            raise ValueError(f"{prefix}.claim must be non-empty")
        identifiers.add(identifier)
        for field in ("rtl_locations", "systemc_locations"):
            locations = item.get(field)
            if not isinstance(locations, list) or not locations:
                raise ValueError(f"{prefix}.{field} must be a non-empty list")
            for location_index, location in enumerate(locations, 1):
                _validate_location(
                    workspace, location, f"{prefix}.{field}[{location_index}]"
                )
        evidence = item.get("tool_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{prefix}.tool_evidence must be a non-empty list")
        for evidence_index, entry in enumerate(evidence, 1):
            evidence_prefix = f"{prefix}.tool_evidence[{evidence_index}]"
            if not isinstance(entry, dict):
                raise ValueError(f"{evidence_prefix} must be a mapping")
            command = entry.get("command")
            observation = entry.get("observation")
            artifact = entry.get("artifact")
            if not isinstance(command, list) or not command or not all(
                isinstance(value, str) and value for value in command
            ):
                raise ValueError(f"{evidence_prefix}.command must be an argv list")
            if not isinstance(observation, str) or not observation:
                raise ValueError(f"{evidence_prefix}.observation must be non-empty")
            if not isinstance(artifact, str) or not artifact:
                raise ValueError(f"{evidence_prefix}.artifact must be a relative path")
            artifact_path = (workspace / artifact).resolve()
            try:
                artifact_path.relative_to(workspace)
            except ValueError as exc:
                raise ValueError(f"{evidence_prefix}.artifact escapes workspace") from exc
            if not artifact_path.is_file():
                raise FileNotFoundError(f"evidence artifact does not exist: {artifact_path}")
    return raw


def audit_model(workspace: Path, model_sources: list[str]) -> None:
    """拒绝最终模型中常见的 simulator/trace 逃逸路径。"""
    for relative in model_sources:
        path = workspace / relative
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in FORBIDDEN_MODEL_PATTERNS.items():
            if pattern.search(text):
                raise ValueError(f"model audit found forbidden {label} in {relative}")


def audit_model_binary(path: Path) -> dict[str, Any]:
    """检查最终可执行文件及其动态依赖。"""
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"model binary was not produced: {path}")
    reader = shutil.which("readelf") or shutil.which("objdump")
    if not reader:
        raise ValueError("readelf or objdump is required for model dependency audit")
    arguments = [reader, "-d", str(path)] if Path(reader).name == "readelf" else [
        reader, "-p", str(path),
    ]
    try:
        result = subprocess.run(
            arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot inspect model binary dependencies: {exc}") from exc
    dependency_text = result.stdout or ""
    if result.returncode != 0:
        raise ValueError(f"cannot inspect model binary dependencies: {dependency_text.strip()}")
    forbidden = re.search(
        r"\b(?:verilated|verilator|vpi|dpi|vcs|xrun|questa|modelsim)\b",
        dependency_text,
        re.IGNORECASE,
    )
    if forbidden:
        raise ValueError(
            f"model binary depends on forbidden simulator component: {forbidden.group(0)}"
        )
    return {"path": str(path), "sha256": _digest(path), "dependencies": dependency_text.splitlines()}


def _expand(command: list[str], values: dict[str, str]) -> list[str]:
    result: list[str] = []
    for argument in command:
        expanded = argument
        for placeholder, value in values.items():
            expanded = expanded.replace(placeholder, value)
        result.append(expanded)
    return result


def _run_command(
    role: str,
    spec: dict[str, Any],
    workspace: Path,
    log_path: Path,
    values: dict[str, str],
) -> dict[str, Any]:
    command = _expand(spec["command"], values)
    cwd = workspace / spec["cwd"]
    executable = command[0]
    if Path(executable).is_absolute():
        resolved = executable if os.access(executable, os.X_OK) else None
    elif "/" in executable:
        candidate = (cwd / executable).resolve()
        resolved = (
            str(candidate)
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    else:
        resolved = shutil.which(executable)
    base = {"id": role, "command": command, "cwd": spec["cwd"], "log": str(log_path)}
    if not resolved:
        log_path.write_text(f"tool is unavailable: {executable}\n", encoding="utf-8")
        return {**base, "status": "blocked", "reason": f"tool is unavailable: {executable}"}
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        log_path.write_text(f"cannot start command: {exc}\n", encoding="utf-8")
        return {**base, "status": "blocked", "reason": f"cannot start command: {exc}"}
    timed_out = False
    try:
        output, _ = process.communicate(timeout=spec["timeout_seconds"])
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
    log_path.write_text(output or "", encoding="utf-8", errors="replace")
    result = {
        **base,
        "duration_seconds": round(time.monotonic() - started, 6),
        "returncode": process.returncode,
    }
    if timed_out:
        return {**result, "status": "failed", "reason": "command timed out"}
    return {**result, "status": "passed" if process.returncode == 0 else "failed"}


def _load_trace(
    path: Path,
    observables: dict[str, int],
    sample_phase: str,
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"trace was not produced: {path}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if (
            not isinstance(record, dict)
            or isinstance(record.get("sample"), bool)
            or record.get("sample") != len(records)
        ):
            raise ValueError(f"trace sample must be contiguous at {path}:{line_number}")
        if record.get("phase") != sample_phase:
            raise ValueError(f"trace phase mismatch at {path}:{line_number}")
        signals = record.get("signals")
        if not isinstance(signals, dict) or set(signals) != set(observables):
            raise ValueError(f"trace signals mismatch at {path}:{line_number}")
        normalized: dict[str, str] = {}
        for name, width in observables.items():
            value = signals[name]
            if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-f]+", value):
                raise ValueError(f"{name} must be canonical lowercase hex at {path}:{line_number}")
            number = int(value, 16)
            if number >= 1 << width:
                raise ValueError(f"{name} exceeds declared width at {path}:{line_number}")
            digits = max(1, (width + 3) // 4)
            canonical = f"0x{number:0{digits}x}"
            if value != canonical:
                raise ValueError(f"{name} is not width-canonical at {path}:{line_number}")
            normalized[name] = canonical
        records.append({"sample": len(records), "phase": sample_phase, "signals": normalized})
    if not records:
        raise ValueError(f"trace is empty: {path}")
    return records


def compare_traces(
    reference: Path,
    model: Path,
    observables: dict[str, int],
    sample_phase: str,
    expected_samples: int | None = None,
) -> dict[str, Any]:
    """逐样点比较两份标准 JSONL trace。"""
    expected = _load_trace(reference, observables, sample_phase)
    actual = _load_trace(model, observables, sample_phase)
    if len(expected) != len(actual):
        raise ValueError(
            f"trace length mismatch: reference={len(expected)}, model={len(actual)}"
        )
    if expected_samples is not None and len(expected) != expected_samples:
        raise ValueError(
            f"trace sample count mismatch: expected={expected_samples}, actual={len(expected)}"
        )
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            mismatches = [
                name for name in observables
                if left["signals"][name] != right["signals"][name]
            ]
            raise ValueError(
                f"trace mismatch at sample {index}: signals={mismatches}, "
                f"reference={left['signals']}, model={right['signals']}"
            )
    return {"samples": len(expected), "reference_sha256": _digest(reference), "model_sha256": _digest(model)}


def verify_cycle(root: Path, *, config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    """执行证据、构建、定向和双批随机差分门禁。"""
    root = root.resolve()
    workspace = (root / config["workspace"]).resolve()
    state = root / STATE_DIR
    run_root = state / "cycle-runs" / f"{time.time_ns()}-{os.getpid()}"
    logs = run_root / "logs"
    logs.mkdir(parents=True)
    checks: list[dict[str, Any]] = []
    status = "passed"
    protected_paths = [
        config_path,
        workspace / config["evidence"],
        workspace / config["source_manifest"],
        *[workspace / relative for relative in config["model_sources"]],
    ]
    protected_hashes = {str(path): _digest(path) for path in protected_paths}

    try:
        evidence_path = workspace / config["evidence"]
        validate_evidence(workspace, evidence_path, config["top"])
        audit_model(workspace, config["model_sources"])
        checks.append({"id": "evidence-and-audit", "status": "passed"})
    except (FileNotFoundError, ValueError) as exc:
        checks.append({"id": "evidence-and-audit", "status": "failed", "reason": str(exc)})
        status = "failed"

    common = {
        "{run_dir}": str(run_root),
        "{seed}": "0",
        "{cycles}": "0",
        "{stimulus}": "",
        "{trace}": "",
    }
    if status == "passed":
        for role in ("reference_build", "model_build", "model_test"):
            result = _run_command(
                role, config["commands"][role], workspace,
                logs / f"{role}.log", common,
            )
            checks.append(result)
            if result["status"] != "passed":
                status = result["status"]
                break
            if role == "model_build":
                try:
                    binary_path = Path(
                        config["model_binary"].replace("{run_dir}", str(run_root))
                    )
                    binary_audit = audit_model_binary(binary_path)
                    checks.append({
                        "id": "model-binary-audit", "status": "passed", **binary_audit,
                    })
                except (FileNotFoundError, ValueError) as exc:
                    checks.append({
                        "id": "model-binary-audit", "status": "failed",
                        "reason": str(exc),
                    })
                    status = "failed"
                    break

    public_seeds = config["random"]["public_seeds"]
    used = {*public_seeds, config["directed"]["seed"]}
    fresh_seeds: list[int] = []
    while len(fresh_seeds) < config["random"]["fresh_seed_count"]:
        seed = secrets.randbits(63)
        if seed not in used:
            used.add(seed)
            fresh_seeds.append(seed)
    cases = [
        ("directed", config["directed"]["seed"], config["directed"]["cycles"]),
        *[("public-random", seed, config["random"]["cycles_per_seed"]) for seed in public_seeds],
        *[("fresh-random", seed, config["random"]["cycles_per_seed"]) for seed in fresh_seeds],
    ]
    case_reports: list[dict[str, Any]] = []
    observables = {item["name"]: item["width"] for item in config["observables"]}
    if status == "passed":
        for case_index, (kind, seed, cycles) in enumerate(cases):
            case_dir = run_root / f"case-{case_index:03d}-{kind}-{seed}"
            case_dir.mkdir()
            stimulus = case_dir / "stimulus.jsonl"
            reference_trace = case_dir / "reference.jsonl"
            model_trace = case_dir / "model.jsonl"
            values = {
                "{run_dir}": str(run_root), "{seed}": str(seed), "{cycles}": str(cycles),
                "{stimulus}": str(stimulus), "{trace}": "",
            }
            case_result: dict[str, Any] = {"kind": kind, "seed": seed, "cycles": cycles}
            for role, trace in (("stimulus", None), ("reference_run", reference_trace), ("model_run", model_trace)):
                values["{trace}"] = str(trace) if trace else ""
                result = _run_command(
                    f"{case_index:03d}-{role}", config["commands"][role], workspace,
                    logs / f"{case_index:03d}-{role}.log", values,
                )
                checks.append(result)
                if result["status"] != "passed":
                    status = result["status"]
                    case_result.update({"status": status, "reason": result.get("reason")})
                    break
                if role == "stimulus":
                    if not stimulus.is_file():
                        status = "failed"
                        case_result.update({"status": status, "reason": "stimulus was not produced"})
                        break
                    stimulus_digest = _digest(stimulus)
                elif _digest(stimulus) != stimulus_digest:
                    status = "failed"
                    case_result.update({"status": status, "reason": f"{role} modified stimulus"})
                    break
            if status == "passed":
                try:
                    comparison = compare_traces(
                        reference_trace, model_trace, observables,
                        config["sample_phase"], expected_samples=cycles,
                    )
                    case_result.update({"status": "passed", **comparison, "stimulus_sha256": stimulus_digest})
                except (FileNotFoundError, ValueError) as exc:
                    status = "failed"
                    case_result.update({"status": "failed", "reason": str(exc)})
            case_reports.append(case_result)
            if status != "passed":
                break

    changed = [
        path for path, digest in protected_hashes.items()
        if not Path(path).is_file() or _digest(Path(path)) != digest
    ]
    if changed:
        checks.append({
            "id": "protected-inputs", "status": "failed",
            "reason": f"verification modified protected inputs: {changed}",
        })
        status = "failed"
    else:
        checks.append({"id": "protected-inputs", "status": "passed"})

    report = {
        "schema_version": 1,
        "status": status,
        "result": (
            "cycle-equivalent" if status == "passed"
            else "blocked" if status == "blocked"
            else "not-cycle-equivalent"
        ),
        "config": {"path": str(config_path), "sha256": protected_hashes[str(config_path)]},
        "evidence": {
            "path": config["evidence"],
            "sha256": protected_hashes[str(workspace / config["evidence"])],
        },
        "source_manifest": {
            "path": config["source_manifest"],
            "sha256": protected_hashes[str(workspace / config["source_manifest"])],
        },
        "run_dir": str(run_root),
        "public_seeds": public_seeds,
        "fresh_seeds": fresh_seeds,
        "checks": checks,
        "cases": case_reports,
    }
    state.mkdir(exist_ok=True)
    (state / "cycle-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
