"""Cycle-SystemC 门禁的外部命令运行边界。"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cycle_config import CommandSpec


@dataclass(frozen=True)
class CommandContext:
    """单次命令的安全占位符值。"""

    run_dir: Path
    seed: int = 0
    cycles: int = 0
    stimulus: Path | None = None
    trace: Path | None = None

    def placeholders(self) -> dict[str, str]:
        return {
            "{run_dir}": str(self.run_dir),
            "{seed}": str(self.seed),
            "{cycles}": str(self.cycles),
            "{stimulus}": str(self.stimulus) if self.stimulus else "",
            "{trace}": str(self.trace) if self.trace else "",
        }


class CommandRunner:
    """解析可执行文件、控制超时并保留完整日志。"""

    def __init__(self, workspace: Path, logs: Path) -> None:
        self.workspace = workspace
        self.logs = logs

    def run(
        self, identifier: str, spec: CommandSpec, context: CommandContext
    ) -> dict[str, Any]:
        command = self._expand(spec.argv, context.placeholders())
        cwd = self.workspace / spec.cwd
        log_path = self.logs / f"{identifier}.log"
        base = {
            "id": identifier,
            "command": command,
            "cwd": spec.cwd,
            "log": str(log_path),
        }
        if not self._resolve_executable(command[0], cwd):
            reason = f"tool is unavailable: {command[0]}"
            log_path.write_text(reason + "\n", encoding="utf-8")
            return {**base, "status": "blocked", "reason": reason}
        return self._execute(command, cwd, spec.timeout_seconds, log_path, base)

    @staticmethod
    def _expand(argv: tuple[str, ...], values: dict[str, str]) -> list[str]:
        result: list[str] = []
        for argument in argv:
            expanded = argument
            for placeholder, value in values.items():
                expanded = expanded.replace(placeholder, value)
            result.append(expanded)
        return result

    @staticmethod
    def _resolve_executable(executable: str, cwd: Path) -> str | None:
        path = Path(executable)
        if path.is_absolute():
            return executable if path.is_file() and os.access(path, os.X_OK) else None
        if "/" in executable:
            candidate = (cwd / path).resolve()
            return (
                str(candidate)
                if candidate.is_file() and os.access(candidate, os.X_OK)
                else None
            )
        return shutil.which(executable)

    @staticmethod
    def _execute(
        command: list[str],
        cwd: Path,
        timeout: int,
        log_path: Path,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            reason = f"cannot start command: {exc}"
            log_path.write_text(reason + "\n", encoding="utf-8")
            return {**base, "status": "blocked", "reason": reason}
        output, timed_out = CommandRunner._communicate(process, timeout)
        log_path.write_text(output, encoding="utf-8", errors="replace")
        result = {
            **base,
            "duration_seconds": round(time.monotonic() - started, 6),
            "returncode": process.returncode,
        }
        if timed_out:
            return {**result, "status": "failed", "reason": "command timed out"}
        return {
            **result,
            "status": "passed" if process.returncode == 0 else "failed",
        }

    @staticmethod
    def _communicate(
        process: subprocess.Popen[str], timeout: int
    ) -> tuple[str, bool]:
        try:
            output, _ = process.communicate(timeout=timeout)
            return output or "", False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
            return output or "", True
