from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tlm_agent.cli import main as tlm_main

from .common import manifest_and_sources
from .generator import apply_rtl_edits, generate_rtl
from .source_index import build_source_index
from .verifier import verify_rtl
from .workflow import (
    RTL_MODES,
    approve_rtl,
    create_rtl_handoff_draft,
    rtl_status,
    validate_rtl_handoff,
)


SHARED_COMMANDS = frozenset({"init", "extract", "graph", "tools"})


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="systemverilog-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    # 实际执行在 main 中按原始 argv 委托给共享 CLI；这里登记用于总帮助。
    for name, help_text in (
        ("init", "create the shared project manifest"),
        ("extract", "extract shared evidence and initialize the graph"),
        ("graph", "build or query the shared canonical graph"),
        ("tools", "finalize shared EDA producer results"),
    ):
        subparsers.add_parser(name, help=help_text)
    architect = subparsers.add_parser("architect", help="create or validate an RTL handoff")
    architect.add_argument("project")
    architect.add_argument("--mode", choices=sorted(RTL_MODES), default="interface")
    architect.add_argument("--validate", action="store_true")
    architect.add_argument("--reset", action="store_true")
    approve = subparsers.add_parser("approve", help="approve the exact RTL handoff")
    approve.add_argument("project")
    approve.add_argument("--approver", required=True)
    for name, help_text in (
        ("source-index", "build the pyslang source index"),
        ("generate", "checkpoint and generate an RTL scaffold or worktree"),
        ("verify", "verify the generated RTL worktree"),
        ("status", "show RTL workflow status"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("project")
    apply_edits = subparsers.add_parser("apply-edits", help="apply bounded edits to the RTL worktree")
    apply_edits.add_argument("project")
    apply_edits.add_argument("edits")
    return parser


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] in SHARED_COMMANDS:
        return tlm_main(values)
    parser = build_parser()
    args = parser.parse_args(values)
    project = Path(args.project).resolve()
    try:
        if args.command == "architect":
            if args.validate:
                result = {"errors": validate_rtl_handoff(project)}
            else:
                _, sources = manifest_and_sources(project)
                source_index = build_source_index(project) if sources else {
                    "node_count": 0, "reason": "no RTL sources",
                }
                result = {
                    "handoff": create_rtl_handoff_draft(
                        project, mode=args.mode, reset=args.reset
                    ),
                    "source_index": source_index,
                }
        elif args.command == "source-index":
            result = build_source_index(project)
        elif args.command == "approve":
            result = approve_rtl(project, approver=args.approver)
        elif args.command == "generate":
            result = generate_rtl(project)
        elif args.command == "apply-edits":
            result = apply_rtl_edits(project, Path(args.edits).resolve())
        elif args.command == "verify":
            result = verify_rtl(project)
        else:
            result = rtl_status(project)
        _print(result)
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
