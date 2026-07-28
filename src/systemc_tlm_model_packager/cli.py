from __future__ import annotations

"""Command-line entry point for standalone generated-model packaging."""

import argparse
import json
import sys
from pathlib import Path

from .packager import package_model


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="systemc-tlm-package")
    parser.add_argument("project", help="generated modeling project directory")
    parser.add_argument("--output", help="output .tar.gz path (defaults to PROJECT)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Package one generated model and print its manifest as JSON."""
    args = build_parser().parse_args(argv)
    try:
        result = package_model(
            Path(args.project), Path(args.output).resolve() if args.output else None
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
