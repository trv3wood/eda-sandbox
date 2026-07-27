from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .io import (
    dump_json, file_digest, load_json, load_yaml, project_paths, resolve_inputs,
)


def _run(command: list[str], cwd: Path, log: Path) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"status": "unavailable", "command": command}
    result = subprocess.run(
        command, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout, encoding="utf-8")
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "command": command,
        "log": str(log),
    }


def _inputs(project: Path) -> tuple[dict[str, Any], list[Path], list[Path], list[str]]:
    manifest = load_yaml(project / "manifest.yaml")
    compile_config = manifest.get("eda_compile") or {}
    sources = resolve_inputs(
        project,
        compile_config.get("sources", manifest.get("rtl", [])),
        directory_suffixes={".v", ".sv"},
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
    return manifest, sources, include_dirs, defines


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
) -> dict[str, Any]:
    return {
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


def produce_uhdm(project: Path) -> dict[str, Any]:
    manifest, sources, include_dirs, defines = _inputs(project)
    paths = project_paths(project)
    work = paths["tools"] / "surelog-work"
    work.mkdir(parents=True, exist_ok=True)
    top = manifest.get("reference_top") or manifest.get("target_top") or manifest.get("top")
    command = [
        "surelog", *(str(path) for path in sources),
        *(f"-I{path}" for path in include_dirs),
        *(f"-D{value}" for value in defines),
        "-top", str(top), "-parse", "-elabuhdm", "-d", "uhdm",
    ]
    surelog = _run(command, work, paths["tools"] / "surelog.log")
    database = work / "slpp_all" / "surelog.uhdm"
    if surelog["status"] == "passed" and database.is_file():
        uhdm = _run(
            [
                "eda-uhdm", "export", str(database),
                "--output", str(paths["tools"] / "uhdm.json"),
                "--source-root", str(project),
            ],
            project,
            paths["tools"] / "uhdm-export.log",
        )
    else:
        uhdm = {
            "status": "skipped",
            "reason": "Surelog did not complete without errors",
            "source": str(database),
        }
    result = _producer_record(
        "uhdm",
        {"surelog": surelog, "uhdm": uhdm},
        sources,
        {
            "surelog": _version(["surelog", "-version"]),
            "uhdm_binding": _version(["eda-uhdm", "version"]),
        },
    )
    dump_json(paths["tools"] / "producer-uhdm.json", result)
    return result


def produce_rtl(project: Path) -> dict[str, Any]:
    manifest = load_yaml(project / "manifest.yaml")
    paths = project_paths(project)
    rtl = resolve_inputs(
        project, manifest.get("rtl", []), directory_suffixes={".v", ".sv"}
    )
    top = manifest.get("reference_top") or manifest.get("target_top") or manifest.get("top")
    verilator = _run(
        [
            "verilator", "--json-only", "--top-module", str(top),
            "--json-only-output", str(paths["tools"] / "verilator.json"),
            *(str(path) for path in rtl),
        ],
        project,
        paths["tools"] / "verilator.log",
    )
    yosys_script = (
        "read_verilog -sv "
        + " ".join(json.dumps(str(path)) for path in rtl)
        + f"; hierarchy -check -top {top}; write_json "
        + json.dumps(str(paths["tools"] / "yosys.json"))
    )
    yosys = _run(
        ["yosys", "-p", yosys_script],
        project,
        paths["tools"] / "yosys.log",
    )
    result = _producer_record(
        "rtl",
        {"verilator": verilator, "yosys": yosys},
        rtl,
        {
            "verilator": _version(["verilator", "--version"]),
            "yosys": _version(["yosys", "-V"]),
        },
    )
    dump_json(paths["tools"] / "producer-rtl.json", result)
    return result


def finalize_tools(project: Path) -> dict[str, Any]:
    paths = project_paths(project)
    rtl_path = paths["facts"] / "rtl.json"
    facts = load_json(rtl_path)
    tools: dict[str, Any] = {}
    missing = []
    producers = ["uhdm", "rtl"]
    for producer in producers:
        path = paths["tools"] / f"producer-{producer}.json"
        if not path.exists():
            missing.append(producer)
            continue
        tools.update(load_json(path).get("tools", {}))
    if missing:
        raise ValueError("missing producer result(s): " + ", ".join(missing))
    facts["tools"] = tools
    dump_json(rtl_path, facts)
    return {"status": "finalized", "tools": tools}


def _main(kind: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"eda-{kind}-produce")
    parser.add_argument("project")
    args = parser.parse_args(argv)
    try:
        result = (
            produce_uhdm(Path(args.project).resolve())
            if kind == "uhdm"
            else produce_rtl(Path(args.project).resolve())
        )
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


def rtl_main(argv: list[str] | None = None) -> int:
    return _main("rtl", argv)
