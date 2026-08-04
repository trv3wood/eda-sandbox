from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import (
    dump_json, file_digest, load_json, load_yaml, project_paths,
    relative_to_project, resolve_filelist_inputs, resolve_inputs,
    RTL_SOURCE_SUFFIXES,
)
from .toolchain import tool_command
from .uhdm_export import export_uhdm_structure
from .graph.finalize import finalize_graph


def _run(
    command: list[str],
    cwd: Path,
    log: Path,
    *,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"status": "unavailable", "command": command}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "command": command,
                "log": str(log),
                "timeout_seconds": timeout,
            }
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "command": command,
        "log": str(log),
    }


def _log_markers(log: Path, markers: tuple[str, ...]) -> tuple[bool, list[str]]:
    found = {marker: False for marker in markers}
    if log.is_file():
        with log.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                for marker in markers:
                    if marker in line:
                        found[marker] = True
    missing = [marker for marker, present in found.items() if not present]
    return not missing, missing


def _surelog_summary_is_clean(log: Path) -> bool:
    """Return whether Surelog reported zero fatal errors and errors."""
    counts: dict[str, int] = {}
    if not log.is_file():
        return False
    with log.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            for name in ("FATAL", "ERROR"):
                marker = f"[  {name}]"
                if marker not in line:
                    continue
                try:
                    counts[name] = int(line.rsplit(":", 1)[1].strip())
                except (IndexError, ValueError):
                    return False
    return counts.get("FATAL") == 0 and counts.get("ERROR") == 0


def _validated_surelog(
    command: list[str], cwd: Path, log: Path, database: Path
) -> dict[str, Any]:
    """Validate Surelog from its database and summary, not warning exit codes."""
    result = _run(command, cwd, log)
    database_valid = database.is_file() and database.stat().st_size > 0
    summary_clean = _surelog_summary_is_clean(log)
    if database_valid and summary_clean:
        return {
            **result,
            "status": "passed",
            "validation": "non-empty UHDM database and zero Surelog ERROR/FATAL summary",
        }
    return {
        **result,
        "status": "failed",
        "reason": "Surelog did not produce a clean elaborated UHDM database",
        "database_present": database_valid,
        "summary_clean": summary_clean,
    }


def _top_in_hierarchy(log: Path, reference_top: str) -> bool:
    if not log.is_file():
        return False
    in_tree = False
    with log.open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if line == "Instance tree:":
                in_tree = True
                continue
            if not in_tree or not line or line.startswith("Design name:"):
                continue
            object_name = line.split(" (", 1)[0].rsplit(".", 1)[-1]
            if object_name.rsplit("@", 1)[-1] == reference_top:
                return True
    return False


def _validated_cli(
    command: list[str],
    cwd: Path,
    log: Path,
    *,
    markers: tuple[str, ...] = (),
) -> dict[str, Any]:
    result = _run(command, cwd, log)
    if result.get("status") != "passed":
        return result
    valid, missing = _log_markers(log, markers)
    if not valid:
        return {
            **result,
            "status": "failed",
            "reason": "required success marker(s) missing",
            "missing_markers": missing,
        }
    return result


@dataclass(frozen=True)
class CompileInputs:
    """保留原生编译配方和可审计依赖闭包。"""

    manifest: dict[str, Any]
    sources: list[Path]
    filelists: list[Path]
    all_filelists: list[Path]
    source_files: list[Path]
    include_dirs: list[Path]
    defines: list[str]
    working_directory: Path

    @property
    def audit_inputs(self) -> list[Path]:
        return list(dict.fromkeys([*self.all_filelists, *self.source_files]))


