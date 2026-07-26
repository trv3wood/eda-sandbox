from __future__ import annotations

"""Command-line entry point for the evidence-to-model workflow.

The CLI intentionally contains orchestration only. Extraction, contract
validation, generation, and verification live in separate modules so that
Codex/Claude adapters and tests use exactly the same deterministic behavior.
"""

import argparse
import json
import sys
from pathlib import Path

from .extractors import extract_project
from .generator import generate_model
from .io import dump_yaml, project_paths
from .verifier import verify_project
from .workflow import (
    approval_is_valid,
    approve,
    create_architecture_draft,
    status,
    validate_architecture,
)


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


def _project(value: str) -> Path:
    # Normalize once at the CLI boundary. All persisted source paths are later
    # made relative to this directory when possible.
    return Path(value).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="systemc-tlm-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a modeling project manifest")
    init.add_argument("project")
    init.add_argument("--name", required=True)
    init.add_argument("--top", required=True, help="target model/DUT top")
    init.add_argument(
        "--reference-top",
        help="existing golden RTL top used by structural EDA tools",
    )
    init.add_argument("--docx", action="append", default=[])
    init.add_argument("--xlsx", action="append", default=[])
    init.add_argument("--rtl", action="append", default=[])
    init.add_argument(
        "--tb", action="append", default=[],
        help="non-synthesizable testbench input (repeatable)",
    )
    init.add_argument("--backend", choices=["auto", "local", "podman"], default="auto")

    extract = subparsers.add_parser("extract", help="extract evidence and design facts")
    extract.add_argument("project")
    extract.add_argument("--skip-tools", action="store_true")

    architect = subparsers.add_parser("architect", help="create or validate contracts")
    architect.add_argument("project")
    architect.add_argument("--validate", action="store_true")

    approve_parser = subparsers.add_parser("approve", help="approve complete contracts")
    approve_parser.add_argument("project")
    approve_parser.add_argument("--approver", required=True)

    generate = subparsers.add_parser("generate", help="generate an approved model")
    generate.add_argument("project")

    verify = subparsers.add_parser("verify", help="compile and test a generated model")
    verify.add_argument("project")
    verify.add_argument("--backend", choices=["auto", "local", "podman"], default="auto")

    run = subparsers.add_parser("run", help="advance the complete workflow")
    run.add_argument("project")
    run.add_argument("--backend", choices=["auto", "local", "podman"], default="auto")
    run.add_argument("--skip-tools", action="store_true")

    status_parser = subparsers.add_parser("status", help="show workflow state")
    status_parser.add_argument("project")
    return parser


def command_init(args: argparse.Namespace) -> dict:
    project_dir = _project(args.project)
    project_dir.mkdir(parents=True, exist_ok=True)
    paths = project_paths(project_dir)
    if paths["manifest"].exists():
        raise FileExistsError(f"{paths['manifest']} already exists")
    # The manifest is the only user-maintained input index. Tool-generated
    # state is kept separately under .systemc-agent/.
    manifest = {
        "schema_version": 1,
        "name": args.name,
        "target_top": args.top,
        "reference_top": getattr(args, "reference_top", None) or args.top,
        "documents": args.docx,
        "registers": args.xlsx,
        "rtl": args.rtl,
        "testbench": getattr(args, "tb", []),
        "backend": args.backend,
    }
    dump_yaml(paths["manifest"], manifest)
    return {"manifest": str(paths["manifest"])}


def command_run(args: argparse.Namespace) -> tuple[dict, int]:
    """Advance until completion or the next mandatory human gate.

    Exit code 2 means the workflow is healthy but intentionally paused for
    architecture completion or approval. Exit code 1 is reserved for errors.
    """
    project_dir = _project(args.project)
    extraction = extract_project(project_dir, run_tools=not args.skip_tools)
    create_architecture_draft(project_dir)
    errors = validate_architecture(project_dir)
    if errors:
        # Generation must not begin while any of the eight contracts or an
        # evidence conflict remains unresolved.
        return {
            "stage": "architecture_gate",
            "extraction": extraction,
            "errors": errors,
            "next": "complete contracts and run approve",
        }, 2
    valid, reason = approval_is_valid(project_dir)
    if not valid:
        # Approval covers source inputs, extracted facts, contracts, and
        # conflict resolutions. Editing any of them invalidates the hash.
        return {
            "stage": "approval_gate",
            "extraction": extraction,
            "reason": reason,
            "next": "run approve",
        }, 2
    generated = generate_model(project_dir)
    verification = verify_project(project_dir, backend=args.backend)
    return {"generated": generated, "verification": verification}, 0


def main(argv: list[str] | None = None) -> int:
    """Parse one command, dispatch it, and emit machine-readable JSON."""
    parser = build_parser()
    args = parser.parse_args(argv)
    project_dir = _project(getattr(args, "project", "."))
    try:
        if args.command == "init":
            result = command_init(args)
        elif args.command == "extract":
            result = extract_project(project_dir, run_tools=not args.skip_tools)
        elif args.command == "architect":
            result = (
                {"errors": validate_architecture(project_dir)}
                if args.validate
                else create_architecture_draft(project_dir)
            )
        elif args.command == "approve":
            result = approve(project_dir, approver=args.approver)
        elif args.command == "generate":
            result = generate_model(project_dir)
        elif args.command == "verify":
            result = verify_project(project_dir, backend=args.backend)
        elif args.command == "run":
            result, returncode = command_run(args)
            _print(result)
            return returncode
        elif args.command == "status":
            result = status(project_dir)
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
        _print(result)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
