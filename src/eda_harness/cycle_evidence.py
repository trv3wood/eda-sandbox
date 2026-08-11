"""Cycle-SystemC 的 EDA 证据与模型独立性审计。"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


LOCATION_PATTERN = re.compile(r"^(.+):(\d+)$")
FORBIDDEN_MODEL_PATTERNS = {
    "Verilator runtime": re.compile(r"\bverilated(?:\.h|_vcd|_fst)?\b", re.IGNORECASE),
    "reference trace": re.compile(r"reference[_-]?trace", re.IGNORECASE),
    "external process": re.compile(r"\b(?:system|popen|exec[lvpe]*)\s*\("),
}
FORBIDDEN_DEPENDENCY = re.compile(
    r"\b(?:verilated|verilator|vpi|dpi|vcs|xrun|questa|modelsim)\b",
    re.IGNORECASE,
)


def file_digest(path: Path) -> str:
    """计算报告使用的稳定文件摘要。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvidenceValidator:
    """校验语义结论、源码位置和 EDA artifact。"""

    def __init__(self, workspace: Path, top: str) -> None:
        self.workspace = workspace.resolve()
        self.top = top

    def validate(self, path: Path) -> dict[str, Any]:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ValueError("cycle evidence schema_version must be 1")
        if raw.get("top") != self.top:
            raise ValueError("cycle evidence top does not match cycle harness")
        semantics = raw.get("semantics")
        if not isinstance(semantics, list) or not semantics:
            raise ValueError("cycle evidence semantics must be a non-empty list")
        identifiers: set[str] = set()
        for index, semantic in enumerate(semantics, 1):
            self._validate_semantic(semantic, index, identifiers)
        return raw

    def _validate_semantic(
        self, semantic: Any, index: int, identifiers: set[str]
    ) -> None:
        prefix = f"semantics[{index}]"
        if not isinstance(semantic, dict):
            raise ValueError(f"{prefix} must be a mapping")
        identifier = semantic.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
        ):
            raise ValueError(f"{prefix}.id must be unique and non-empty")
        claim = semantic.get("claim")
        if not isinstance(claim, str) or not claim:
            raise ValueError(f"{prefix}.claim must be non-empty")
        identifiers.add(identifier)
        self._validate_locations(semantic, prefix, "rtl_locations")
        self._validate_locations(semantic, prefix, "systemc_locations")
        self._validate_tool_evidence(semantic, prefix)

    def _validate_locations(
        self, semantic: dict[str, Any], prefix: str, field: str
    ) -> None:
        locations = semantic.get(field)
        if not isinstance(locations, list) or not locations:
            raise ValueError(f"{prefix}.{field} must be a non-empty list")
        for index, location in enumerate(locations, 1):
            self._validate_location(location, f"{prefix}.{field}[{index}]")

    def _validate_location(self, value: Any, field: str) -> None:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be path:line")
        match = LOCATION_PATTERN.fullmatch(value)
        if not match:
            raise ValueError(f"{field} must be path:line")
        path = self._workspace_path(match.group(1), field)
        if not path.is_file():
            raise FileNotFoundError(f"{field} does not exist: {path}")
        line = int(match.group(2))
        line_count = len(
            path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
        if line <= 0 or line > line_count:
            raise ValueError(f"{field} line is outside file: {value}")

    def _validate_tool_evidence(
        self, semantic: dict[str, Any], prefix: str
    ) -> None:
        entries = semantic.get("tool_evidence")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{prefix}.tool_evidence must be a non-empty list")
        for index, entry in enumerate(entries, 1):
            self._validate_tool_entry(entry, f"{prefix}.tool_evidence[{index}]")

    def _validate_tool_entry(self, entry: Any, prefix: str) -> None:
        if not isinstance(entry, dict):
            raise ValueError(f"{prefix} must be a mapping")
        command = entry.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(value, str) and value for value in command
        ):
            raise ValueError(f"{prefix}.command must be an argv list")
        observation = entry.get("observation")
        if not isinstance(observation, str) or not observation:
            raise ValueError(f"{prefix}.observation must be non-empty")
        artifact = entry.get("artifact")
        if not isinstance(artifact, str) or not artifact:
            raise ValueError(f"{prefix}.artifact must be a relative path")
        artifact_path = self._workspace_path(artifact, f"{prefix}.artifact")
        if not artifact_path.is_file():
            raise FileNotFoundError(
                f"evidence artifact does not exist: {artifact_path}"
            )

    def _workspace_path(self, value: str, field: str) -> Path:
        path = (self.workspace / value).resolve()
        try:
            path.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError(f"{field} escapes workspace") from exc
        return path


class ModelAuditor:
    """确认最终模型不依赖 reference simulator 或外部进程。"""

    def __init__(self, workspace: Path, model_sources: tuple[str, ...]) -> None:
        self.workspace = workspace
        self.model_sources = model_sources

    def audit_sources(self) -> None:
        for relative in self.model_sources:
            text = (self.workspace / relative).read_text(
                encoding="utf-8", errors="replace"
            )
            for label, pattern in FORBIDDEN_MODEL_PATTERNS.items():
                if pattern.search(text):
                    raise ValueError(
                        f"model audit found forbidden {label} in {relative}"
                    )

    def audit_binary(self, path: Path) -> dict[str, Any]:
        if not path.is_file() or not os.access(path, os.X_OK):
            raise FileNotFoundError(f"model binary was not produced: {path}")
        reader = shutil.which("readelf") or shutil.which("objdump")
        if not reader:
            raise ValueError(
                "readelf or objdump is required for model dependency audit"
            )
        result = self._read_dependencies(reader, path)
        if result.returncode != 0:
            raise ValueError(
                "cannot inspect model binary dependencies: "
                f"{(result.stdout or '').strip()}"
            )
        dependencies = result.stdout or ""
        forbidden = FORBIDDEN_DEPENDENCY.search(dependencies)
        if forbidden:
            raise ValueError(
                "model binary depends on forbidden simulator component: "
                f"{forbidden.group(0)}"
            )
        return {
            "path": str(path),
            "sha256": file_digest(path),
            "dependencies": dependencies.splitlines(),
        }

    @staticmethod
    def _read_dependencies(reader: str, path: Path) -> subprocess.CompletedProcess[str]:
        arguments = (
            [reader, "-d", str(path)]
            if Path(reader).name == "readelf"
            else [reader, "-p", str(path)]
        )
        try:
            return subprocess.run(
                arguments,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(
                f"cannot inspect model binary dependencies: {exc}"
            ) from exc
