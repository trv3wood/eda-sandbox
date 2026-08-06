"""记录任务开始状态，并核对本次文件变化范围。"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


STATE_DIR = ".eda-harness"
DEFAULT_EXCLUDED_NAMES = frozenset({".git", STATE_DIR, "__pycache__", ".pytest_cache"})


def _digest(path: Path) -> str:
    if path.is_symlink():
        return "symlink:" + os.readlink(path)
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _git_files(workspace: Path) -> list[Path] | None:
    probe = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode or probe.stdout.strip() != "true":
        return None
    result = subprocess.run(
        ["git", "-C", str(workspace), "ls-files", "-co", "--exclude-standard", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return [workspace / item.decode() for item in result.stdout.split(b"\0") if item]


def _recursive_files(workspace: Path) -> list[Path]:
    result = []
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace)
        if any(
            part in DEFAULT_EXCLUDED_NAMES or part == "build" or part.startswith("build-")
            for part in relative.parts
        ):
            continue
        if path.is_file() or path.is_symlink():
            result.append(path)
    return result


def inventory(
    workspace: Path, *, control_files: set[Path] | None = None
) -> tuple[dict[str, str], str]:
    """返回稳定的相对路径到摘要映射及枚举来源。"""
    controls = {item.resolve() for item in (control_files or set())}
    files = _git_files(workspace)
    source = "git" if files is not None else "filesystem"
    selected = files if files is not None else _recursive_files(workspace)
    values: dict[str, str] = {}
    for path in sorted(set(selected), key=str):
        if path.resolve() in controls or not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(workspace).as_posix()
        if relative == STATE_DIR or relative.startswith(f"{STATE_DIR}/"):
            continue
        values[relative] = _digest(path)
    return values, source


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def create_snapshot(
    root: Path,
    *,
    config_path: Path,
    task_path: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """在首个代码修改前创建不可隐式覆盖的基线。"""
    root = root.resolve()
    workspace = (root / config["workspace"]).resolve()
    state_path = root / STATE_DIR / "baseline.json"
    if state_path.exists():
        raise FileExistsError(
            f"snapshot already exists: {state_path}; remove it explicitly to start a new task"
        )
    if not task_path.is_file():
        raise FileNotFoundError(task_path)
    controls = {config_path.resolve(), task_path.resolve()}
    files, source = inventory(workspace, control_files=controls)
    snapshot = {
        "schema_version": 1,
        "workspace": str(workspace.relative_to(root)),
        "inventory_source": source,
        "allowed_changes": config["allowed_changes"],
        "task": str(task_path.resolve()),
        "task_sha256": _digest(task_path),
        "config": str(config_path.resolve()),
        "files": files,
    }
    _write_json(state_path, snapshot)
    return {"snapshot": str(state_path), "file_count": len(files), "inventory_source": source}


def _allowed(path: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(path, pattern)
        or (pattern.endswith("/**") and path == pattern[:-3].rstrip("/"))
        for pattern in patterns
    )


def check_integrity(root: Path, config_path: Path, task_path: Path) -> dict[str, Any]:
    """比较 snapshot 后的增量，并用 snapshot 中锁定的范围判定。"""
    baseline_path = root / STATE_DIR / "baseline.json"
    if not baseline_path.is_file():
        raise FileNotFoundError("baseline snapshot is missing; run snapshot first")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    workspace = (root / baseline["workspace"]).resolve()
    current, source = inventory(
        workspace, control_files={config_path.resolve(), task_path.resolve()}
    )
    before = baseline["files"]
    added = sorted(set(current) - set(before))
    deleted = sorted(set(before) - set(current))
    modified = sorted(
        path for path in set(before) & set(current) if before[path] != current[path]
    )
    changed = sorted({*added, *deleted, *modified})
    violations = sorted(path for path in changed if not _allowed(path, baseline["allowed_changes"]))
    return {
        "status": "failed" if violations else "passed",
        "inventory_source": source,
        "added": added,
        "deleted": deleted,
        "modified": modified,
        "violations": violations,
        "allowed_changes": baseline["allowed_changes"],
    }
