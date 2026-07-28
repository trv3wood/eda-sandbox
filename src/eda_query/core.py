from __future__ import annotations

import hashlib
import importlib.resources
import json
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_VERSION = 1
BACKENDS = {"yosys", "verilator"}
STATUSES = {"ok", "empty", "unsupported", "error"}


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source(bundle: Path, backend: str) -> tuple[Path, dict[str, str]]:
    if backend not in BACKENDS:
        raise ValueError(f"unsupported backend: {backend}")
    bundle = bundle.resolve()
    path = (bundle / "tools" / f"{backend}.json").resolve()
    if path.parent != (bundle / "tools").resolve():
        raise ValueError("backend artifact escapes bundle")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path, {
        "path": str(path),
        "sha256": _digest(path),
        "format": f"{backend}-json",
    }


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _locations(attributes: Any, key: str = "src") -> list[str]:
    if not isinstance(attributes, dict):
        return []
    value = attributes.get(key)
    return [str(value)] if value not in (None, "") else []


def _yosys(data: dict[str, Any], kind: str, selectors: dict[str, str]) -> list[dict]:
    modules = data.get("modules", {})
    if not isinstance(modules, dict):
        raise ValueError("Yosys JSON has no modules mapping")
    module_filter = selectors.get("module")
    selected = [
        (name, value)
        for name, value in sorted(modules.items())
        if not module_filter or name == module_filter
    ]
    if kind == "modules":
        return [
            {
                "name": name,
                "source_locations": _locations(module.get("attributes")),
                "pointer": f"/modules/{_pointer_escape(name)}",
            }
            for name, module in selected
        ]
    if kind == "hierarchy":
        names = set(modules)
        return [
            {
                "parent": parent,
                "instance": cell_name,
                "child": cell.get("type"),
                "source_locations": _locations(cell.get("attributes")),
                "pointer": (
                    f"/modules/{_pointer_escape(parent)}/cells/"
                    f"{_pointer_escape(cell_name)}"
                ),
            }
            for parent, module in selected
            for cell_name, cell in sorted(module.get("cells", {}).items())
            if cell.get("type") in names
        ]
    collection = {
        "ports": "ports",
        "cells": "cells",
        "signals": "netnames",
    }.get(kind)
    if collection:
        items = []
        for module_name, module in selected:
            for name, value in sorted(module.get(collection, {}).items()):
                if selectors.get("name") and selectors["name"] != name:
                    continue
                if (
                    kind == "cells"
                    and selectors.get("cell_type")
                    and selectors["cell_type"] != value.get("type")
                ):
                    continue
                item = {
                    "module": module_name,
                    "name": name,
                    "pointer": (
                        f"/modules/{_pointer_escape(module_name)}/{collection}/"
                        f"{_pointer_escape(name)}"
                    ),
                    "source_locations": _locations(value.get("attributes")),
                }
                if kind == "ports":
                    item.update(
                        direction=value.get("direction"),
                        width=len(value.get("bits", [])),
                        bits=value.get("bits", []),
                    )
                elif kind == "cells":
                    item.update(
                        type=value.get("type"),
                        parameters=value.get("parameters", {}),
                        connections=value.get("connections", {}),
                    )
                else:
                    item.update(
                        width=len(value.get("bits", [])),
                        bits=value.get("bits", []),
                        hide_name=value.get("hide_name"),
                    )
                items.append(item)
        return items
    if kind == "source-locations":
        results = []
        for module_name, module in selected:
            base = f"/modules/{_pointer_escape(module_name)}"
            for location in _locations(module.get("attributes")):
                results.append(
                    {
                        "module": module_name,
                        "entity_kind": "module",
                        "name": module_name,
                        "location": location,
                        "pointer": base,
                    }
                )
            for collection_name in ("ports", "cells", "netnames"):
                for name, value in sorted(module.get(collection_name, {}).items()):
                    for location in _locations(value.get("attributes")):
                        results.append(
                            {
                                "module": module_name,
                                "entity_kind": collection_name,
                                "name": name,
                                "location": location,
                                "pointer": (
                                    f"{base}/{collection_name}/{_pointer_escape(name)}"
                                ),
                            }
                        )
        return results
    raise NotImplementedError(kind)


def _walk(value: Any, pointer: str = ""):
    if isinstance(value, dict):
        yield value, pointer
        for key, child in value.items():
            yield from _walk(child, f"{pointer}/{_pointer_escape(str(key))}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{pointer}/{index}")


def _verilator_modules(data: dict[str, Any]) -> list[tuple[dict, str]]:
    return [
        (node, pointer)
        for node, pointer in _walk(data)
        if node.get("type") == "MODULE" and node.get("name")
    ]


