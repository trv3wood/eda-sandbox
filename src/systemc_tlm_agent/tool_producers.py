from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import shlex
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


def _vcs_config(project: Path) -> tuple[dict[str, Any], Path, list[str]]:
    """Validate the portable manifest contract for an LSF-hosted VCS run."""
    manifest = load_yaml(project / "manifest.yaml")
    config = manifest.get("synopsys_vcs")
    if not isinstance(config, dict):
        raise ValueError("synopsys_vcs must be a YAML mapping")
    sim_top = config.get("sim_top")
    if not isinstance(sim_top, str) or not sim_top:
        raise ValueError("synopsys_vcs.sim_top must be a non-empty string")
    for key in ("compile_args", "run_args", "fsdb_index_command"):
        value = config.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError(f"synopsys_vcs.{key} must be a list of strings")
    index_command = config["fsdb_index_command"]
    if "{fsdb}" not in index_command or "{output}" not in index_command:
        raise ValueError(
            "synopsys_vcs.fsdb_index_command must contain {fsdb} and {output}"
        )
    allowed_placeholders = {"{fsdb}", "{output}"}
    if any("{" in item or "}" in item for item in index_command if item not in allowed_placeholders):
        raise ValueError(
            "FSDB command placeholders must be standalone {fsdb} or {output} arguments"
        )
    fsdb_value = config.get("fsdb_path")
    if not isinstance(fsdb_value, str) or not fsdb_value:
        raise ValueError("synopsys_vcs.fsdb_path must be a non-empty relative path")
    fsdb_path = (project / fsdb_value).resolve()
    try:
        fsdb_path.relative_to(project.resolve())
    except ValueError as exc:
        raise ValueError("synopsys_vcs.fsdb_path must stay within the project") from exc
    if Path(fsdb_value).is_absolute():
        raise ValueError("synopsys_vcs.fsdb_path must be relative")
    compile_config = manifest.get("eda_compile") or {}
    sources = resolve_inputs(
        project,
        compile_config.get("sources", manifest.get("rtl", [])),
        directory_suffixes={".v", ".sv"},
    )
    testbench = resolve_inputs(
        project, manifest.get("testbench", []), directory_suffixes={".v", ".sv"}
    )
    return config, fsdb_path, [str(path) for path in dict.fromkeys([*sources, *testbench])]


def _validate_vcs_snapshot(path: Path) -> dict[str, Any]:
    try:
        snapshot = load_json(path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError("FSDB indexer did not produce valid JSON") from exc
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema_version") != 1
        or snapshot.get("format") != "vcs-json"
        or not isinstance(snapshot.get("modules"), list)
        or not isinstance(snapshot.get("signals"), list)
    ):
        raise RuntimeError("FSDB indexer produced an unsupported vcs-json snapshot")
    for key in ("modules", "signals"):
        if not all(isinstance(item, dict) for item in snapshot[key]):
            raise RuntimeError(f"vcs-json {key} must contain objects")
    return snapshot


