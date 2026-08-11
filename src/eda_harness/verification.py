"""按声明执行验证命令，并保存分层结果。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .state import STATE_DIR


def _run_check(check: dict[str, Any], workspace: Path, logs: Path) -> dict[str, Any]:
    command = check["command"]
    executable = command[0]
    cwd = workspace / check["cwd"]
    executable_path = Path(executable)
    if executable_path.is_absolute():
        resolved = (
            str(executable_path)
            if executable_path.is_file() and os.access(executable_path, os.X_OK)
            else None
        )
    elif "/" in executable:
        candidate = (cwd / executable_path).resolve()
        resolved = (
            str(candidate)
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    else:
        resolved = shutil.which(executable)
    base = {
        "id": check["id"],
        "category": check["category"],
        "required": check["required"],
        "command": command,
        "cwd": check["cwd"],
        "timeout_seconds": check["timeout_seconds"],
    }
    log_path = logs / f"{check['id']}.log"
    base["log"] = str(log_path)
    if not resolved:
        log_path.write_text(f"tool is unavailable: {executable}\n", encoding="utf-8")
        return {**base, "status": "blocked", "reason": f"tool is unavailable: {executable}"}
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
        log_path.write_text(f"cannot start command: {exc}\n", encoding="utf-8")
        return {**base, "status": "blocked", "reason": f"cannot start command: {exc}"}
    timed_out = False
    try:
        output, _ = process.communicate(timeout=check["timeout_seconds"])
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
    duration = round(time.monotonic() - started, 6)
    log_path.write_text(output or "", encoding="utf-8", errors="replace")
    if timed_out:
        return {
            **base,
            "status": "failed",
            "reason": f"command timed out after {check['timeout_seconds']} seconds",
            "duration_seconds": duration,
            "returncode": process.returncode,
        }
    return {
        **base,
        "status": "passed" if process.returncode == 0 else "failed",
        "duration_seconds": duration,
        "returncode": process.returncode,
    }


def verify(
    root: Path,
    *,
    config_path: Path,
    task_path: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """按声明运行全部检查。"""
    root = root.resolve()
    workspace = (root / config["workspace"]).resolve()
    state = root / STATE_DIR
    logs = state / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for check in config["checks"]:
        blocked_by = [
            identifier for identifier in check["depends_on"]
            if by_id[identifier]["status"] != "passed"
        ]
        if blocked_by:
            result = {
                "id": check["id"],
                "category": check["category"],
                "required": check["required"],
                "command": check["command"],
                "cwd": check["cwd"],
                "status": "blocked",
                "reason": f"dependency did not pass: {', '.join(blocked_by)}",
            }
        else:
            result = _run_check(check, workspace, logs)
        results.append(result)
        by_id[check["id"]] = result
    required = [item for item in results if item["required"]]
    if any(item["status"] == "failed" for item in required):
        overall = "failed"
    elif any(item["status"] == "blocked" for item in required):
        overall = "blocked"
    else:
        overall = "passed"

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    report = {
        "schema_version": 1,
        "status": overall,
        "task": {"path": str(task_path), "sha256": digest(task_path)},
        "config": {"path": str(config_path), "sha256": digest(config_path)},
        "checks": results,
    }
    report_path = state / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