def _verilator(
    data: dict[str, Any], kind: str, selectors: dict[str, str]
) -> list[dict]:
    all_modules = _verilator_modules(data)
    modules = [
        pair
        for pair in all_modules
        if not selectors.get("module") or pair[0].get("name") == selectors["module"]
    ]
    if kind == "modules":
        return [
            {
                "name": module["name"],
                "source_locations": [module["loc"]] if module.get("loc") else [],
                "pointer": pointer,
            }
            for module, pointer in modules
        ]
    if kind == "hierarchy":
        results = []
        module_names = {module["name"] for module, _ in all_modules}
        modules_by_address = {
            module["addr"]: module["name"]
            for module, _ in all_modules
            if module.get("addr")
        }
        for module, pointer in modules:
            for node, relative in _walk(module):
                child = (
                    node.get("modName")
                    or node.get("module")
                    or modules_by_address.get(node.get("modp"))
                )
                if node is module or not child or child not in module_names:
                    continue
                results.append(
                    {
                        "parent": module["name"],
                        "instance": node.get("name"),
                        "child": child,
                        "source_locations": [node["loc"]] if node.get("loc") else [],
                        "pointer": pointer + relative,
                    }
                )
        return results
    if kind in {"ports", "signals", "statements", "source-locations"}:
        results = []
        for module, pointer in modules:
            for node, relative in _walk(module):
                if node is module:
                    continue
                node_type = node.get("type")
                is_port = node_type == "VAR" and (
                    node.get("isPrimaryIO")
                    or str(node.get("direction", "")).upper()
                    in {"INPUT", "OUTPUT", "INOUT"}
                )
                if kind == "ports" and not is_port:
                    continue
                if kind == "signals" and node_type != "VAR":
                    continue
                if kind == "statements" and node_type not in {
                    "ALWAYS", "ASSIGN", "ASSIGNDLY", "ASSIGNW", "CASE",
                    "CASEITEM", "IF", "INITIAL", "WHILE",
                }:
                    continue
                if kind == "source-locations" and not node.get("loc"):
                    continue
                if selectors.get("name") and node.get("name") != selectors["name"]:
                    continue
                item = {
                    "module": module["name"],
                    "name": node.get("name"),
                    "node_type": node_type,
                    "pointer": pointer + relative,
                    "source_locations": [node["loc"]] if node.get("loc") else [],
                }
                if kind == "ports":
                    item["direction"] = node.get("direction")
                    item["dtype"] = node.get("dtypep")
                if kind == "source-locations":
                    item["location"] = node["loc"]
                    item["entity_kind"] = node_type
                results.append(item)
        return results
    raise NotImplementedError(kind)


def _result(
    backend: str,
    kind: str,
    selectors: dict[str, Any],
    source: dict[str, str],
    status: str,
    items: list[Any],
    warnings: list[str],
    *,
    truncated: bool = False,
    next_offset: int | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "backend": backend,
        "kind": kind,
        "selectors": selectors,
        "source": source,
        "status": status,
        "items": items,
        "warnings": warnings,
        "truncated": truncated,
        "next_offset": next_offset,
    }
    result["query_id"] = _canonical_digest(result)
    return result


def query_bundle(
    bundle: Path,
    *,
    backend: str,
    kind: str,
    selectors: dict[str, str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if limit < 1 or limit > 10_000 or offset < 0:
        raise ValueError("limit must be 1..10000 and offset must be non-negative")
    path, source = _source(bundle, backend)
    data = json.loads(path.read_text(encoding="utf-8"))
    selectors = {key: value for key, value in (selectors or {}).items() if value}
    try:
        items = (
            _yosys(data, kind, selectors)
            if backend == "yosys"
            else _verilator(data, kind, selectors)
        )
    except NotImplementedError:
        return _result(
            backend, kind, selectors, source, "unsupported", [],
            [f"{kind} is unsupported by {backend}"],
        )
    page = items[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(items) else None
    return _result(
        backend,
        kind,
        {**selectors, "limit": limit, "offset": offset},
        source,
        "ok" if page else "empty",
        page,
        [],
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


def _resolve_pointer(data: Any, pointer: str) -> Any:
    if pointer == "":
        return data
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or start with '/'")
    value = data
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdigit():
                raise ValueError(f"invalid list index in JSON Pointer: {token}")
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError("JSON Pointer traverses a scalar")
    return value


def raw_query(bundle: Path, *, backend: str, pointer: str) -> dict[str, Any]:
    path, source = _source(bundle, backend)
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        item = _resolve_pointer(data, pointer)
    except (IndexError, KeyError) as exc:
        raise ValueError(f"JSON Pointer not found: {pointer}") from exc
    return _result(
        backend, "raw", {"pointer": pointer}, source, "ok", [item], []
    )


def catalog_bundle(bundle: Path) -> dict[str, Any]:
    entries = []
    for backend in sorted(BACKENDS):
        try:
            path, source = _source(bundle, backend)
            data = json.loads(path.read_text(encoding="utf-8"))
            modules = (
                sorted(data.get("modules", {}))
                if backend == "yosys"
                else sorted(module["name"] for module, _ in _verilator_modules(data))
            )
            entries.append({**source, "backend": backend, "modules": modules})
        except FileNotFoundError:
            continue
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle": str(bundle.resolve()),
        "backends": entries,
    }


def validate_result(result: Any, *, verify_source: bool = False) -> None:
    schema_text = (
        importlib.resources.files("eda_query")
        .joinpath("query-result.schema.json")
        .read_text(encoding="utf-8")
    )
    try:
        jsonschema.validate(result, json.loads(schema_text))
    except jsonschema.ValidationError as exc:
        raise ValueError(f"invalid QueryResult: {exc.message}") from exc
    expected = dict(result)
    query_id = expected.pop("query_id")
    if query_id != _canonical_digest(expected):
        raise ValueError("QueryResult query_id does not match its content")
    if verify_source:
        path = Path(result["source"]["path"])
        if not path.is_file() or _digest(path) != result["source"]["sha256"]:
            raise ValueError("QueryResult source is missing or has changed")
