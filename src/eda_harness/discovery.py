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
from .tool_registry import TOOL_BY_NAME, TOOL_SPECS
from .toolchain import configured_tool


def _probe(name: str) -> dict[str, Any]:
    spec = TOOL_BY_NAME[name]
    candidate, source = configured_tool(name)
    if source.startswith("environment:"):
        resolved = (
            candidate
            if Path(candidate).is_file() and os.access(candidate, os.X_OK)
            else shutil.which(candidate)
        )
    else:
        resolved = next(
            (value for executable in spec.executables if (value := shutil.which(executable))),
            None,
        )
    record: dict[str, Any] = {
        "category": spec.category,
        "capabilities": list(spec.capabilities),
        "available": resolved is not None,
        "source": source,
        "path": str(Path(resolved).resolve()) if resolved else candidate,
    }
    if not resolved:
        record["reason"] = "executable not found"
        record["usable"] = False
        return record
    if not spec.probe_safe:
        record.update({
            "usable": None,
            "probe_status": "not-run",
            "reason": (
                "version probe is disabled because the command may initialize "
                "a licensed tool"
            ),
            "needs_user_confirmation": True,
        })
        return record
    try:
        result = subprocess.run(
            [resolved, *spec.version_arguments],
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
        record["probe_status"] = "passed" if result.returncode == 0 else "failed"
        if result.returncode != 0:
            record["failure_scope"] = "current-execution-environment"
            record["needs_user_confirmation"] = True
    except subprocess.TimeoutExpired:
        record["version"] = "probe timed out"
        record["usable"] = False
        record["probe_status"] = "timeout"
        record["failure_scope"] = "current-execution-environment"
        record["needs_user_confirmation"] = True
    except OSError as exc:
        record["version"] = f"probe failed: {exc}"
        record["usable"] = False
        record["probe_status"] = "failed"
        record["failure_scope"] = "current-execution-environment"
        record["needs_user_confirmation"] = True
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
        "meson": "meson.build",
        "bazel": "MODULE.bazel",
        "register-description": "*.hjson",
        "waveform": "*.vcd",
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
        for name in ("verilator", "slang", "surelog", "vcs", "xrun", "vsim"):
            if tools[name]["usable"]:
                values.append({
                    "capability": f"rtl-{name}",
                    "argv": [name, "<project arguments>"],
                    "basis": f"RTL sources and {name} are available",
                    "limitation": (
                        "project filelists, top and license state still require "
                        "task-aware selection"
                    ),
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


def _capability_matrix(tools: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    matrix: dict[str, dict[str, list[str]]] = {}
    for name, record in tools.items():
        for capability in record["capabilities"]:
            values = matrix.setdefault(
                capability,
                {"usable": [], "unverified": [], "unavailable": []},
            )
            if record["usable"] is True:
                values["usable"].append(name)
            elif record["available"]:
                values["unverified"].append(name)
            else:
                values["unavailable"].append(name)
    return matrix


def _module_environment() -> dict[str, Any]:
    variables = ("MODULESHOME", "MODULEPATH", "LMOD_CMD", "LOADEDMODULES")
    return {
        "configured": any(os.environ.get(name) for name in variables),
        "variables": {name: bool(os.environ.get(name)) for name in variables},
        "loaded_module_count": len(
            [item for item in os.environ.get("LOADEDMODULES", "").split(":") if item]
        ),
        "policy": "module avail/load is not executed automatically",
    }


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


def summarize_discovery(report: dict[str, Any]) -> dict[str, Any]:
    """生成供 Agent 优先读取的紧凑工具与能力摘要。"""
    tools = report["tools"]
    usable_tools = []
    needs_confirmation = []
    for name, record in tools.items():
        if record["usable"] is True:
            usable_tools.append(name)
        elif record["available"]:
            needs_confirmation.append({
                "name": name,
                "probe_status": record.get("probe_status", "unknown"),
                "reason": record.get("reason") or record.get("version", "probe failed"),
                "failure_scope": record.get(
                    "failure_scope", "current-execution-environment"
                ),
            })

    available_capabilities = {}
    for name, values in report["capabilities"].items():
        if values["usable"] or values["unverified"]:
            available_capabilities[name] = {
                "usable": values["usable"],
                "unverified": values["unverified"],
            }

    configured_sdks = sorted(
        name for name, value in report["sdks"].items() if value["configured"]
    )
    available_modules = sorted(
        name
        for name, value in report["python_modules"].items()
        if value["available"]
    )
    container_tools = {
        name: tools[name]
        for name in ("podman", "podman-compose", "docker")
        if name in tools
    }
    container_summary = {
        "usable": sorted(
            name for name, value in container_tools.items() if value["usable"] is True
        ),
        "needs_confirmation": sorted(
            name
            for name, value in container_tools.items()
            if value["available"] and value["usable"] is not True
        ),
        "local_images": sorted(
            name
            for name, value in report["containers"]["images"].items()
            if value["available"]
        ),
    }
    return {
        "schema_version": 1,
        "report_kind": "agent-summary",
        "counts": {
            "registered_tools": len(tools),
            "available_tools": sum(1 for value in tools.values() if value["available"]),
            "probe_passed_tools": len(usable_tools),
            "tools_needing_confirmation": len(needs_confirmation),
            "unavailable_tools": sum(
                1 for value in tools.values() if not value["available"]
            ),
            "available_capabilities": len(available_capabilities),
        },
        "project_signals": report["project_signals"],
        "usable_tools": usable_tools,
        "tools_needing_confirmation": needs_confirmation,
        "available_capabilities": available_capabilities,
        "configured_sdks": configured_sdks,
        "available_python_modules": available_modules,
        "environment_modules": {
            "configured": report["environment_modules"].get("configured", False),
            "loaded_module_count": report["environment_modules"].get(
                "loaded_module_count", 0
            ),
        },
        "containers": container_summary,
        "recommendations": report["recommendations"],
        "limitations": [
            "Probe results describe the current process or sandbox, not every host shell.",
            "A failed probe for an available command requires user confirmation before "
            "declaring the host tool unusable.",
            "A passed version probe does not prove license, feature, or project compatibility.",
            "Only a real project check can establish task-validated status.",
        ],
        "full_report": ".eda-harness/discovery.json",
    }


def discover(root: Path) -> dict[str, Any]:
    """探测本机能力并写出机器可读报告。"""
    root = root.resolve()
    tools = {item.name: _probe(item.name) for item in TOOL_SPECS}
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
            for name in ("pyslang", "uhdm", "edalize", "yaml")
        },
        "sdks": {
            name: {
                "configured": bool(os.environ.get(name)),
                "path_exists": bool(
                    os.environ.get(name)
                    and Path(os.environ[name].split(os.pathsep)[0]).exists()
                ),
            }
            for name in (
                "EDA_SCC_HOME",
                "EDA_SYSTEMC_HOME",
                "VCS_HOME",
                "VERDI_HOME",
                "XCELIUM_HOME",
                "CDS_INST_DIR",
                "QUESTA_HOME",
                "MODELSIM_HOME",
                "ALDEC_HOME",
                "XILINX_VIVADO",
                "QUARTUS_ROOTDIR",
            )
        },
        "license_environment": {
            name: bool(os.environ.get(name))
            for name in (
                "SNPSLMD_LICENSE_FILE",
                "CDS_LIC_FILE",
                "MGLS_LICENSE_FILE",
                "XILINXD_LICENSE_FILE",
                "ALTERAD_LICENSE_FILE",
                "LM_LICENSE_FILE",
            )
        },
    }
    report["environment_modules"] = _module_environment()
    report["containers"] = _container_images(tools)
    report["capabilities"] = _capability_matrix(tools)
    report["recommendations"] = _recommendations(tools, signals)
    output = root / STATE_DIR / "discovery.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = summarize_discovery(report)
    summary_output = root / STATE_DIR / "discovery-summary.json"
    summary_output.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
