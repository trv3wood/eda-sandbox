#!/usr/bin/env python3
"""构建并对拍单体、全 Verilated 分区和混合 SystemC 三种实现。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

from hybrid_manifest import apply_config, parse_hw_mlir
from systemc_codegen import generate_wrapper


POC = Path(__file__).resolve().parents[1]
RTL = POC / "rtl" / "hybrid_stream_accel.sv"
ORIGINAL_RTL = POC / "rtl" / "stream_accel.sv"
CONFIG = POC / "config" / "hybrid.json"
TESTBENCH = POC / "tests" / "hybrid_sc_main.cpp"
NATIVE_SOURCE = POC / "src" / "stream_accumulator_sc.cpp"
INCLUDE = POC / "include"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def generate_stimulus(path: Path, transactions: int, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[list[int]] = []
    rows.extend([[0, 0, 0, 1, 0, 0, 0, 1] for _ in range(3)])
    for transaction in range(transactions):
        length = 1 if transaction == 0 else 255 if transaction == 1 else rng.randint(1, 32)
        scale = 0xffff if transaction == 2 else rng.randrange(0x10000)
        bias = 0xffff if transaction == 2 else rng.randrange(0x10000)
        rows.append([1, 1, length, scale, bias, 0, 0, 1])
        accepted = 0
        while accepted < length:
            valid = rng.random() < 0.75
            sample = rng.randrange(0x10000)
            rows.append([1, 0, length, scale, bias, int(valid), sample, 0])
            if valid:
                accepted += 1
        for _ in range(rng.randint(0, 4)):
            rows.append([1, 0, length, scale, bias, 0, 0, 0])
        rows.append([1, 0, length, scale, bias, 0, 0, 1])
        if transaction in {transactions // 3, (2 * transactions) // 3}:
            # 额外制造 active 状态并异步复位；该事务不计入完成数。
            rows.append([1, 1, 3, scale, bias, 0, 0, 1])
            rows.append([1, 0, 3, scale, bias, 1, rng.randrange(0x10000), 1])
            rows.append([0, 0, 0, scale, bias, 0, 0, 1])
            rows.append([1, 0, 0, scale, bias, 0, 0, 1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["reset_n", "start", "length", "scale", "bias", "in_valid", "in_data", "out_ready"])
        writer.writerows(rows)


def verilator_include(verilator: str) -> Path:
    root = os.environ.get("VERILATOR_ROOT")
    if not root:
        completed = subprocess.run(
            [verilator, "-V"], check=True, text=True, capture_output=True
        )
        match = re.search(r"^\s*VERILATOR_ROOT\s*=\s*(\S+)\s*$", completed.stdout, re.MULTILINE)
        if not match:
            raise RuntimeError("无法从 verilator -V 发现 VERILATOR_ROOT")
        root = match.group(1)
    include = Path(root) / "include"
    if not (include / "verilated.cpp").is_file():
        raise RuntimeError(f"无效的 VERILATOR_ROOT：{root}")
    return include


def verilate(
    verilator: str,
    top: str,
    prefix: str,
    directory: Path,
    source: Path = RTL,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    run([
        verilator, "--sc", "--pins-sc-uint", "--top-module", top,
        "--prefix", prefix, "--Mdir", str(directory), str(source),
    ])
    run(["make", "-C", str(directory), "-f", f"{prefix}.mk", "-j2"])


def compile_sim(
    output: Path,
    header: str,
    class_name: str,
    model_dirs: list[Path],
    prefixes: list[str],
    verilator_include_dir: Path,
    extra_sources: list[Path] | None = None,
    debug_term: bool = False,
) -> None:
    runtime_dir = model_dirs[0]
    command = [
        "c++", "-std=c++17", "-O2", "-pthread", "-DVM_SC=1",
        f'-DDUT_HEADER="{header}"', f"-DDUT_CLASS={class_name}",
    ]
    if debug_term:
        command.append("-DDUT_HAS_DEBUG_TERM=1")
    for include in [verilator_include_dir, verilator_include_dir / "vltstd", INCLUDE, *model_dirs, output.parent]:
        command.extend(["-I", str(include)])
    command.append(str(TESTBENCH))
    command.extend(str(source) for source in (extra_sources or []))
    command.extend(str(directory / f"{prefix}__ALL.a") for directory, prefix in zip(model_dirs, prefixes, strict=True))
    command.extend([
        str(runtime_dir / "verilated.o"),
        str(runtime_dir / "verilated_threads.o"),
        "-lsystemc", "-o", str(output),
    ])
    run(command)


def compare_traces(paths: list[Path]) -> None:
    reference = paths[0].read_bytes()
    for path in paths[1:]:
        if path.read_bytes() != reference:
            run([sys.executable, str(POC / "tools" / "compare_traces.py"), str(paths[0]), str(path)])
            raise RuntimeError(f"trace mismatch: {paths[0]} vs {path}")


def validate_completion_count(stimulus: Path, trace: Path, expected: int) -> None:
    with stimulus.open(encoding="utf-8", newline="") as stimulus_file:
        stimulus_rows = list(csv.DictReader(stimulus_file))
    with trace.open(encoding="utf-8", newline="") as trace_file:
        trace_rows = list(csv.DictReader(trace_file))
    if len(stimulus_rows) != len(trace_rows):
        raise RuntimeError("stimulus 与 trace 周期数不一致")
    completed = 0
    previous_valid = False
    for trace_row in trace_rows:
        current_valid = bool(int(trace_row["out_valid"]))
        if current_valid and not previous_valid:
            completed += 1
        previous_valid = current_valid
    if completed != expected:
        raise RuntimeError(f"期望完成 {expected} 笔事务，实际完成 {completed} 笔")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--circt-verilog", default="circt-verilog")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--transactions", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260809)
    args = parser.parse_args()
    if args.transactions < 3:
        parser.error("--transactions 必须至少为 3")

    try:
        args.work.mkdir(parents=True, exist_ok=True)
        verilator_include_dir = verilator_include(args.verilator)
        completed = subprocess.run(
            [args.circt_verilog, "--ir-hw", "--top", "hybrid_stream_accel", str(RTL)],
            check=True, text=True, capture_output=True,
        )
        manifest = apply_config(
            parse_hw_mlir(completed.stdout, "hybrid_stream_accel"),
            json.loads(CONFIG.read_text(encoding="utf-8")),
        )
        (args.work / "hierarchy.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stimulus = args.work / "stimulus.csv"
        generate_stimulus(stimulus, args.transactions, args.seed)

        golden_dir = args.work / "golden"
        transform_dir = args.work / "transform"
        accumulator_dir = args.work / "accumulator"
        verilate(args.verilator, "stream_accel", "VGolden", golden_dir, ORIGINAL_RTL)
        verilate(args.verilator, "sample_transform", "VSampleTransform", transform_dir)
        verilate(args.verilator, "stream_accumulator", "VStreamAccumulator", accumulator_dir)

        generated = args.work / "generated"
        all_header = generated / "hybrid_all.hpp"
        mixed_header = generated / "hybrid_mixed.hpp"
        class_name = generate_wrapper(manifest, all_header, replacements=False)
        generate_wrapper(manifest, mixed_header, replacements=True)

        golden_exe = args.work / "sim_golden"
        all_exe = args.work / "sim_all_verilated"
        mixed_exe = args.work / "sim_mixed"
        compile_sim(
            golden_exe, "VGolden.h", "VGolden", [golden_dir], ["VGolden"],
            verilator_include_dir,
        )
        compile_sim(
            all_exe, str(all_header), class_name,
            [transform_dir, accumulator_dir], ["VSampleTransform", "VStreamAccumulator"],
            verilator_include_dir,
            debug_term=True,
        )
        compile_sim(
            mixed_exe, str(mixed_header), class_name,
            [transform_dir], ["VSampleTransform"], verilator_include_dir,
            [NATIVE_SOURCE], debug_term=True,
        )

        traces = []
        for executable, name in [
            (golden_exe, "golden"),
            (all_exe, "all_verilated"),
            (mixed_exe, "mixed"),
        ]:
            trace = args.work / f"trace_{name}.csv"
            run([str(executable), str(stimulus), str(trace)])
            traces.append(trace)
        compare_traces(traces)
        validate_completion_count(stimulus, traces[0], args.transactions)
        print(f"hybrid comparison passed: {args.transactions} transactions, seed={args.seed}")
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        print(f"hybrid comparison failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
