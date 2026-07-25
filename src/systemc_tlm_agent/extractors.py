from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
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


@dataclass(frozen=True)
class Evidence:
    id: str
    source_kind: str
    source_path: str
    source_digest: str
    locator: str
    text: str
    extractor: str


def _evidence(
    *,
    kind: str,
    path: Path,
    project_dir: Path,
    locator: str,
    text: str,
    extractor: str,
) -> Evidence:
    import hashlib

    normalized = " ".join(text.split())
    key = f"{kind}\0{path.resolve()}\0{locator}\0{normalized}".encode()
    evidence_id = "ev-" + hashlib.sha256(key).hexdigest()[:16]
    return Evidence(
        id=evidence_id,
        source_kind=kind,
        source_path=relative_to_project(project_dir, path),
        source_digest=file_digest(path),
        locator=locator,
        text=normalized,
        extractor=extractor,
    )


def extract_docx(path: Path, project_dir: Path) -> tuple[list[Evidence], dict[str, Any]]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("DOCX extraction requires python-docx") from exc

    document = Document(path)
    evidence: list[Evidence] = []
    paragraphs = []
    for index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if not text:
            continue
        item = _evidence(
            kind="docx",
            path=path,
            project_dir=project_dir,
            locator=f"paragraph:{index}",
            text=text,
            extractor="python-docx",
        )
        evidence.append(item)
        paragraphs.append({"index": index, "style": paragraph.style.name, "evidence": item.id})

    tables = []
    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row_index, row in enumerate(table.rows, start=1):
            values = []
            for column_index, cell in enumerate(row.cells, start=1):
                text = cell.text.strip()
                if not text:
                    values.append(None)
                    continue
                item = _evidence(
                    kind="docx",
                    path=path,
                    project_dir=project_dir,
                    locator=f"table:{table_index}/row:{row_index}/cell:{column_index}",
                    text=text,
                    extractor="python-docx",
                )
                evidence.append(item)
                values.append(item.id)
            rows.append(values)
        tables.append({"index": table_index, "rows": rows})
    return evidence, {"path": str(path), "paragraphs": paragraphs, "tables": tables}


def extract_xlsx(path: Path, project_dir: Path) -> tuple[list[Evidence], dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("XLSX extraction requires openpyxl") from exc

    formula_book = load_workbook(path, data_only=False, read_only=False)
    value_book = load_workbook(path, data_only=True, read_only=False)
    evidence: list[Evidence] = []
    sheets: dict[str, Any] = {}
    for sheet in formula_book.worksheets:
        value_sheet = value_book[sheet.title]
        cells = []
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                cached = value_sheet[cell.coordinate].value
                text = str(cell.value)
                if text.startswith("="):
                    text = f"formula={text}; cached={cached!r}"
                item = _evidence(
                    kind="xlsx",
                    path=path,
                    project_dir=project_dir,
                    locator=f"sheet:{sheet.title}/cell:{cell.coordinate}",
                    text=text,
                    extractor="openpyxl",
                )
                evidence.append(item)
                cells.append(
                    {
                        "cell": cell.coordinate,
                        "evidence": item.id,
                        "formula": cell.value if str(cell.value).startswith("=") else None,
                        "cached": cached,
                    }
                )
        sheets[sheet.title] = {
            "cells": cells,
            "merged_ranges": [str(value) for value in sheet.merged_cells.ranges],
        }
    return evidence, {"path": str(path), "sheets": sheets}


# Regex extraction is only a lightweight, always-available hierarchy fallback.
# Surelog/UHDM, Verilator, and Yosys provide stronger parser/elaboration views.
MODULE_RE = re.compile(
    r"\bmodule\s+(?P<name>[A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*#\s*\((?P<params>.*?)\))?\s*\((?P<ports>.*?)\)\s*;",
    re.DOTALL,
)
INSTANCE_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*#\s*\(.*?\))?\s+(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE | re.DOTALL,
)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_rtl(path: Path, project_dir: Path) -> tuple[list[Evidence], dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    evidence: list[Evidence] = []
    modules = []
    for match in MODULE_RE.finditer(text):
        name = match.group("name")
        line = _line_number(text, match.start())
        item = _evidence(
            kind="rtl",
            path=path,
            project_dir=project_dir,
            locator=f"line:{line}/module:{name}",
            text=match.group(0)[:1000],
            extractor="systemc-tlm-agent-regex",
        )
        evidence.append(item)
        instances = []
        body_end = text.find("endmodule", match.end())
        body = text[match.end() : body_end if body_end >= 0 else len(text)]
        for instance in INSTANCE_RE.finditer(body):
            instance_type = instance.group("type")
            if instance_type in {
                "if",
                "for",
                "while",
                "case",
                "assign",
                "always",
                "always_ff",
                "always_comb",
            }:
                continue
            instances.append({"type": instance_type, "name": instance.group("name")})
        modules.append(
            {
                "name": name,
                "line": line,
                "evidence": item.id,
                "instances": instances,
                "ports_text": " ".join((match.group("ports") or "").split()),
                "parameters_text": " ".join((match.group("params") or "").split()),
            }
        )
    return evidence, {"path": str(path), "modules": modules}


def _run_tool(command: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"status": "unavailable", "command": command}
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.stdout, encoding="utf-8")
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "command": command,
        "log": str(log_path),
    }


