from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import json

from .io import dump_json, load_json, load_yaml, project_paths


def _execute(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "status": "passed" if result.returncode == 0 else "failed",
        "output": result.stdout,
    }


def _find_repo_root(project_dir: Path) -> Path | None:
    for candidate in (project_dir, *project_dir.parents):
        if (candidate / "compose.yaml").exists():
            return candidate
    return None


def verify_project(project_dir: Path, *, backend: str = "auto") -> dict[str, Any]:
    paths = project_paths(project_dir)
    if not (paths["model"] / "CMakeLists.txt").exists():
        raise FileNotFoundError("model/CMakeLists.txt is missing; run generate first")

    selected = backend
    if selected == "auto":
        # /opt/scc is the image installation convention. Users can override
        # this heuristic explicitly with --backend local or --backend podman.
        selected = "local" if Path("/opt/scc").exists() else "podman"

    if selected == "podman":
        repo_root = _find_repo_root(project_dir.resolve())
        if repo_root is None:
            raise RuntimeError("cannot locate compose.yaml for podman backend")
        relative_project = project_dir.resolve().relative_to(repo_root)
        inner = (
            f"cd {shlex.quote(str(Path('/workspace') / relative_project))} && "
            "PYTHONPATH=/workspace/src python3 -m systemc_tlm_agent.cli "
            "verify . --backend local"
        )
        provider = shutil.which("podman-compose")
        if provider:
            command = [
                provider,
                "-f",
                str(repo_root / "compose.yaml"),
                "run",
                "--rm",
                "-T",
                # This service name is repository integration policy and is
                # therefore the main container-related hard-coded value.
                "eda-scc",
                "bash",
                "-lc",
                inner,
            ]
        else:
            command = [
                "podman",
                "compose",
                "-f",
                str(repo_root / "compose.yaml"),
                "run",
                "--rm",
                "-T",
                "eda-scc",
                "bash",
                "-lc",
                inner,
            ]
        result = _execute(command, repo_root)
        result["backend"] = "podman"
        dump_json(paths["verification"], result)
        return result

    build_dir = paths["model"] / "build"
    configure = _execute(
        [
            "cmake",
            "-S",
            str(paths["model"]),
            "-B",
            str(build_dir),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
        ],
        project_dir,
    )
    build = (
        _execute(["cmake", "--build", str(build_dir), "--parallel"], project_dir)
        if configure["returncode"] == 0
        else {"status": "skipped", "returncode": 1, "output": ""}
    )
    discovery = (
        _execute(["ctest", "--test-dir", str(build_dir), "--show-only=json-v1"], project_dir)
        if build["returncode"] == 0
        else {"status": "skipped", "returncode": 1, "output": ""}
    )
    expected_tests = {
        f"contract::{test['id']}"
        for test in load_yaml(paths["contract_test_manifest"]).get("tests", [])
    }
    discovered_tests: set[str] = set()
    if discovery["status"] == "passed":
        try:
            discovered_tests = {
                item["name"] for item in json.loads(discovery["output"]).get("tests", [])
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            discovery["status"] = "failed"
            discovery["returncode"] = 1
    missing_tests = sorted(expected_tests - discovered_tests)
    contract_tests = (
        _execute(
            [
                "ctest", "--test-dir", str(build_dir), "--output-on-failure",
                "-R", "^contract::",
            ],
            project_dir,
        )
        if build["returncode"] == 0 and not missing_tests and discovery["status"] == "passed"
        else {
            "status": "failed" if build["returncode"] == 0 else "skipped",
            "returncode": 1,
            "output": "",
            "missing": missing_tests,
        }
    )
    smoke_tests = (
        _execute(
            [
                "ctest", "--test-dir", str(build_dir), "--output-on-failure",
                "-R", "^model_smoke$",
            ],
            project_dir,
        )
        if build["returncode"] == 0
        else {"status": "skipped", "returncode": 1, "output": ""}
    )
    rtl = load_json(paths["facts"] / "rtl.json")
    verilator_status = rtl.get("tools", {}).get("verilator", {}).get("status")
    differential = {
        # Parsing/elaborating RTL alone is not equivalence checking. Keep this
        # blocked until a project supplies shared stimuli and normalization.
        "status": "blocked",
        "reason": (
            "reference RTL elaborated; transaction stimulus adapter is not configured"
            if verilator_status == "passed"
            else "Verilator reference model is unavailable"
        ),
    }
    report = {
        "backend": "local",
        "configure": configure,
        "build": build,
        "test_discovery": discovery,
        "smoke_tests": smoke_tests,
        "contract_tests": contract_tests,
        "differential": differential,
        "status": (
            "passed_with_differential_blocked"
            if smoke_tests["status"] == "passed"
            and contract_tests["status"] == "passed"
            else "failed"
        ),
    }
    dump_json(paths["verification"], report)
    return report
