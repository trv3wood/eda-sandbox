from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .core import catalog_bundle, query_bundle, raw_query


def _write(data: dict, output: str | None) -> None:
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not output:
        print(text, end="")
        return
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        Path(temporary).replace(destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eda-query")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("bundle")
    catalog.add_argument("--output")
    query = commands.add_parser("query")
    query.add_argument("bundle")
    query.add_argument(
        "--backend", choices=["uhdm", "yosys", "verilator"], required=True
    )
    query.add_argument("--kind", required=True)
    query.add_argument("--module")
    query.add_argument("--name")
    query.add_argument("--cell-type")
    query.add_argument("--limit", type=int, default=100)
    query.add_argument("--offset", type=int, default=0)
    query.add_argument("--output")
    raw = commands.add_parser("raw")
    raw.add_argument("bundle")
    raw.add_argument(
        "--backend", choices=["uhdm", "yosys", "verilator"], required=True
    )
    raw.add_argument("--pointer", required=True)
    raw.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "catalog":
            result = catalog_bundle(Path(args.bundle))
        elif args.command == "query":
            result = query_bundle(
                Path(args.bundle),
                backend=args.backend,
                kind=args.kind,
                selectors={
                    "module": args.module,
                    "name": args.name,
                    "cell_type": args.cell_type,
                },
                limit=args.limit,
                offset=args.offset,
            )
        else:
            result = raw_query(
                Path(args.bundle), backend=args.backend, pointer=args.pointer
            )
        _write(result, args.output)
        return 0
    except (FileNotFoundError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