def run_eda_tools(
    *,
    project_dir: Path,
    rtl_files: list[Path],
    top: str,
    tools_dir: Path,
) -> dict[str, Any]:
    # The command templates are tool integration policy. RTL file lists and the
    # top module come from manifest.yaml rather than being hard-coded.
    relative_rtl = [str(path) for path in rtl_files]
    surelog = _run_tool(
        ["surelog", *relative_rtl, "-parse", "-d", "uhdm"],
        project_dir,
        tools_dir / "surelog.log",
    )
    verilator = _run_tool(
        [
            "verilator",
            "--xml-only",
            "--top-module",
            top,
            "--xml-output",
            str(tools_dir / "verilator.xml"),
            *relative_rtl,
        ],
        project_dir,
        tools_dir / "verilator.log",
    )
    yosys_script = (
        "read_verilog -sv "
        + " ".join(relative_rtl)
        + f"; hierarchy -check -top {top}; write_json {tools_dir / 'yosys.json'}"
    )
    yosys = _run_tool(
        ["yosys", "-p", yosys_script],
        project_dir,
        tools_dir / "yosys.log",
    )
    return {"surelog": surelog, "verilator": verilator, "yosys": yosys}


def extract_project(project_dir: Path, *, run_tools: bool = True) -> dict[str, Any]:
    """Extract immutable, source-located facts from manifest inputs."""
    paths = project_paths(project_dir)
    manifest = load_yaml(paths["manifest"])
    all_evidence: list[Evidence] = []

    documents = []
    for path in resolve_inputs(project_dir, manifest.get("documents", [])):
        evidence, facts = extract_docx(path, project_dir)
        all_evidence.extend(evidence)
        documents.append(facts)

    registers = []
    for path in resolve_inputs(project_dir, manifest.get("registers", [])):
        evidence, facts = extract_xlsx(path, project_dir)
        all_evidence.extend(evidence)
        registers.append(facts)

    rtl_files = resolve_inputs(
        project_dir,
        manifest.get("rtl", []),
        directory_suffixes={".v", ".sv"},
    )
    rtl_units = []
    for path in rtl_files:
        evidence, facts = extract_rtl(path, project_dir)
        all_evidence.extend(evidence)
        rtl_units.append(facts)

    paths["facts"].mkdir(parents=True, exist_ok=True)
    dump_json(paths["facts"] / "documents.json", {"documents": documents})
    dump_json(paths["facts"] / "registers.json", {"workbooks": registers})
    rtl_facts = {
        "top": manifest["top"],
        "files": rtl_units,
        "tools": (
            run_eda_tools(
                project_dir=project_dir,
                rtl_files=rtl_files,
                top=manifest["top"],
                tools_dir=paths["tools"],
            )
            if run_tools and rtl_files
            else {
                tool: {
                    "status": "skipped",
                    "reason": (
                        "no RTL inputs were provided"
                        if not rtl_files
                        else "EDA tool execution was disabled"
                    ),
                }
                for tool in ("surelog", "verilator", "yosys")
            }
        ),
    }
    dump_json(paths["facts"] / "rtl.json", rtl_facts)
    with paths["evidence"].open("w", encoding="utf-8") as stream:
        for item in sorted(all_evidence, key=lambda value: value.id):
            stream.write(json.dumps(asdict(item), ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "evidence_count": len(all_evidence),
        "document_count": len(documents),
        "register_workbook_count": len(registers),
        "rtl_available": bool(rtl_files),
        "rtl_file_count": len(rtl_units),
        "rtl_module_count": sum(len(unit["modules"]) for unit in rtl_units),
        "missing_inputs": [] if rtl_files else ["rtl"],
    }
    dump_json(paths["facts"] / "summary.json", summary)
    return summary
