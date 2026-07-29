from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .io import (
    dump_json, file_digest, load_json, load_yaml, project_paths,
    relative_to_project, resolve_inputs,
)
from .uhdm_export import export_uhdm_structure


def _run(
    command: list[str],
    cwd: Path,
    log: Path,
) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"status": "unavailable", "command": command}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
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


def _inputs(project: Path) -> tuple[dict[str, Any], list[Path], list[Path], list[str]]:
    manifest = load_yaml(project / "manifest.yaml")
    compile_config = manifest.get("eda_compile") or {}
    excludes = compile_config.get("exclude_sources", [])
    if not isinstance(excludes, list) or not all(
        isinstance(value, str) and value for value in excludes
    ):
        raise ValueError("eda_compile.exclude_sources must be a list of strings")
    sources = resolve_inputs(
        project,
        compile_config.get("sources", manifest.get("rtl", [])),
        directory_suffixes={".v", ".sv"},
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
    if not sources:
        raise ValueError("eda_compile sources are empty after exclude_sources")
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
            ["uhdm-lint", str(database)],
            project,
            paths["tools"] / "uhdm-lint.log",
        )
        uhdm_hier = _validated_cli(
            ["uhdm-hier", str(database), "--line"],
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
        sources,
        {
            "surelog": _version(["surelog", "-version"]),
            "uhdm_binding": _version(["eda-uhdm", "version"]),
        },
    )
    dump_json(paths["tools"] / "producer-uhdm.json", result)
    return result


