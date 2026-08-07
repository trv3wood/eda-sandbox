#!/usr/bin/env python3
"""逐项执行 CIRCT 五阶段探针，并生成结构化 JSON 报告。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


CASES = {
    "comb": ("comb.sv", "comb"),
    "hierarchy": ("child.sv", "hierarchy"),
    "counter": ("counter.sv", "counter"),
    "fsm": ("fsm.sv", "fsm"),
    "memory": ("memory.sv", "memory"),
    "parameterized": ("parameterized.sv", "parameterized"),
    "inout": ("inout.sv", "inout_probe"),
    "stream_accel": ("stream_accel.sv", "stream_accel"),
}


def run(stage: str, argv: list[str], log: Path,
        stdout_path: Path | None = None) -> dict:
    completed = subprocess.run(
        argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode == 0 and stdout_path is not None:
        stdout_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "stage": stage,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "argv": argv,
        "log": str(log),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--systemc-cxxflags", default=os.environ.get("SYSTEMC_CXXFLAGS", ""))
    args = parser.parse_args()

    required = ["circt-verilog", "circt-opt", "circt-translate"]
    missing = [tool for tool in required if shutil.which(tool) is None]
    report: dict = {"schema_version": 1, "cases": {}}
    if missing:
        for name, (_, top) in CASES.items():
            stages = []
            reason = f"缺少工具: {', '.join(missing)}"
            for stage in ("frontend", "conversion", "emission", "compile", "run"):
                stages.append({"stage": stage, "status": "blocked", "reason": reason})
            report["cases"][name] = {"top": top, "stages": stages}
        report.update({"status": "blocked", "reason": "缺少工具", "missing": missing})
        args.work.mkdir(parents=True, exist_ok=True)
        (args.work / "feature-ladder.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    root = Path(__file__).resolve().parents[1]
    rtl = root / "rtl"
    args.work.mkdir(parents=True, exist_ok=True)
    for name, (filename, top) in CASES.items():
        case_dir = args.work / name
        case_dir.mkdir(exist_ok=True)
        core_ir = case_dir / "core.mlir"
        systemc_ir = case_dir / "systemc.mlir"
        generated = case_dir / "generated.hpp"
        stages = []

        stages.append(run("frontend", [
            "circt-verilog", str(rtl / filename), "--top", top,
        ], case_dir / "frontend.log", core_ir))
        if stages[-1]["status"] == "passed":
            stages.append(run("conversion", [
                "circt-opt", str(core_ir), "--convert-hw-to-systemc",
            ], case_dir / "conversion.log", systemc_ir))
        if stages[-1]["status"] == "passed" and len(stages) == 2:
            stages.append(run("emission", [
                "circt-translate", str(systemc_ir), "--export-systemc",
            ], case_dir / "emission.log", generated))

        if len(stages) == 3 and stages[-1]["status"] == "passed":
            compiler = shutil.which("c++")
            if compiler is None or not args.systemc_cxxflags:
                stages.append({
                    "stage": "compile",
                    "status": "blocked",
                    "reason": "需要 c++ 和 SYSTEMC_CXXFLAGS 才能编译生成代码",
                })
            else:
                smoke = case_dir / "smoke.cpp"
                smoke.write_text(
                    f'#include "{generated.name}"\nint sc_main(int, char**) {{ return 0; }}\n',
                    encoding="utf-8",
                )
                stages.append(run("compile",
                    [compiler, *args.systemc_cxxflags.split(), "-fsyntax-only", str(smoke)],
                    case_dir / "compile.log",
                ))
        while len(stages) < 4:
            stages.append({
                "stage": ("frontend", "conversion", "emission", "compile")[len(stages)],
                "status": "blocked",
                "reason": "上游阶段未通过",
            })
        stages.append({
            "stage": "run",
            "status": "blocked",
            "reason": "需要为生成模块接入逐用例 SystemC sc_main",
        })
        report["cases"][name] = {"top": top, "stages": stages}

    statuses = [stage["status"] for case in report["cases"].values() for stage in case["stages"]]
    report["status"] = "failed" if "failed" in statuses else (
        "blocked" if "blocked" in statuses else "passed"
    )
    (args.work / "feature-ladder.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
