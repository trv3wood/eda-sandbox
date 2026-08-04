from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tlm_agent.io import dump_json, load_json, load_yaml, project_paths

from .common import safe_relative_path
from .workflow import rtl_gate_is_valid


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "blocked", "reason": reason}


def _run(command: list[str], cwd: Path, timeout: int = 1800) -> dict[str, Any]:
    executable = command[0]
    if not Path(executable).is_file() and shutil.which(executable) is None:
        return _blocked(f"tool is unavailable: {executable}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "reason": f"command timed out after {timeout} seconds",
            "command": command,
            "output": exc.stdout or "",
        }
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "command": command,
        "returncode": result.returncode,
        "output": result.stdout,
    }


def _tree_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root) for path in root.rglob("*") if path.is_file()
    }


def _integrity(paths: dict[str, Path], generation: dict[str, Any]) -> dict[str, Any]:
    baseline_files = _tree_files(paths["rtl_baseline"])
    worktree_files = _tree_files(paths["rtl_worktree"])
    handoff_path = Path("implementation-handoff.yaml")
    unexpected_added = sorted(worktree_files - baseline_files - {handoff_path}, key=str)
    missing = sorted(baseline_files - worktree_files, key=str)
    allowed = {safe_relative_path(value) for value in generation["files"]}
    changed = []
    unexpected_changed = []
    for relative in sorted(baseline_files & worktree_files, key=str):
        before = paths["rtl_baseline"] / relative
        after = paths["rtl_worktree"] / relative
        if before.read_bytes() == after.read_bytes():
            continue
        changed.append(str(relative))
        if relative not in allowed:
            unexpected_changed.append(str(relative))
    status = "passed" if not unexpected_added and not missing and not unexpected_changed else "failed"
    return {
        "status": status,
        "changed_files": changed,
        "unexpected_added": [str(item) for item in unexpected_added],
        "missing": [str(item) for item in missing],
        "unexpected_changed": unexpected_changed,
    }


def _node_bytes(node: Any, data: bytes) -> bytes | None:
    source_range = getattr(node, "sourceRange", None)
    start = getattr(getattr(source_range, "start", None), "offset", None)
    end = getattr(getattr(source_range, "end", None), "offset", None)
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(data):
        return data[start:end]
    return None


def _parse_and_structure(root: Path, files: list[str]) -> tuple[dict[str, Any], dict[str, list[str]]]:
    try:
        import pyslang  # type: ignore[import-not-found]
    except ImportError:
        return _blocked("pyslang is unavailable; install the rtl extra"), {}
    errors = []
    warnings = []
    structure = {"module_headers": [], "instances": []}
    trees = []
    for value in files:
        relative = safe_relative_path(value)
        path = root / relative
        if path.suffix.lower() not in {".v", ".sv", ".svp"}:
            continue
        syntax = getattr(pyslang, "syntax", pyslang)
        tree = syntax.SyntaxTree.fromFile(str(path))
        diagnostics = list(getattr(tree, "diagnostics", []))
        if diagnostics:
            errors.extend(f"{relative}: {getattr(item, 'code', item)}" for item in diagnostics)
            continue
        trees.append(tree)
        data = path.read_bytes()

        def visit(node: Any) -> Any:
            value = getattr(node, "kind", "")
            kind = str(getattr(value, "name", value)).rsplit(".", 1)[-1]
            target = (
                "module_headers" if kind == "ModuleHeader"
                else "instances" if kind == "HierarchyInstantiation"
                else None
            )
            node_data = _node_bytes(node, data)
            if target and node_data is not None:
                structure[target].append(hashlib.sha256(node_data).hexdigest())
            visit_action = getattr(pyslang, "VisitAction", None)
            if visit_action is None:
                visit_action = pyslang.ast.VisitAction
            return visit_action.Advance

        tree.root.visit(visit)
    compilation = pyslang.ast.Compilation()
    for tree in trees:
        compilation.addSyntaxTree(tree)
    semantic_diagnostics = list(compilation.getAllDiagnostics())
    for item in semantic_diagnostics:
        message = str(getattr(item, "code", item))
        if item.isError():
            errors.append(message)
        else:
            warnings.append(message)
    for values in structure.values():
        values.sort()
    return (
        {"status": "failed", "errors": errors, "warnings": warnings} if errors
        else {"status": "passed", "file_count": len(files), "warnings": warnings},
        structure,
    )