def _write_vcs_script(
    script: Path,
    *,
    project: Path,
    config: dict[str, Any],
    sources: list[str],
    fsdb_path: Path,
    snapshot_path: Path,
    work: Path,
) -> None:
    manifest = load_yaml(project / "manifest.yaml")
    compile_config = manifest.get("eda_compile") or {}
    include_dirs = [
        str((project / value).resolve()) if not Path(value).is_absolute() else value
        for value in compile_config.get("include_dirs", [])
    ]
    defines = compile_config.get("defines", [])
    if not all(isinstance(value, str) and value for value in include_dirs + defines):
        raise ValueError("eda_compile include_dirs and defines must be lists of strings")
    simv = work / "simv"
    compile_command = [
        "vcs", "-sverilog", "-full64", "-top", config["sim_top"],
        "-o", str(simv), *sources,
        *(f"+incdir+{value}" for value in include_dirs),
        *(f"+define+{value}" for value in defines),
        *config["compile_args"],
    ]
    index_command = [
        str(fsdb_path) if item == "{fsdb}" else str(snapshot_path)
        if item == "{output}" else item
        for item in config["fsdb_index_command"]
    ]
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        f"mkdir -p {shlex.quote(str(work))}\n"
        f"vcs -ID > {shlex.quote(str(work / 'vcs-version.log'))} 2>&1 || true\n"
        f"{shlex.join(compile_command)} > {shlex.quote(str(work / 'vcs.log'))} 2>&1\n"
        f"{shlex.join([str(simv), *config['run_args']])} > {shlex.quote(str(work / 'sim.log'))} 2>&1\n"
        f"test -f {shlex.quote(str(fsdb_path))}\n"
        f"{shlex.join(index_command)} > {shlex.quote(str(work / 'fsdb-index.log'))} 2>&1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def produce_vcs(project: Path) -> dict[str, Any]:
    """Run VCS and the site-provided FSDB indexer on the LSF sim queue."""
    project = project.resolve()
    config, fsdb_path, sources = _vcs_config(project)
    paths = project_paths(project)
    work = paths["tools"] / "vcs-work"
    snapshot_path = paths["tools"] / "vcs.json"
    snapshot_temporary = work / "vcs-index.json"
    script = work / "run-vcs.sh"
    snapshot_path.unlink(missing_ok=True)
    snapshot_temporary.unlink(missing_ok=True)
    _write_vcs_script(
        script, project=project, config=config, sources=sources,
        fsdb_path=fsdb_path, snapshot_path=snapshot_temporary, work=work,
    )
    bsub = shutil.which("bsub")
    command = ["bsub", "-q", "sim", "-K", "-cwd", str(project), "-oo",
               str(paths["tools"] / "vcs-lsf.log"), "bash", str(script)]
    tool: dict[str, Any] = {"command": command, "script": str(script)}
    if not bsub:
        tool.update({"status": "unavailable", "reason": "bsub is unavailable"})
    else:
        result = subprocess.run(
            command, cwd=project, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
        submission = paths["tools"] / "vcs-submit.log"
        submission.parent.mkdir(parents=True, exist_ok=True)
        submission.write_text(result.stdout, encoding="utf-8")
        tool.update({"returncode": result.returncode, "log": str(submission)})
        job = re.search(r"Job\s+<(\d+)>", result.stdout)
        if job:
            tool["job_id"] = job.group(1)
        if result.returncode:
            tool.update({"status": "failed", "reason": "LSF VCS job failed"})
        else:
            try:
                snapshot = _validate_vcs_snapshot(snapshot_temporary)
                snapshot_temporary.replace(snapshot_path)
                version_log = work / "vcs-version.log"
                version = (
                    version_log.read_text(encoding="utf-8").splitlines()[:1]
                    if version_log.is_file() else []
                )
                tool.update({
                    "status": "passed", "fsdb": str(fsdb_path),
                    "fsdb_sha256": file_digest(fsdb_path),
                    "snapshot": str(snapshot_path),
                    "vcs_version": version[0] if version else "unknown",
                    "modules": len(snapshot["modules"]),
                    "signals": len(snapshot["signals"]),
                })
            except (FileNotFoundError, RuntimeError) as exc:
                tool.update({"status": "failed", "reason": str(exc)})
    result = _producer_record(
        "vcs", {"vcs": tool}, [Path(path) for path in sources],
        {"vcs": "LSF job"},
    )
    dump_json(paths["tools"] / "producer-vcs.json", result)
    return result


def finalize_tools(project: Path) -> dict[str, Any]:
    paths = project_paths(project)
    rtl_path = paths["facts"] / "rtl.json"
    facts = load_json(rtl_path)
    tools: dict[str, Any] = {}
    missing = []
    manifest = load_yaml(project / "manifest.yaml")
    producers = ["uhdm", "rtl"]
    if "synopsys_vcs" in manifest:
        producers.append("vcs")
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


def vcs_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eda-vcs-produce")
    parser.add_argument("project")
    args = parser.parse_args(argv)
    try:
        result = produce_vcs(Path(args.project))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["tools"]["vcs"].get("status") == "passed" else 1
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
