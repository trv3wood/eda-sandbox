from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import (
    dump_json,
    file_digest,
    load_yaml,
    project_paths,
    relative_to_project,
    resolve_inputs,
)
from .graph_extract import extract_document_graph, extract_workbook_units
from .graph_schema import GRAPH_SCHEMA_VERSION, canonical_digest, write_jsonl


def extract_project(project_dir: Path, *, run_tools: bool = True) -> dict[str, Any]:
    """Extract deterministic document units and initialize the canonical graph."""
    paths = project_paths(project_dir)
    manifest = load_yaml(paths["manifest"])
    document_paths = resolve_inputs(project_dir, manifest.get("documents", []))
    register_paths = resolve_inputs(project_dir, manifest.get("registers", []))
    rtl_files = resolve_inputs(
        project_dir,
        manifest.get("rtl", []),
        directory_suffixes={".v", ".sv"},
    )
    testbench_files = resolve_inputs(
        project_dir,
        manifest.get("testbench", []),
        directory_suffixes={".v", ".sv"},
    )
    compile_config = manifest.get("eda_compile", {})
    if compile_config and not isinstance(compile_config, dict):
        raise ValueError("manifest eda_compile must be a mapping")
    excludes = compile_config.get("exclude_sources", [])
    if not isinstance(excludes, list) or not all(
        isinstance(value, str) and value for value in excludes
    ):
        raise ValueError("manifest eda_compile.exclude_sources must be a list of strings")
    compile_sources = resolve_inputs(
        project_dir,
        compile_config.get("sources", manifest.get("rtl", [])),
        directory_suffixes={".v", ".sv"},
        exclude_values=excludes,
    )
    include_dirs = []
    for value in compile_config.get("include_dirs", []):
        path = Path(value)
        resolved = (path if path.is_absolute() else project_dir / path).resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"EDA include directory does not exist: {value}")
        include_dirs.append(resolved)
    defines = compile_config.get("defines", [])
    if not isinstance(defines, list) or not all(
        isinstance(value, str) and value for value in defines
    ):
        raise ValueError("manifest eda_compile.defines must be a list of strings")
    if rtl_files and not compile_sources:
        raise ValueError("manifest eda_compile sources are empty after exclude_sources")
    target_top = manifest.get("target_top", manifest.get("top"))
    reference_top = manifest.get("reference_top") or target_top
    if not target_top:
        raise ValueError("manifest requires target_top (or legacy top)")
    graph = paths["graph"]
    graph.mkdir(parents=True, exist_ok=True)
    document_tree, text_units = extract_document_graph(
        project_dir, document_paths
    )
    workbook_trees, workbook_units = extract_workbook_units(
        project_dir, register_paths
    )
    document_tree["workbooks"] = workbook_trees
    text_units = [*text_units, *workbook_units]
    for ordinal, unit in enumerate(text_units):
        unit["ordinal"] = ordinal
    dump_json(graph / "document_tree.json", document_tree)
    write_jsonl(graph / "text_units.jsonl", text_units)
    for name in (
        "spec_entities.jsonl",
        "spec_relationships.jsonl",
        "rtl_entities.jsonl",
        "rtl_relationships.jsonl",
        "cross_source_relationships.jsonl",
        "entities.jsonl",
        "relationships.jsonl",
    ):
        write_jsonl(graph / name, [])
    input_paths = sorted(set([
        *document_paths,
        *register_paths,
        *rtl_files,
        *testbench_files,
        *compile_sources,
    ]))
    input_records = [
        {
            "path": relative_to_project(project_dir, path),
            "sha256": file_digest(path),
        }
        for path in input_paths
    ]
    graph_manifest = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "status": "pending" if (text_units or rtl_files) else "ready",
        "target_top": target_top,
        "reference_top": reference_top,
        "inputs": input_records,
        "input_digest": canonical_digest(input_records),
        "producers": {
            "documents": {
                "status": "passed",
                "text_unit_count": len(text_units),
            },
            "spec": {
                "status": "pending" if text_units else "skipped",
                "reason": None if text_units else "no document text units",
            },
            "rtl": {
                "status": "pending" if rtl_files else "skipped",
                "reason": None if rtl_files else "no RTL inputs",
            },
            "cross_source": {"status": "pending"},
        },
        "artifacts": {},
        "validation": {"errors": [], "warnings": [], "metrics": {}},
    }
    dump_json(paths["graph_manifest"], graph_manifest)
    summary = {
        "document_count": len(document_paths),
        "register_workbook_count": len(register_paths),
        "text_unit_count": len(text_units),
        "rtl_available": bool(rtl_files),
        "rtl_file_count": len(rtl_files),
        "testbench_file_count": len(testbench_files),
        "rtl_status": graph_manifest["producers"]["rtl"]["status"],
        "graph_status": graph_manifest["status"],
        "missing_inputs": [] if rtl_files else ["rtl"],
    }
    if run_tools and rtl_files:
        from .graph_extract import produce_spec_graph
        from .tool_producers import finalize_tools, produce_rtl, produce_uhdm

        if text_units:
            produce_spec_graph(project_dir)
        produce_uhdm(project_dir)
        produce_rtl(project_dir)
        finalize_tools(project_dir)
        finalized = load_json(paths["graph_manifest"])
        summary["graph_status"] = finalized["status"]
        summary["rtl_status"] = finalized["producers"]["rtl"]["status"]
    elif run_tools:
        from .graph_extract import produce_spec_graph
        from .graph_finalize import finalize_graph

        if text_units:
            produce_spec_graph(project_dir)
        finalize_graph(project_dir, structure=None, sources=[])
        summary["graph_status"] = "ready"
    return summary
