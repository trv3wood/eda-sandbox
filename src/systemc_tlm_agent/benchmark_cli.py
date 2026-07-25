from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .benchmark import (
    lock_sources, prepare_workspace, report_benchmark, run_benchmark,
    score_benchmark,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark-systemc-tlm")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("prepare", "create metadata and fetch commands"),
        ("lock", "pin already fetched source checkouts"),
        ("score", "aggregate blind reviewer scores"),
        ("report", "render the Markdown report"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--work", required=True)
    run = sub.add_parser("run", help="plan or execute blinded architect runs")
    run.add_argument("--work", required=True)
    run.add_argument("--model", default="gpt-5.6-luna")
    run.add_argument("--arm", choices=["baseline", "skill"], required=True)
    run.add_argument("--trials", type=int, default=3)
    run.add_argument("--case", action="append", dest="cases")
    run.add_argument("--stage", choices=["architect", "implement"],
                     default="architect")
    run.add_argument("--execute", action="store_true",
                     help="invoke codex; default only writes auditable plans")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work = Path(args.work)
    try:
        if args.command == "prepare":
            result = prepare_workspace(work)
        elif args.command == "lock":
            result = lock_sources(work)
        elif args.command == "run":
            if args.trials < 1:
                raise ValueError("--trials must be positive")
            result = run_benchmark(
                work, model=args.model, arm=args.arm, trials=args.trials,
                cases=args.cases, execute=args.execute, stage=args.stage,
            )
        elif args.command == "score":
            result = score_benchmark(work)
        else:
            result = report_benchmark(work)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (FileNotFoundError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
