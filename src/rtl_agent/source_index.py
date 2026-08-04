from __future__ import annotations

import hashlib
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


def _index_file(path: Path, project_dir: Path, pyslang: Any) -> list[dict[str, Any]]:
    data = path.read_bytes()
    syntax = getattr(pyslang, "syntax", pyslang)
    tree = syntax.SyntaxTree.fromFile(str(path))
    diagnostics = list(getattr(tree, "diagnostics", []))
    if diagnostics:
        raise ValueError(f"pyslang failed to parse {path}: {diagnostics[0]}")
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


def build_source_index(project_dir: Path) -> dict[str, Any]:
    """使用 pyslang CST 建立精确、可摘要的源码节点索引。"""
    try:
        import pyslang  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("pyslang is required; install the project with the rtl extra") from exc
    _, sources = manifest_and_sources(project_dir)
    records: list[dict[str, Any]] = []
    for source in sources:
        records.extend(_index_file(source, project_dir, pyslang))
    path = project_paths(project_dir)["rtl_source_index"]
    write_jsonl(path, records)
    return {
        "path": str(path),
        "file_count": len(sources),
        "node_count": len(records),
        "editable_count": sum(bool(item["editable"]) for item in records),
    }
