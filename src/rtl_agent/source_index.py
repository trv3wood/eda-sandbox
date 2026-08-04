from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from tlm_agent.graph.schema import canonical_digest, write_jsonl
from tlm_agent.io import file_digest, project_paths, relative_to_project

from .common import manifest_and_sources


INDEXED_KINDS = {
    "ModuleDeclaration": "module",
    "AlwaysBlock": "process",
    "AlwaysCombBlock": "process",
    "AlwaysFFBlock": "process",
    "AlwaysLatchBlock": "process",
    "ContinuousAssign": "continuous_assign",
    "HierarchyInstantiation": "instance",
}
ALLOWED_EDIT_KINDS = frozenset({"process", "continuous_assign", "instance"})


def _kind_name(node: Any) -> str:
    value = getattr(node, "kind", "")
    return str(getattr(value, "name", value)).rsplit(".", 1)[-1]


def _offset(location: Any) -> int | None:
    value = getattr(location, "offset", None)
    return value if isinstance(value, int) else None


def _range(node: Any) -> tuple[int, int] | None:
    source_range = getattr(node, "sourceRange", None)
    if source_range is None:
        return None
    start = _offset(getattr(source_range, "start", None))
    end = _offset(getattr(source_range, "end", None))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _line_column(data: bytes, offset: int) -> tuple[int, int]:
    prefix = data[:offset]
    line = prefix.count(b"\n") + 1
    column = offset - prefix.rfind(b"\n")
    return line, column


def _index_file(
    path: Path, project_dir: Path, pyslang: Any, include_dirs: list[Path]
) -> list[dict[str, Any]]:
    data = path.read_bytes()
    syntax = getattr(pyslang, "syntax", pyslang)
    # FuseSoC 等工程通过 manifest 传递 `include 路径；逐文件直接解析会
    # 错过这些目录并把可编译的真实 RTL 误报为语法失败。
    source_manager = pyslang.SourceManager()
    for include_dir in include_dirs:
        source_manager.addUserDirectories(str(include_dir))
    tree = syntax.SyntaxTree.fromFile(str(path), source_manager)
    diagnostics = list(getattr(tree, "diagnostics", []))
    errors = [item for item in diagnostics if item.isError()]
    if errors:
        raise ValueError(f"pyslang failed to parse {path}: {errors[0]}")
    records: list[dict[str, Any]] = []

    def visit(node: Any) -> Any:
        syntax_kind = _kind_name(node)
        node_kind = INDEXED_KINDS.get(syntax_kind)
        span = _range(node)
        if node_kind and span is not None:
            start, end = span
            if end <= len(data):
                line, column = _line_column(data, start)
                identity = {
                    "path": relative_to_project(project_dir, path),
                    "file_sha256": file_digest(path),
                    "syntax_kind": syntax_kind,
                    "start_byte": start,
                    "end_byte": end,
                }
                records.append({
                    "id": f"syn-{canonical_digest(identity)[:20]}",
                    "kind": node_kind,
                    "syntax_kind": syntax_kind,
                    "path": identity["path"],
                    "start_byte": start,
                    "end_byte": end,
                    "line": line,
                    "column": column,
                    "file_sha256": identity["file_sha256"],
                    "text_sha256": hashlib.sha256(data[start:end]).hexdigest(),
                    "editable": node_kind in ALLOWED_EDIT_KINDS,
                })
        visit_action = getattr(pyslang, "VisitAction", None)
        if visit_action is None:
            visit_action = pyslang.ast.VisitAction
        return visit_action.Advance

    try:
        tree.root.visit(visit)
    except AttributeError as exc:
        raise RuntimeError("installed pyslang does not expose CST visitation") from exc
    return records


def _include_dirs(project_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    compile_config = manifest.get("eda_compile", {})
    if not isinstance(compile_config, dict):
        raise ValueError("manifest eda_compile must be a mapping")
    values = compile_config.get("include_dirs", [])
    if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
        raise ValueError("eda_compile.include_dirs must be a list of strings")
    resolved = []
    for value in values:
        expanded = os.path.expandvars(os.path.expanduser(value))
        if "$" in expanded:
            raise ValueError(f"eda_compile.include_dirs has unresolved variable: {value}")
        candidate = Path(expanded)
        path = (candidate if candidate.is_absolute() else project_dir / candidate).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"SystemVerilog include directory does not exist: {value}")
        if path not in resolved:
            resolved.append(path)
    return resolved


def build_source_index(project_dir: Path) -> dict[str, Any]:
    """使用 pyslang CST 建立精确、可摘要的源码节点索引。"""
    try:
        import pyslang  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("pyslang is required; install the project with the rtl extra") from exc
    manifest, sources = manifest_and_sources(project_dir)
    include_dirs = _include_dirs(project_dir, manifest)
    records: list[dict[str, Any]] = []
    for source in sources:
        records.extend(_index_file(source, project_dir, pyslang, include_dirs))
    path = project_paths(project_dir)["rtl_source_index"]
    write_jsonl(path, records)
    return {
        "path": str(path),
        "file_count": len(sources),
        "node_count": len(records),
        "editable_count": sum(bool(item["editable"]) for item in records),
    }
