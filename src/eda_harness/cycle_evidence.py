"""Cycle-SystemC 模型独立性审计。"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


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


class ModelAuditor:
    """确认最终模型不依赖 reference simulator、trace 或外部进程。"""

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
