"""无副作用地发现 EDA、SystemC 与工程构建能力。"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .snapshot import STATE_DIR
from .toolchain import TOOL_VARIABLES, configured_tool


VERSION_ARGS = {
    "vcs": ["-ID"],
    "cmake": ["--version"],
    "ctest": ["--version"],
    "c++": ["--version"],
    "cc": ["--version"],
    "ninja": ["--version"],
    "make": ["--version"],
    "verilator": ["--version"],
    "iverilog": ["-V"],
    "surelog": ["--version"],
    "uhdm-lint": ["--version"],
    "uhdm-hier": ["--version"],
    "eda-uhdm": ["version"],
    "podman": ["--version"],
    "podman-compose": ["--version"],
    "docker": ["--version"],
    "uv": ["--version"],
    "git": ["--version"],
}


def _probe(name: str) -> dict[str, Any]:
    candidate, source = configured_tool(name)
    resolved = (
        candidate
        if Path(candidate).is_file() and os.access(candidate, os.X_OK)
        else shutil.which(candidate)
    )
    record: dict[str, Any] = {
        "available": resolved is not None,
        "source": source,
        "path": str(Path(resolved).resolve()) if resolved else candidate,
    }
    if not resolved:
        record["reason"] = "executable not found"
        record["usable"] = False
        return record
    try:
        result = subprocess.run(
            [resolved, *VERSION_ARGS[name]],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        record["version"] = lines[0][:500] if lines else "unknown"
        record["version_probe_returncode"] = result.returncode
        record["usable"] = result.returncode == 0
    except subprocess.TimeoutExpired:
        record["version"] = "probe timed out"
        record["usable"] = False
    except OSError as exc:
        record["version"] = f"probe failed: {exc}"
        record["usable"] = False
    return record


def _signals(root: Path) -> list[str]:
    patterns = {
        "cmake": "CMakeLists.txt",
        "make": "Makefile",
        "fusesoc": "*.core",
        "systemverilog": "*.sv",
        "verilog": "*.v",
        "systemc": "*.cpp",
        "filelist": "*.f",
        "python": "pyproject.toml",
    }
    found = []
    for name, pattern in patterns.items():
        if any(root.rglob(pattern)):
            found.append(name)
    return found


def _recommendations(tools: dict[str, Any], signals: list[str]) -> list[dict[str, Any]]:
    values = []
    if "cmake" in signals and tools["cmake"]["usable"]:
        values.append({
            "capability": "cmake-build-test",
            "argv": ["cmake", "-S", ".", "-B", "build"],
            "follow_up": [
                ["cmake", "--build", "build", "--parallel"],
                ["ctest", "--test-dir", "build", "--output-on-failure"],
            ],
            "basis": "CMakeLists.txt and CMake are available",
        })
    if {"systemverilog", "verilog"} & set(signals):
        for name in ("verilator", "surelog", "vcs"):
            if tools[name]["usable"]:
                values.append({
                    "capability": f"rtl-{name}",
                    "argv": [name, "<project arguments>"],
                    "basis": f"RTL sources and {name} are available",
                    "limitation": "project filelists, top and license state still require task-aware selection",
                })
    if os.environ.get("EDA_SCC_HOME"):
        values.append({
            "capability": "scc-local",
            "argv": ["cmake", "-S", ".", "-B", "build"],
            "basis": "EDA_SCC_HOME is configured",
        })
    elif tools["podman"]["usable"] or tools["docker"]["usable"]:
        values.append({
            "capability": "scc-container-candidate",
            "argv": ["scripts/eda-run", "scc", "--shell"],
            "basis": "container engine is available",
            "limitation": "discover does not pull or start images",
        })
    return values


def _container_images(tools: dict[str, Any]) -> dict[str, Any]:
    engine = "podman" if tools["podman"]["usable"] else (
        "docker" if tools["docker"]["usable"] else None
    )
    images = {
        "uhdm": os.environ.get("EDA_UHDM_IMAGE", "ghcr.io/trv3wood/eda-uhdm:main"),
        "rtl": os.environ.get("EDA_RTL_IMAGE", "ghcr.io/trv3wood/eda-rtl:main"),
        "scc": os.environ.get("EDA_SCC_IMAGE", "ghcr.io/trv3wood/eda-scc:main"),
        "rocky": os.environ.get("EDA_ROCKY_IMAGE", "ghcr.io/trv3wood/eda-scc-rocky8:main"),
    }
    if engine is None:
        return {
            "engine": None,
            "images": {
                name: {"image": value, "available": False}
                for name, value in images.items()
            },
        }
    executable = tools[engine]["path"]
    records = {}
    for name, image in images.items():
        command = (
            [executable, "image", "exists", image]
            if engine == "podman"
            else [executable, "image", "inspect", image]
        )
        try:
            result = subprocess.run(
                command, check=False, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5,
            )
            available = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            available = False
        records[name] = {"image": image, "available": available}
    return {"engine": engine, "images": records, "policy": "local inspection only; no pull"}


def discover(root: Path) -> dict[str, Any]:
    """探测本机能力并写出机器可读报告。"""
    root = root.resolve()
    tools = {name: _probe(name) for name in TOOL_VARIABLES}
    signals = _signals(root)
    report = {
        "schema_version": 1,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "project_signals": signals,
        "tools": tools,
        "python_modules": {
            name: {"available": importlib.util.find_spec(name) is not None}
            for name in ("pyslang", "yaml")
        },
        "sdks": {
            name: {
                "configured": bool(os.environ.get(name)),
                "path_exists": bool(
                    os.environ.get(name)
                    and Path(os.environ[name].split(os.pathsep)[0]).exists()
                ),
            }
            for name in ("EDA_SCC_HOME", "EDA_SYSTEMC_HOME", "VCS_HOME")
        },
        "license_environment": {
            name: bool(os.environ.get(name))
            for name in ("SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE")
        },
    }
    report["containers"] = _container_images(tools)
    report["recommendations"] = _recommendations(tools, signals)
    output = root / STATE_DIR / "discovery.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
