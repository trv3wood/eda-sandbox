from __future__ import annotations

import difflib
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from tlm_agent.graph.schema import read_jsonl
from tlm_agent.io import (
    dump_json,
    dump_yaml,
    file_digest,
    load_json,
    load_yaml,
    project_paths,
)

from .common import safe_relative_path
from .workflow import rtl_approval_is_valid


def _semicolon(value: str) -> str:
    return value.rstrip().rstrip(";") + ";"


def _indented(value: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in value.splitlines())


def _named_bindings(values: list[dict[str, Any]], indent: int) -> str:
    prefix = " " * indent
    return ",\n".join(
        f"{prefix}.{item['name']}({item['expression']})" for item in values
    )


def _instance_text(instance: dict[str, Any]) -> str:
    parameters = instance.get("parameter_bindings", [])
    parameter_text = ""
    if parameters:
        parameter_text = " #(\n" + _named_bindings(parameters, 8) + "\n    )"
    connections = _named_bindings(instance.get("connections", []), 8)
    return (
        f"    {instance['module']}{parameter_text} {instance['name']} (\n"
        f"{connections}\n"
        "    );"
    )


def _requirement_block(requirement: dict[str, Any]) -> str:
    evidence = ", ".join(requirement["evidence_ids"])
    identifier = requirement["id"]
    return f"""    // TODO[{identifier}]
    // 需求：{requirement['statement']}
    // Evidence: {evidence}
    // RTL_AGENT_EDIT_BEGIN {identifier}
    // 请严格按已批准的 RTL handoff 实现。
    // RTL_AGENT_EDIT_END {identifier}"""


def _module_text(module: dict[str, Any], requirements: list[dict[str, Any]]) -> str:
    imports = "\n".join(_semicolon(item) for item in module.get("imports", []))
    parameters = module.get("parameters", [])
    parameter_text = ""
    if parameters:
        values = ",\n".join(
            _indented(item["declaration"], 4) for item in parameters
        )
        parameter_text = f" #(\n{values}\n)"
    ports = ",\n".join(_indented(item["declaration"], 4) for item in module["ports"])
    signals = "\n".join(
        _indented(_semicolon(item["declaration"])) for item in module.get("signals", [])
    )
    instances = "\n\n".join(
        _instance_text(item) for item in module.get("instances", [])
    )
    todos = "\n\n".join(_requirement_block(item) for item in requirements)
    body = "\n\n".join(item for item in (signals, instances, todos) if item)
    prefix = f"{imports}\n\n" if imports else ""
    return f"""{prefix}module {module['name']}{parameter_text} (
{ports}
);

{body}

endmodule
"""


def _prepare_empty(paths: dict[str, Path]) -> None:
    for key in ("rtl_worktree", "rtl_baseline"):
        if paths[key].exists():
            raise FileExistsError(f"{paths[key]} already exists; preserve or remove the prior generated tree")
    paths["rtl_worktree"].mkdir(parents=True)


def _copy_project(project_dir: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git", ".systemc-agent", "__pycache__", "*.pyc", "build", "build-*",
    )
    shutil.copytree(project_dir, destination, symlinks=False, ignore=ignored)


def _generated_targets(path: Path, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data = path.read_bytes()
    targets = []
    for requirement in requirements:
        identifier = requirement["id"]
        begin = f"    // RTL_AGENT_EDIT_BEGIN {identifier}\n".encode()
        end = f"\n    // RTL_AGENT_EDIT_END {identifier}".encode()
        marker = data.find(begin)
        end_marker = data.find(end, marker + len(begin)) if marker >= 0 else -1
        if marker < 0 or end_marker < 0:
            raise RuntimeError(f"generated TODO markers are missing for {identifier}")
        start = marker + len(begin)
        targets.append({
            "id": f"todo-{identifier}",
            "kind": "generated_region",
            "path": str(path),
            "start_byte": start,
            "end_byte": end_marker,
            "text_sha256": hashlib.sha256(data[start:end_marker]).hexdigest(),
            "requirement_ids": [identifier],
        })
    return targets


def _generate_new_scaffold(
    paths: dict[str, Path], handoff: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]]]:
    generated: list[str] = []
    targets: list[dict[str, Any]] = []
    source_dir = paths["rtl_worktree"] / "rtl"
    source_dir.mkdir(parents=True)
    requirements = handoff["requirements"]
    for module in handoff["module_contracts"]:
        module_requirements = [
            item for item in requirements
            if item.get("module", handoff["target"]["top"]) == module["name"]
        ]
        output = source_dir / f"{module['name']}.sv"
        output.write_text(_module_text(module, module_requirements), encoding="utf-8")
        relative = str(output.relative_to(paths["rtl_worktree"]))
        generated.append(relative)
        for target in _generated_targets(output, module_requirements):
            target["path"] = relative
            targets.append(target)
    return generated, targets


def _patch_targets(paths: dict[str, Path], handoff: dict[str, Any]) -> list[dict[str, Any]]:
    index = {item["id"]: item for item in read_jsonl(paths["rtl_source_index"])}
    targets = []
    for declared in handoff["edit_targets"]:
        node = index[declared["node_id"]]
        relative = safe_relative_path(node["path"])
        copied = paths["rtl_worktree"] / relative
        if not copied.is_file():
            raise FileNotFoundError(f"patch source was not copied: {relative}")
        data = copied.read_bytes()
        start, end = node["start_byte"], node["end_byte"]
        if hashlib.sha256(data[start:end]).hexdigest() != node["text_sha256"]:
            raise ValueError(f"source span changed for {node['id']}")
        targets.append({
            "id": node["id"],
            "kind": node["kind"],
            "path": str(relative),
            "start_byte": start,
            "end_byte": end,
            "text_sha256": node["text_sha256"],
            "requirement_ids": declared["requirement_ids"],
        })
    return targets