def _structure_gate(
    paths: dict[str, Path], generation: dict[str, Any], handoff: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_files = sorted(
        str(path.relative_to(paths["rtl_baseline"]))
        for path in paths["rtl_baseline"].rglob("*")
        if path.is_file() and path.suffix.lower() in {".v", ".sv", ".svp"}
    )
    candidate_files = sorted(
        str(path.relative_to(paths["rtl_worktree"]))
        for path in paths["rtl_worktree"].rglob("*")
        if path.is_file() and path.suffix.lower() in {".v", ".sv", ".svp"}
    )
    before_parse, before = _parse_and_structure(paths["rtl_baseline"], baseline_files)
    after_parse, after = _parse_and_structure(paths["rtl_worktree"], candidate_files)
    parse_gate = after_parse
    if before_parse["status"] != "passed" or after_parse["status"] != "passed":
        return parse_gate, _blocked("structure comparison requires successful baseline and candidate parsing")
    if generation["mode"] != "patch":
        return parse_gate, {"status": "passed", "policy": "declared-only scaffold"}
    if before["module_headers"] != after["module_headers"]:
        return parse_gate, {"status": "failed", "reason": "module interface changed in patch mode"}
    instance_edit_allowed = any(
        item.get("kind") == "instance" for item in handoff.get("edit_targets", [])
    )
    if before["instances"] != after["instances"] and not instance_edit_allowed:
        return parse_gate, {"status": "failed", "reason": "undeclared instance structure changed"}
    return parse_gate, {
        "status": "passed",
        "instance_change": before["instances"] != after["instances"],
        "instance_edit_allowed": instance_edit_allowed,
    }


def verify_rtl(project_dir: Path) -> dict[str, Any]:
    """分层验证 RTL worktree，缺失外部工具时显式 blocked。"""
    valid, reason = rtl_gate_is_valid(project_dir)
    if not valid:
        raise ValueError(f"RTL verification blocked: {reason}")
    paths = project_paths(project_dir)
    if not paths["rtl_generation"].is_file():
        raise FileNotFoundError("RTL generation manifest is missing; run generate first")
    generation = load_yaml(paths["rtl_generation"])
    handoff = load_yaml(paths["rtl_handoff"])
    integrity = _integrity(paths, generation)
    parse, structure = _structure_gate(paths, generation, handoff)
    verification = handoff["verification"]
    lint_command = verification["lint"]["command"]
    compile_command = verification["compile"]["command"]
    lint = _run(lint_command, paths["rtl_worktree"]) if lint_command else _blocked("lint command is not configured")
    compile_gate = _run(compile_command, paths["rtl_worktree"]) if compile_command else _blocked("compile command is not configured")

    expected_tests = {
        test_id
        for scenario in handoff.get("acceptance_scenarios", [])
        for test_id in scenario.get("test_ids", [])
    }
    configured_tests = {
        item["id"]: item for item in verification["simulation"].get("tests", [])
    }
    missing_tests = sorted(expected_tests - configured_tests.keys())
    if missing_tests:
        simulation: dict[str, Any] = _blocked("acceptance test IDs are not configured")
        simulation["missing"] = missing_tests
    elif not configured_tests:
        simulation = _blocked("existing simulation tests are not configured")
    else:
        results = {
            name: _run(item["command"], paths["rtl_worktree"], int(item.get("timeout_seconds", 1800)))
            for name, item in configured_tests.items()
        }
        simulation = {
            "status": "passed" if all(item["status"] == "passed" for item in results.values()) else "failed",
            "tests": results,
        }
    gates = [integrity, parse, structure, lint, compile_gate, simulation]
    if any(item["status"] == "failed" for item in gates):
        overall = "failed"
    elif any(item["status"] == "blocked" for item in gates):
        overall = "blocked"
    else:
        overall = "passed"
    report = {
        "schema_version": 1,
        "content_gate": reason,
        "integrity": integrity,
        "parse_elaborate": parse,
        "structure_delta": structure,
        "lint": lint,
        "compile": compile_gate,
        "simulation": simulation,
        "status": overall,
    }
    dump_json(paths["rtl_verification"], report)
    return report