def produce_rtl(project: Path) -> dict[str, Any]:
    manifest, rtl, include_dirs, defines = _inputs(project)
    paths = project_paths(project)
    top = manifest.get("reference_top") or manifest.get("target_top") or manifest.get("top")
    verilator = _run(
        [
            "verilator", "--json-only", "--top-module", str(top),
            "--json-only-output", str(paths["tools"] / "verilator.json"),
            *(f"-I{path}" for path in include_dirs),
            *(f"-D{value}" for value in defines),
            *(str(path) for path in rtl),
        ],
        project,
        paths["tools"] / "verilator.log",
    )
    yosys_script = (
        "read_verilog -sv "
        + " ".join(json.dumps(f"-I{path}") for path in include_dirs)
        + " "
        + " ".join(json.dumps(f"-D{value}") for value in defines)
        + " "
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

    def fail(reason: str) -> None:
        facts.update(
            {
                "schema_version": 2,
                "status": "failed",
                "backend": "uhdm",
                "files": [],
                "top_modules": [],
                "tools": tools,
                "failure": reason,
            }
        )
        dump_json(rtl_path, facts)
        summary_path = paths["facts"] / "summary.json"
        if summary_path.exists():
            summary = load_json(summary_path)
            summary["rtl_status"] = "failed"
            summary["rtl_module_count"] = 0
            dump_json(summary_path, summary)
        raise ValueError(reason)

    missing = []
    producers = ["uhdm", "rtl"]
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
    uhdm = tools.get("uhdm", {})
    if uhdm.get("status") != "passed":
        fail("UHDM extraction gate did not pass")
    structure_record = uhdm.get("structure", {})
    structure_path = Path(structure_record.get("path", ""))
    if not structure_path.is_absolute():
        structure_path = project / structure_path
    if structure_record.get("status") != "passed" or not structure_path.is_file():
        fail("UHDM structure artifact is missing or invalid")
    if file_digest(structure_path) != structure_record.get("sha256"):
        fail("UHDM structure artifact digest mismatch")
    structure = load_json(structure_path)
    manifest, host_sources, _, _ = _inputs(project)
    if (
        structure.get("schema_version") != 1
        or structure.get("backend") != "uhdm-python-vpi"
        or not isinstance(structure.get("modules"), list)
        or not structure["modules"]
        or not isinstance(structure.get("top_modules"), list)
        or not structure["top_modules"]
    ):
        fail("UHDM structure artifact schema or content is invalid")
    reference_top = (
        manifest.get("reference_top")
        or manifest.get("target_top")
        or manifest.get("top")
    )
    if structure.get("reference_top") != reference_top:
        fail("UHDM structure top does not match current manifest")
    database_path = Path(uhdm.get("database", ""))
    if not database_path.is_absolute():
        database_path = project / database_path
    if (
        not database_path.is_file()
        or file_digest(database_path) != uhdm.get("database_sha256")
        or structure.get("database", {}).get("sha256")
        != uhdm.get("database_sha256")
    ):
        fail("UHDM database is missing, changed, or inconsistent")
    expected_inputs = {
        "uhdm": sorted(file_digest(source) for source in host_sources),
        "rtl": sorted(file_digest(source) for source in host_sources),
    }
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
        if actual != expected_inputs[producer]:
            fail(f"{producer} producer inputs do not match current manifest")
    sources_by_digest: dict[str, list[Path]] = {}
    for source in host_sources:
        sources_by_digest.setdefault(file_digest(source), []).append(source)
    files_by_path: dict[Path, dict[str, Any]] = {
        source: {"path": relative_to_project(project, source), "modules": []}
        for source in host_sources
    }
    rtl_evidence = []
    from .extractors import _evidence

    def normalize_locations(value: Any) -> Any:
        if isinstance(value, list):
            return [normalize_locations(item) for item in value]
        if not isinstance(value, dict):
            return value
        normalized = {
            key: normalize_locations(item) for key, item in value.items()
        }
        digest = normalized.get("sha256")
        matches = sources_by_digest.get(digest, [])
        if len(matches) == 1:
            normalized["path"] = relative_to_project(project, matches[0])
        return normalized

    normalized_modules = normalize_locations(copy.deepcopy(structure["modules"]))
    normalized_tops = normalize_locations(copy.deepcopy(structure["top_modules"]))
    for raw_module in normalized_modules:
        digest = raw_module.get("sha256")
        matches = sources_by_digest.get(digest, [])
        if len(matches) > 1 and raw_module.get("path"):
            source_name = Path(raw_module["path"]).name
            matches = [source for source in matches if source.name == source_name]
        if len(matches) != 1:
            fail(
                f"UHDM module {raw_module.get('name')} cannot be mapped to one RTL input"
            )
        source = matches[0]
        module = dict(raw_module)
        module_name = (
            module.get("definition") or module.get("name") or ""
        ).rsplit("@", 1)[-1]
        line = module.get("line")
        evidence = _evidence(
            kind="rtl",
            path=source,
            project_dir=project,
            locator=f"line:{line or 'unknown'}/module:{module_name}",
            text=f"UHDM module definition {module_name}",
            extractor="uhdm-python-vpi/1",
        )
        module["name"] = module_name
        module["evidence"] = evidence.id
        files_by_path[source]["modules"].append(module)
        rtl_evidence.append(asdict(evidence))

    database = dict(structure["database"])
    recorded_database = Path(uhdm.get("database", database["path"]))
    database["path"] = (
        str(recorded_database)
        if not recorded_database.is_absolute()
        else relative_to_project(project, recorded_database)
    )
    facts.update(
        {
            "schema_version": 2,
            "status": "ready",
            "backend": "uhdm",
            "database": database,
            "top_modules": normalized_tops,
            "files": [
                files_by_path[path]
                for path in sorted(files_by_path)
                if files_by_path[path]["modules"]
            ],
            "tools": tools,
        }
    )
    facts["uhdm_modules"] = normalized_modules
    dump_json(rtl_path, facts)
    existing_evidence = []
    if paths["evidence"].exists():
        for line in paths["evidence"].read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get("source_kind") != "rtl":
                    existing_evidence.append(item)
    with paths["evidence"].open("w", encoding="utf-8") as stream:
        for item in sorted(
            [*existing_evidence, *rtl_evidence], key=lambda value: value["id"]
        ):
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    summary_path = paths["facts"] / "summary.json"
    if summary_path.exists():
        summary = load_json(summary_path)
        summary["rtl_status"] = "ready"
        summary["rtl_module_count"] = len(normalized_modules)
        summary["evidence_count"] = len(existing_evidence) + len(rtl_evidence)
        dump_json(summary_path, summary)
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
