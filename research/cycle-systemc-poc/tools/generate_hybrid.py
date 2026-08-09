#!/usr/bin/env python3
"""运行 CIRCT elaboration 并生成混合 SystemC manifest 与结构壳。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from hybrid_manifest import ManifestError, apply_config, parse_hw_mlir
from systemc_codegen import generate_wrapper


def _sources(filelist: Path) -> list[Path]:
    sources = []
    for raw_line in filelist.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("+", "-")):
            raise ManifestError(f"首版 filelist 不支持选项：{line}")
        source = (filelist.parent / line).resolve()
        if not source.is_file():
            raise ManifestError(f"RTL 文件不存在：{source}")
        sources.append(source)
    if not sources:
        raise ManifestError("filelist 为空")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--circt-verilog", default="circt-verilog")
    parser.add_argument("--filelist", type=Path, required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()

    try:
        sources = _sources(args.filelist.resolve())
        args.work.mkdir(parents=True, exist_ok=True)
        command = [args.circt_verilog, "--ir-hw", "--top", args.top]
        command.extend(str(source) for source in sources)
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
        core_path = args.work / "core.mlir"
        core_path.write_text(completed.stdout, encoding="utf-8")
        manifest = parse_hw_mlir(completed.stdout, args.top)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        manifest = apply_config(manifest, config)
        manifest["sources"] = [str(source) for source in sources]
        output = args.work / "hierarchy.json"
        output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        generate_wrapper(manifest, args.work / "hybrid_top.hpp")
        print(output)
        return 0
    except (ManifestError, OSError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"hybrid build failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
