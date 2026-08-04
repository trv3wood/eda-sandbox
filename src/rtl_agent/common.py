from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tlm_agent.io import (
    RTL_SOURCE_SUFFIXES,
    load_yaml,
    project_paths,
    resolve_filelist_inputs,
    resolve_inputs,
)


def manifest_and_sources(project_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    """按现有 manifest 的编译顺序解析 RTL 源文件。"""
    paths = project_paths(project_dir)
    manifest = load_yaml(paths["manifest"])
    compile_config = manifest.get("eda_compile", {})
    if not isinstance(compile_config, dict):
        raise ValueError("manifest eda_compile must be a mapping")
    working_value = compile_config.get("working_directory", ".")
    if not isinstance(working_value, str) or not working_value:
        raise ValueError("eda_compile.working_directory must be a string")
    expanded = os.path.expandvars(os.path.expanduser(working_value))
    if "$" in expanded:
        raise ValueError("eda_compile.working_directory has unresolved variable")
    working = Path(expanded)
    working = (working if working.is_absolute() else project_dir / working).resolve()
    _, _, filelist_sources = resolve_filelist_inputs(
        project_dir,
        compile_config.get("filelists", []),
        working_directory=working,
    )
    source_values = compile_config.get("sources")
    if source_values is None:
        source_values = manifest.get("rtl", [])
    explicit = resolve_inputs(
        project_dir,
        source_values,
        directory_suffixes=set(RTL_SOURCE_SUFFIXES),
        exclude_values=compile_config.get("exclude_sources", []),
    )
    sources = list(dict.fromkeys([*filelist_sources, *explicit]))
    if not sources:
        sources = resolve_inputs(
            project_dir,
            manifest.get("rtl", []),
            directory_suffixes=set(RTL_SOURCE_SUFFIXES),
        )
    return manifest, sources


def safe_relative_path(value: Any) -> Path:
    """拒绝绝对路径和目录穿越。"""
    if not isinstance(value, str) or not value:
        raise ValueError("relative path is required")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path