def _compile_inputs(project: Path) -> CompileInputs:
    manifest = load_yaml(project / "manifest.yaml")
    compile_config = manifest.get("eda_compile") or {}
    if not isinstance(compile_config, dict):
        raise ValueError("manifest eda_compile must be a mapping")
    excludes = compile_config.get("exclude_sources", [])
    if not isinstance(excludes, list) or not all(
        isinstance(value, str) and value for value in excludes
    ):
        raise ValueError("eda_compile.exclude_sources must be a list of strings")
    working_value = compile_config.get("working_directory", ".")
    if not isinstance(working_value, str) or not working_value:
        raise ValueError("eda_compile.working_directory must be a string")
    working_path = Path(working_value)
    working_directory = (
        working_path if working_path.is_absolute() else project / working_path
    ).resolve()
    if not working_directory.is_dir():
        raise FileNotFoundError(
            f"EDA working directory does not exist: {working_value}"
        )
    filelists, all_filelists, filelist_sources = resolve_filelist_inputs(
        project,
        compile_config.get("filelists", []),
        working_directory=working_directory,
    )
    source_values = compile_config.get("sources")
    if source_values is None:
        source_values = [] if filelists else manifest.get("rtl", [])
    if not isinstance(source_values, list) or not all(
        isinstance(value, str) and value for value in source_values
    ):
        raise ValueError("eda_compile.sources must be a list of strings")
    sources = resolve_inputs(
        project,
        source_values,
        directory_suffixes=set(RTL_SOURCE_SUFFIXES),
        exclude_values=excludes,
    )
    include_dirs = []
    for value in compile_config.get("include_dirs", []):
        path = Path(value)
        resolved = (path if path.is_absolute() else project / path).resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"EDA include directory does not exist: {value}")
        include_dirs.append(resolved)
    defines = compile_config.get("defines", [])
    if not isinstance(defines, list) or not all(
        isinstance(value, str) and value for value in defines
    ):
        raise ValueError("eda_compile.defines must be a list of strings")
    source_files = list(dict.fromkeys([*filelist_sources, *sources]))
    if not source_files:
        raise ValueError(
            "eda_compile sources and filelist source closure are empty"
        )
    return CompileInputs(
        manifest=manifest,
        sources=sources,
        filelists=filelists,
        all_filelists=all_filelists,
        source_files=source_files,
        include_dirs=include_dirs,
        defines=defines,
        working_directory=working_directory,
    )


def _inputs(project: Path) -> tuple[dict[str, Any], list[Path], list[Path], list[str]]:
    """兼容现有调用方，返回完整源码闭包而非 filelist 本身。"""
    inputs = _compile_inputs(project)
    return (
        inputs.manifest,
        inputs.source_files,
        inputs.include_dirs,
        inputs.defines,
    )


def _rtl_backend(manifest: dict[str, Any]) -> str:
    """解析 RTL producer 后端；旧 manifest 保持 UHDM 兼容语义。"""
    graph = manifest.get("graph", {})
    if graph is None:
        graph = {}
    if not isinstance(graph, dict):
        raise ValueError("manifest graph must be a mapping")
    config = graph.get("rtl_extraction")
    if config is None:
        return "uhdm"
    if not isinstance(config, dict):
        raise ValueError("manifest graph.rtl_extraction must be a mapping")
    backend = config.get("backend", "vcs-vpi")
    if backend not in {"vcs-vpi", "uhdm"}:
        raise ValueError(
            "manifest graph.rtl_extraction.backend must be vcs-vpi or uhdm"
        )
    return str(backend)


