from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from .core import _result, _uhdm


def _call(obj: Any, name: str, default: Any = None) -> Any:
    method = getattr(obj, name, None)
    if not callable(method):
        return default
    try:
        return method()
    except (RuntimeError, TypeError):
        return default


def _class_name(obj: Any) -> str:
    return type(obj).__name__.lower().removeprefix("uhdm.")


def _kind(obj: Any) -> str | None:
    name = _class_name(obj)
    if "module_inst" in name:
        return "module"
    if name == "package":
        return "package"
    if name == "port":
        return "port"
    if name == "parameter":
        return "parameter"
    if name == "enum_typespec":
        return "enum"
    if name == "enum_const":
        return "enum-constant"
    if name in {"always", "initial"}:
        return "process"
    if name == "case_stmt":
        return "case"
    if name in {"assign_stmt", "assignment", "cont_assign"}:
        return "assignment"
    if name.endswith(("_var", "_net")) or name in {"logic_var", "variables"}:
        return "variable"
    return None


def _objects(serializer: Any) -> Iterable[Any]:
    objects = serializer.AllObjects()
    if isinstance(objects, dict):
        return objects.keys()
    return objects


def _module_name(obj: Any) -> str:
    parent = _call(obj, "VpiParent")
    while parent is not None:
        if _kind(parent) == "module":
            return str(_call(parent, "VpiName", "") or _call(parent, "VpiDefName", ""))
        parent = _call(parent, "VpiParent")
    return ""


def _direction(value: Any) -> str:
    # IEEE VPI direction constants are stable; unknown values remain explicit.
    return {1: "input", 2: "output", 3: "inout", 4: "mixed", 5: "none"}.get(
        value, "unknown"
    )


def snapshot(path: Path, *, source_root: Path | None = None) -> dict[str, Any]:
    try:
        from uhdm import uhdm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "UHDM Python binding is unavailable; use the eda-uhdm image"
        ) from exc
    serializer = uhdm.Serializer()
    designs = serializer.Restore(str(path.resolve()))
    if not designs:
        raise ValueError("UHDM database contains no design")
    records = []
    for obj in sorted(_objects(serializer), key=lambda item: int(_call(item, "UhdmId", 0))):
        kind = _kind(obj)
        if kind is None:
            continue
        file_value = str(_call(obj, "VpiFile", "") or "")
        if source_root and file_value:
            try:
                file_value = str(Path(file_value).resolve().relative_to(source_root.resolve()))
            except ValueError:
                pass
        parent = _call(obj, "VpiParent")
        record: dict[str, Any] = {
            "id": int(_call(obj, "UhdmId", 0)),
            "kind": kind,
            "name": str(_call(obj, "VpiName", "") or ""),
            "definition": str(_call(obj, "VpiDefName", "") or ""),
            "parent_id": int(_call(parent, "UhdmId", 0)) if parent else None,
            "module": _module_name(obj),
            "file": file_value,
            "line": int(_call(obj, "VpiLineNo", 0)),
            "column": int(_call(obj, "VpiColumnNo", 0)),
            "end_line": int(_call(obj, "VpiEndLineNo", 0)),
            "end_column": int(_call(obj, "VpiEndColumnNo", 0)),
        }
        if kind == "module" and not record["module"]:
            record["module"] = record["name"] or record["definition"]
        if kind == "port":
            record["direction"] = _direction(_call(obj, "VpiDirection", 0))
            record["size"] = int(_call(obj, "VpiSize", 0))
        if kind == "enum-constant":
            record["value"] = str(_call(obj, "VpiValue", "") or "")
            record["decompile"] = str(_call(obj, "VpiDecompile", "") or "")
            record["size"] = int(_call(obj, "VpiSize", 0))
        if kind == "process":
            record["process_type"] = _class_name(obj)
        typespec = _call(obj, "Typespec")
        actual = _call(typespec, "Actual_typespec") if typespec else None
        typespec = actual or typespec
        if typespec:
            record["typespec_id"] = int(_call(typespec, "UhdmId", 0))
            record["typespec_name"] = str(
                _call(typespec, "VpiName", "") or _call(typespec, "VpiDefName", "")
            )
        records.append(record)
    return {
        "schema_version": 1,
        "format": "uhdm-json",
        "source": path.name,
        "objects": records,
    }


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def query_snapshot(
    data: dict[str, Any],
    source_path: Path,
    *,
    kind: str,
    selectors: dict[str, str],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if limit < 1 or limit > 10_000 or offset < 0:
        raise ValueError("limit must be 1..10000 and offset must be non-negative")
    try:
        items = _uhdm(data, kind, selectors)
        status = "ok" if items[offset : offset + limit] else "empty"
        warnings: list[str] = []
    except NotImplementedError:
        items, status = [], "unsupported"
        warnings = [f"{kind} is unsupported by uhdm"]
    page = items[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(items) else None
    return _result(
        "uhdm",
        kind,
        {**selectors, "limit": limit, "offset": offset},
        {
            "path": str(source_path.resolve()),
            "sha256": _digest(source_path),
            "format": "uhdm-binary",
        },
        status,
        page,
        warnings,
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


def _selectors(args: argparse.Namespace) -> dict[str, str]:
    return {
        key: value
        for key, value in {"module": args.module, "name": args.name}.items()
        if value
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eda-uhdm")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("database")
    export.add_argument("--output", required=True)
    export.add_argument("--source-root")
    for name in ("query", "serve"):
        command = commands.add_parser(name)
        command.add_argument("database")
        if name == "query":
            command.add_argument("--kind", required=True)
            command.add_argument("--module")
            command.add_argument("--name")
            command.add_argument("--limit", type=int, default=100)
            command.add_argument("--offset", type=int, default=0)
    commands.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "version":
            from uhdm import uhdm  # type: ignore[import-not-found]

            print(f"eda-uhdm schema 1; binding={uhdm.__file__}")
            return 0
        database = Path(args.database)
        data = snapshot(
            database,
            source_root=Path(args.source_root) if getattr(args, "source_root", None) else None,
        )
        if args.command == "export":
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(output.name + ".tmp")
            temporary.write_text(
                json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(output)
            return 0
        if args.command == "query":
            print(json.dumps(query_snapshot(
                data, database, kind=args.kind, selectors=_selectors(args),
                limit=args.limit, offset=args.offset,
            ), sort_keys=True, ensure_ascii=False))
            return 0
        for line in sys.stdin:
            try:
                request = json.loads(line)
                response = query_snapshot(
                    data,
                    database,
                    kind=request["kind"],
                    selectors=request.get("selectors", {}),
                    limit=int(request.get("limit", 100)),
                    offset=int(request.get("offset", 0)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                response = {"status": "error", "error": str(exc)}
            print(json.dumps(response, sort_keys=True, ensure_ascii=False), flush=True)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