def generate_rtl(project_dir: Path) -> dict[str, Any]:
    """从获批 handoff 生成骨架或隔离 patch working tree。"""
    valid, reason = rtl_approval_is_valid(project_dir)
    if not valid:
        raise ValueError(f"RTL generation blocked: {reason}")
    paths = project_paths(project_dir)
    handoff = load_yaml(paths["rtl_handoff"])
    mode = handoff["policy"]["mode"]
    if mode == "patch":
        for key in ("rtl_worktree", "rtl_baseline"):
            if paths[key].exists():
                raise FileExistsError(f"{paths[key]} already exists; preserve or remove the prior generated tree")
        _copy_project(project_dir, paths["rtl_worktree"])
        targets = _patch_targets(paths, handoff)
        generated = sorted({item["path"] for item in targets})
    else:
        _prepare_empty(paths)
        generated, targets = _generate_new_scaffold(paths, handoff)
    shutil.copytree(paths["rtl_worktree"], paths["rtl_baseline"], symlinks=False)
    generation = {
        "schema_version": 1,
        "mode": mode,
        "top": handoff["target"]["top"],
        "approval": reason,
        "files": generated,
        "targets": targets,
    }
    dump_yaml(paths["rtl_generation"], generation)
    dump_yaml(paths["rtl_worktree"] / "implementation-handoff.yaml", handoff)
    return {
        "mode": mode,
        "worktree": str(paths["rtl_worktree"]),
        "file_count": len(generated),
        "edit_target_count": len(targets),
    }


def _load_edits(path: Path) -> list[dict[str, Any]]:
    value = load_json(path)
    edits = value.get("edits") if isinstance(value, dict) else None
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits.json must contain a non-empty edits list")
    return edits


def _diff_trees(paths: dict[str, Path], touched: set[Path]) -> str:
    chunks = []
    for relative in sorted(touched, key=str):
        before_path = paths["rtl_baseline"] / relative
        after_path = paths["rtl_worktree"] / relative
        before = before_path.read_text(encoding="utf-8").splitlines(keepends=True)
        after = after_path.read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(
            before, after,
            fromfile=f"a/{relative}", tofile=f"b/{relative}",
        ))
    return "".join(chunks)


def apply_rtl_edits(project_dir: Path, edits_path: Path) -> dict[str, Any]:
    """校验结构化 edit，并只更新隔离 working tree。"""
    valid, reason = rtl_approval_is_valid(project_dir)
    if not valid:
        raise ValueError(f"RTL edit blocked: {reason}")
    paths = project_paths(project_dir)
    if paths["rtl_edits"].exists():
        raise FileExistsError("edits were already applied to this generated worktree")
    generation = load_yaml(paths["rtl_generation"])
    targets = {item["id"]: item for item in generation["targets"]}
    edits = _load_edits(edits_path)
    grouped: dict[Path, list[tuple[int, int, bytes, dict[str, Any]]]] = {}
    seen: set[str] = set()
    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            raise ValueError(f"edits[{index}] must be a mapping")
        target_id = edit.get("target_id")
        if target_id in seen:
            raise ValueError(f"duplicate edit target: {target_id}")
        seen.add(target_id)
        target = targets.get(target_id)
        if target is None:
            raise ValueError(f"unknown or unapproved edit target: {target_id}")
        if edit.get("base_sha256") != target["text_sha256"]:
            raise ValueError(f"stale base_sha256 for {target_id}")
        addressed = edit.get("requirement_ids")
        if not isinstance(addressed, list) or set(addressed) != set(target["requirement_ids"]):
            raise ValueError(f"requirement_ids must exactly match target {target_id}")
        replacement = edit.get("replacement_text")
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValueError(f"replacement_text is required for {target_id}")
        relative = safe_relative_path(target["path"])
        grouped.setdefault(relative, []).append((
            target["start_byte"], target["end_byte"], replacement.encode("utf-8"), target,
        ))
    for relative, values in grouped.items():
        path = paths["rtl_worktree"] / relative
        data = path.read_bytes()
        ordered = sorted(values, key=lambda item: item[0])
        for previous, current in zip(ordered, ordered[1:]):
            if previous[1] > current[0]:
                raise ValueError(f"overlapping edits in {relative}")
        for start, end, _, target in ordered:
            if hashlib.sha256(data[start:end]).hexdigest() != target["text_sha256"]:
                raise ValueError(f"working tree span changed before edit: {target['id']}")
        for start, end, replacement, _ in reversed(ordered):
            data = data[:start] + replacement + data[end:]
        path.write_bytes(data)
    patch = _diff_trees(paths, set(grouped))
    paths["rtl_patch"].write_text(patch, encoding="utf-8")
    dump_json(paths["rtl_edits"], {
        "schema_version": 1,
        "approval": reason,
        "source": str(edits_path),
        "edits": edits,
    })
    return {
        "worktree": str(paths["rtl_worktree"]),
        "edit_count": len(edits),
        "changed_files": [str(item) for item in sorted(grouped, key=str)],
        "patch": str(paths["rtl_patch"]),
    }