def _version(command: list[str]) -> str:
    executable = shutil.which(command[0])
    if not executable:
        return "unavailable"
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run(
            command, cwd=temporary, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
    return (result.stdout.strip().splitlines() or ["unknown"])[0]


def _producer_record(
    name: str,
    tools: dict[str, Any],
    sources: list[Path],
    versions: dict[str, str],
    *,
    compile_inputs: CompileInputs | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": 1,
        "producer": name,
        "image_revision": os.environ.get("IMAGE_REVISION", "unknown"),
        "inputs": [
            {"path": str(path), "sha256": file_digest(path)}
            for path in sources
        ],
        "versions": versions,
        "tools": tools,
    }
    if compile_inputs is not None:
        result["compile"] = {
            "filelists": [str(path) for path in compile_inputs.filelists],
            "all_filelists": [
                str(path) for path in compile_inputs.all_filelists
            ],
            "filelist_source_closure": [
                str(path)
                for path in compile_inputs.source_files
                if path not in compile_inputs.sources
            ],
            "appended_sources": [
                str(path) for path in compile_inputs.sources
            ],
            "working_directory": str(compile_inputs.working_directory),
        }
    return result


def produce_uhdm(project: Path) -> dict[str, Any]:
    inputs = _compile_inputs(project)
    manifest = inputs.manifest
    sources = inputs.source_files
    paths = project_paths(project)
    work = paths["tools"] / "surelog-work"
    work.mkdir(parents=True, exist_ok=True)
    top = manifest.get("reference_top") or manifest.get("target_top") or manifest.get("top")
    command = [
        *tool_command("EDA_TOOL_SURELOG", "surelog"),
        *(item for path in inputs.filelists for item in ("-f", str(path))),
        *(str(path) for path in inputs.sources),
        *(f"-I{path}" for path in inputs.include_dirs),
        *(f"-D{value}" for value in inputs.defines),
        "-top", str(top), "-parse", "-elabuhdm",
    ]
    database = work / "slpp_all" / "surelog.uhdm"
    surelog = _validated_surelog(
        command, work, paths["tools"] / "surelog.log", database
    )
    database_valid = (
        surelog.get("status") == "passed"
        and database.is_file()
        and database.stat().st_size > 0
    )
    if database_valid:
        uhdm_elab = {
            "status": "passed",
            "database": relative_to_project(project, database),
            "validation": (
                "Surelog -elabuhdm produced a non-empty binary UHDM database "
                "with zero ERROR/FATAL summary"
            ),
        }
    else:
        uhdm_elab = {
            "status": "skipped",
            "reason": "Surelog did not successfully produce a non-empty UHDM database",
        }
    if uhdm_elab.get("status") == "passed":
        uhdm_lint = _validated_cli(
            [*tool_command("EDA_TOOL_UHDM_LINT", "uhdm-lint"), str(database)],
            project,
            paths["tools"] / "uhdm-lint.log",
        )
        uhdm_hier = _validated_cli(
            [*tool_command("EDA_TOOL_UHDM_HIER", "uhdm-hier"), str(database), "--line"],
            project,
            paths["tools"] / "uhdm-hier.log",
            markers=("Design name:", "Instance tree:"),
        )
        if (
            uhdm_hier.get("status") == "passed"
            and not _top_in_hierarchy(paths["tools"] / "uhdm-hier.log", str(top))
        ):
            uhdm_hier = {
                **uhdm_hier,
                "status": "failed",
                "reason": f"elaborated hierarchy does not contain top {top}",
            }
    else:
        reason = "Surelog did not produce a validated UHDM database"
        uhdm_lint = {"status": "skipped", "reason": reason}
        uhdm_hier = {"status": "skipped", "reason": reason}

    structure_path = paths["tools"] / "uhdm-structure.json"
    fixed_steps = (surelog, uhdm_elab, uhdm_lint, uhdm_hier)
    if all(item.get("status") == "passed" for item in fixed_steps):
        try:
            structure = export_uhdm_structure(database, sources, str(top))
            dump_json(structure_path, structure)
            structure_status = {
                "status": "passed",
                "path": relative_to_project(project, structure_path),
                "sha256": file_digest(structure_path),
            }
        except (RuntimeError, ValueError) as exc:
            structure_status = {"status": "failed", "reason": str(exc)}
    else:
        structure_status = {
            "status": "skipped",
            "reason": "fixed UHDM CLI validation did not pass",
        }
    aggregate_passed = all(
        item.get("status") == "passed"
        for item in (*fixed_steps, structure_status)
    )
    uhdm = {
        "status": "passed" if aggregate_passed else "failed",
        "database": relative_to_project(project, database),
        "database_sha256": file_digest(database) if database_valid else None,
        "database_size": database.stat().st_size if database_valid else 0,
        "structure": structure_status,
    }
    result = _producer_record(
        "uhdm",
        {
            "surelog": surelog,
            "uhdm_elab": uhdm_elab,
            "uhdm_lint": uhdm_lint,
            "uhdm_hier": uhdm_hier,
            "uhdm": uhdm,
        },
        inputs.audit_inputs,
        {
            "surelog": _version([*tool_command("EDA_TOOL_SURELOG", "surelog"), "-version"]),
            "uhdm_binding": _version([*tool_command("EDA_TOOL_UHDM", "eda-uhdm"), "version"]),
        },
        compile_inputs=inputs,
    )
    dump_json(paths["tools"] / "producer-uhdm.json", result)
    return result


def _vcs_home() -> Path:
    """定位 VCS 安装根目录和标准 VPI 头文件。"""
    configured = os.environ.get("VCS_HOME")
    if configured:
        root = Path(configured).resolve()
    else:
        executable = shutil.which(tool_command("EDA_TOOL_VCS", "vcs")[0])
        if not executable:
            raise RuntimeError("VCS is unavailable; configure the研发网 VCS environment")
        root = Path(executable).resolve().parent.parent
    header = root / "include" / "vpi_user.h"
    if not header.is_file():
        raise RuntimeError(f"VCS VPI header is unavailable: {header}")
    return root


def _vcs_config(manifest: dict[str, Any]) -> tuple[list[str], int]:
    compile_config = manifest.get("eda_compile") or {}
    vcs_args = compile_config.get("vcs_args", [])
    if not isinstance(vcs_args, list) or not all(
        isinstance(value, str) and value for value in vcs_args
    ):
        raise ValueError("eda_compile.vcs_args must be a list of strings")
    graph = manifest.get("graph") or {}
    rtl_config = graph.get("rtl_extraction") or {}
    timeout = rtl_config.get("timeout_seconds", 1800)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError(
            "graph.rtl_extraction.timeout_seconds must be a positive integer"
        )
    return vcs_args, timeout


def _vcs_debug_arguments(vcs_args: list[str]) -> list[str]:
    """默认保留完整 VPI 可见性，同时允许工程显式覆盖。"""
    if any(value.startswith("-debug_access") for value in vcs_args):
        return []
    return ["-debug_access+all"]


def _normalize_vcs_structure(
    raw: dict[str, Any],
    *,
    reference_top: str,
    executable: Path,
) -> dict[str, Any]:
    """把 VCS 的 elaborated VPI 视图归一化为后端无关结构契约。"""
    if not isinstance(raw, dict):
        raise ValueError("VCS VPI exporter output must be a JSON object")
    raw_tops = raw.get("top_modules")
    raw_packages = raw.get("packages", [])
    if not isinstance(raw_tops, list) or not all(
        isinstance(item, dict) for item in raw_tops
    ):
        raise ValueError("VCS VPI exporter top_modules must be a list of objects")
    if not isinstance(raw_packages, list) or not all(
        isinstance(item, dict) for item in raw_packages
    ):
        raise ValueError("VCS VPI exporter packages must be a list of objects")

    def records(value: object, field: str) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise ValueError(f"VCS VPI field {field} must be a list of objects")
        return value

    def named(item: dict[str, Any]) -> dict[str, Any]:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("VCS VPI named object is missing a name")
        result: dict[str, Any] = {"name": name.rsplit(".", 1)[-1]}
        path = item.get("path")
        if isinstance(path, str) and path:
            result["path"] = path
        line = item.get("line")
        if isinstance(line, int) and not isinstance(line, bool) and line > 0:
            result["line"] = line
        size = item.get("size")
        if isinstance(size, int) and not isinstance(size, bool) and size > 0:
            result["size"] = size
        direction = item.get("direction")
        if isinstance(direction, str) and direction:
            result["direction"] = direction
        return result

    definitions: dict[str, dict[str, Any]] = {}

    def module(item: dict[str, Any]) -> dict[str, Any]:
        raw_definition = item.get("definition") or item.get("name")
        if not isinstance(raw_definition, str) or not raw_definition:
            raise ValueError("VCS VPI module is missing a definition")
        definition_name = raw_definition.rsplit("@", 1)[-1]
        result = named(item)
        result["definition"] = f"work@{definition_name}"
        for field in ("ports", "parameters", "signals", "imports"):
            values = [named(value) for value in records(item.get(field), field)]
            unique = {
                (
                    value["name"],
                    value.get("path"),
                    value.get("line"),
                    value.get("direction"),
                    value.get("size"),
                ): value
                for value in values
            }
            result[field] = sorted(
                unique.values(),
                key=lambda value: (
                    value["name"],
                    str(value.get("path", "")),
                    int(value.get("line", 0)),
                ),
            )
        result["instances"] = [
            module(child) for child in records(item.get("instances"), "instances")
        ]
        result["instances"].sort(
            key=lambda value: (value["name"], value["definition"])
        )
        definition_record = {
            key: value for key, value in result.items() if key != "instances"
        }
        existing = definitions.get(result["definition"])
        if existing is None:
            definitions[result["definition"]] = definition_record
        return result

    top_modules = [module(item) for item in raw_tops]
    top_matches = [
        item
        for item in top_modules
        if item["definition"].rsplit("@", 1)[-1] == reference_top
    ]
    if len(top_matches) != 1 or len(top_modules) != 1:
        raise ValueError(
            f"VCS elaborated view must contain exactly top {reference_top}"
        )
    packages = [named(item) for item in raw_packages]
    packages.sort(key=lambda value: value["name"])
    return {
        "schema_version": 1,
        "backend": "vcs-vpi",
        "backend_artifact": {
            "kind": "vcs-simv",
            "path": str(executable),
            "sha256": file_digest(executable),
            "size": executable.stat().st_size,
        },
        "reference_top": reference_top,
        "top_modules": top_modules,
        "modules": sorted(definitions.values(), key=lambda value: value["definition"]),
        "packages": packages,
    }


def produce_vcs(project: Path) -> dict[str, Any]:
    """使用研发网 VCS elaboration 和零时刻 VPI 导出 RTL 结构。"""
    inputs = _compile_inputs(project)
    manifest = inputs.manifest
    sources = inputs.source_files
    vcs_args, timeout = _vcs_config(manifest)
    paths = project_paths(project)
    work = paths["tools"] / "vcs-work"
    work.mkdir(parents=True, exist_ok=True)
    top = (
        manifest.get("reference_top")
        or manifest.get("target_top")
        or manifest.get("top")
    )
    vcs_home = _vcs_home()
    compiler = shutil.which(tool_command("EDA_TOOL_CC", "cc")[0])
    if not compiler:
        raise RuntimeError("C compiler cc is unavailable for the VCS VPI exporter")
    source = Path(__file__).with_name("vcs_vpi_export.c")
    if not source.is_file():
        raise RuntimeError(f"packaged VCS VPI exporter is missing: {source}")
    library = work / "libtlm_graph_vpi.so"
    library.unlink(missing_ok=True)
    compile_plugin = _run(
        [
            compiler,
            "-std=c11",
            "-fPIC",
            "-shared",
            "-I",
            str(vcs_home / "include"),
            str(source),
            "-o",
            str(library),
        ],
        work,
        paths["tools"] / "vcs-vpi-compile.log",
        timeout=timeout,
    )
    executable = work / "simv"
    executable.unlink(missing_ok=True)
    vcs_make_directory = work / "csrc"
    vcs_make_argument = (
        []
        if any(value.startswith("-Mdir") for value in vcs_args)
        else [f"-Mdir={vcs_make_directory}"]
    )
    vcs_debug_arguments = _vcs_debug_arguments(vcs_args)
    if compile_plugin.get("status") == "passed" and library.is_file():
        vcs = _run(
            [
                *tool_command("EDA_TOOL_VCS", "vcs"),
                "-full64",
                "-sverilog",
                *(
                    item
                    for path in inputs.filelists
                    for item in ("-f", str(path))
                ),
                *(str(path) for path in inputs.sources),
                *(f"+incdir+{path}" for path in inputs.include_dirs),
                *(f"+define+{value}" for value in inputs.defines),
                *vcs_make_argument,
                *vcs_debug_arguments,
                *vcs_args,
                "-top",
                str(top),
                "-load",
                f"{library}:tlm_graph_register",
                "-o",
                str(executable),
            ],
            inputs.working_directory,
            paths["tools"] / "vcs.log",
            timeout=timeout,
        )
    else:
        vcs = {
            "status": "skipped",
            "reason": "VCS VPI exporter did not compile",
        }

    raw_path = work / "vcs-vpi-raw.json"
    raw_path.unlink(missing_ok=True)
    if vcs.get("status") == "passed" and executable.is_file():
        environment = os.environ.copy()
        environment["TLM_GRAPH_OUTPUT"] = str(raw_path)
        simulation = _run(
            [str(executable)],
            inputs.working_directory,
            paths["tools"] / "vcs-vpi-run.log",
            env=environment,
            timeout=timeout,
        )
    else:
        simulation = {
            "status": "skipped",
            "reason": "VCS elaboration did not produce simv",
        }

    structure_path = paths["tools"] / "rtl-structure.json"
    if simulation.get("status") == "passed" and raw_path.is_file():
        try:
            structure = _normalize_vcs_structure(
                load_json(raw_path),
                reference_top=str(top),
                executable=executable,
            )
            dump_json(structure_path, structure)
            structure_status = {
                "status": "passed",
                "path": relative_to_project(project, structure_path),
                "sha256": file_digest(structure_path),
            }
        except (json.JSONDecodeError, ValueError) as exc:
            structure_status = {"status": "failed", "reason": str(exc)}
    else:
        structure_status = {
            "status": "skipped",
            "reason": "VCS VPI execution did not produce a structure artifact",
        }
    aggregate_passed = all(
        item.get("status") == "passed"
        for item in (compile_plugin, vcs, simulation, structure_status)
    )
    rtl = {
        "status": "passed" if aggregate_passed else "failed",
        "backend": "vcs-vpi",
        "structure": structure_status,
        "backend_artifact": (
            {
                "path": relative_to_project(project, executable),
                "sha256": file_digest(executable),
                "size": executable.stat().st_size,
            }
            if executable.is_file()
            else None
        ),
    }
    result = _producer_record(
        "vcs-vpi",
        {
            "vpi_compile": compile_plugin,
            "vcs_elaboration": vcs,
            "vpi_export": simulation,
            "rtl": rtl,
        },
        inputs.audit_inputs,
        {
            "vcs": _version([*tool_command("EDA_TOOL_VCS", "vcs"), "-ID"]),
            "cc": _version([compiler, "--version"]),
        },
        compile_inputs=inputs,
    )
    dump_json(paths["tools"] / "producer-vcs-vpi.json", result)
    return result


def produce_rtl(project: Path) -> dict[str, Any]:
    """按 manifest 选择唯一的 canonical RTL producer。"""
    manifest = load_yaml(project / "manifest.yaml")
    backend = _rtl_backend(manifest)
    if backend == "vcs-vpi":
        return produce_vcs(project)
    return produce_uhdm(project)


def finalize_tools(project: Path) -> dict[str, Any]:
    paths = project_paths(project)
    tools: dict[str, Any] = {}

    def fail(reason: str) -> None:
        if paths["graph_manifest"].is_file():
            manifest = load_json(paths["graph_manifest"])
            manifest["status"] = "failed"
            manifest.setdefault("validation", {}).setdefault("errors", []).append(reason)
            dump_json(paths["graph_manifest"], manifest)
        raise ValueError(reason)

    graph_manifest = load_json(paths["graph_manifest"])
    rtl_required = graph_manifest.get("producers", {}).get("rtl", {}).get(
        "status"
    ) != "skipped"
    if not rtl_required:
        finalized = finalize_graph(project, structure=None, sources=[])
        return {
            "status": "finalized",
            "tools": {},
            "graph": {
                "status": finalized["status"],
                "content_digest": finalized["content_digest"],
            },
        }

    host_manifest = load_yaml(project / "manifest.yaml")
    backend = _rtl_backend(host_manifest)
    recorded_backend = graph_manifest.get("producers", {}).get("rtl", {}).get(
        "backend"
    )
    if recorded_backend not in {None, backend}:
        fail(
            "RTL backend changed since extraction; rerun extract --skip-tools"
        )
    producer_name = "vcs-vpi" if backend == "vcs-vpi" else "uhdm"
    missing = []
    producers = [producer_name]
    producer_records = {}
    for producer in producers:
        path = paths["tools"] / f"producer-{producer}.json"
        if not path.exists():
            missing.append(producer)
            continue
        producer_records[producer] = load_json(path)
        tools.update(producer_records[producer].get("tools", {}))
    if missing:
        fail("missing producer result(s): " + ", ".join(missing))
    rtl_gate = tools.get("rtl", {}) if backend == "vcs-vpi" else tools.get("uhdm", {})
    if rtl_gate.get("status") != "passed":
        fail(f"{backend} extraction gate did not pass")
    structure_record = rtl_gate.get("structure", {})
    structure_path = Path(structure_record.get("path", ""))
    if not structure_path.is_absolute():
        structure_path = project / structure_path
    if structure_record.get("status") != "passed" or not structure_path.is_file():
        fail(f"{backend} structure artifact is missing or invalid")
    if file_digest(structure_path) != structure_record.get("sha256"):
        fail(f"{backend} structure artifact digest mismatch")
    structure = load_json(structure_path)
    compile_inputs = _compile_inputs(project)
    manifest = compile_inputs.manifest
    host_sources = compile_inputs.source_files
    expected_structure_backend = (
        "vcs-vpi" if backend == "vcs-vpi" else "uhdm-python-vpi"
    )
    if (
        structure.get("schema_version") != 1
        or structure.get("backend") != expected_structure_backend
        or not isinstance(structure.get("modules"), list)
        or not structure["modules"]
        or not isinstance(structure.get("top_modules"), list)
        or not structure["top_modules"]
    ):
        fail(f"{backend} structure artifact schema or content is invalid")
    reference_top = (
        manifest.get("reference_top")
        or manifest.get("target_top")
        or manifest.get("top")
    )
    if structure.get("reference_top") != reference_top:
        fail(f"{backend} structure top does not match current manifest")
    if backend == "uhdm":
        database_path = Path(rtl_gate.get("database", ""))
        if not database_path.is_absolute():
            database_path = project / database_path
        if (
            not database_path.is_file()
            or file_digest(database_path) != rtl_gate.get("database_sha256")
            or structure.get("database", {}).get("sha256")
            != rtl_gate.get("database_sha256")
        ):
            fail("UHDM database is missing, changed, or inconsistent")
    else:
        backend_artifact = rtl_gate.get("backend_artifact")
        if not isinstance(backend_artifact, dict):
            fail("VCS backend artifact record is missing")
        executable_path = Path(backend_artifact.get("path", ""))
        if not executable_path.is_absolute():
            executable_path = project / executable_path
        if (
            not executable_path.is_file()
            or file_digest(executable_path) != backend_artifact.get("sha256")
            or structure.get("backend_artifact", {}).get("sha256")
            != backend_artifact.get("sha256")
        ):
            fail("VCS backend artifact is missing, changed, or inconsistent")
    expected_inputs = sorted(
        file_digest(path) for path in compile_inputs.audit_inputs
    )
    for producer, record in producer_records.items():
        if (
            record.get("schema_version") != 1
            or record.get("producer") != producer
            or not isinstance(record.get("inputs"), list)
        ):
            fail(f"{producer} producer record is invalid")
        actual_values = [item.get("sha256") for item in record["inputs"]]
        if not all(isinstance(value, str) for value in actual_values):
            fail(f"{producer} producer input digest is invalid")
        actual = sorted(actual_values)
        if actual != expected_inputs:
            fail(f"{producer} producer inputs do not match current manifest")
    graph_manifest = finalize_graph(
        project,
        structure=structure,
        sources=host_sources,
    )
    return {
        "status": "finalized",
        "tools": tools,
        "graph": {
            "status": graph_manifest["status"],
            "content_digest": graph_manifest["content_digest"],
        },
    }


def _main(kind: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"eda-{kind}-produce")
    parser.add_argument("project")
    args = parser.parse_args(argv)
    try:
        project = Path(args.project).resolve()
        if kind == "uhdm":
            result = produce_uhdm(project)
        elif kind == "vcs":
            result = produce_vcs(project)
        else:
            result = produce_rtl(project)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if all(
            item.get("status") in {"passed", "skipped"}
            for item in result["tools"].values()
        ) else 1
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def uhdm_main(argv: list[str] | None = None) -> int:
    return _main("uhdm", argv)


def vcs_main(argv: list[str] | None = None) -> int:
    return _main("vcs", argv)


def rtl_main(argv: list[str] | None = None) -> int:
    return _main("rtl", argv)
