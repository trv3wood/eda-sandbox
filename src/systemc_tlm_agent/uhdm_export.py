from __future__ import annotations

"""Export deterministic structural facts through the official UHDM binding."""

from pathlib import Path
from typing import Any, Iterator

from .io import file_digest


def _scan(uhdm: Any, relation: int, handle: Any) -> Iterator[Any]:
    iterator = uhdm.vpi_iterate(relation, handle)
    while iterator:
        item = uhdm.vpi_scan(iterator)
        if item is None:
            break
        yield item


def _scan_named_relations(
    uhdm: Any, relation_names: tuple[str, ...], handle: Any
) -> Iterator[Any]:
    seen: set[int] = set()
    for name in relation_names:
        relation = getattr(uhdm, name, None)
        if relation is None:
            continue
        for item in _scan(uhdm, relation, handle):
            identity = id(item)
            if identity in seen:
                continue
            seen.add(identity)
            yield item


def _string(uhdm: Any, property_id: int, handle: Any) -> str | None:
    value = uhdm.vpi_get_str(property_id, handle)
    return str(value) if value is not None else None


def _integer(uhdm: Any, property_id: int, handle: Any) -> int | None:
    value = int(uhdm.vpi_get(property_id, handle))
    return value if value != 0 else None


def _source_record(path_text: str | None, sources: list[Path]) -> dict[str, Any]:
    if path_text:
        candidate = Path(path_text)
        if candidate.is_file():
            return {"path": str(candidate), "sha256": file_digest(candidate)}
        normalized = candidate.as_posix()
        matches = [
            source
            for source in sources
            if normalized.endswith(source.as_posix())
            or normalized.endswith("/" + source.name)
        ]
        if len(matches) == 1:
            return {"path": str(matches[0]), "sha256": file_digest(matches[0])}
    return {"path": path_text, "sha256": None}


def _location(uhdm: Any, handle: Any, sources: list[Path]) -> dict[str, Any]:
    source = _source_record(_string(uhdm, uhdm.vpiFile, handle), sources)
    source["line"] = _integer(uhdm, uhdm.vpiLineNo, handle)
    return source


def _named_object(uhdm: Any, handle: Any, sources: list[Path]) -> dict[str, Any]:
    result = {
        "name": _string(uhdm, uhdm.vpiName, handle),
        **_location(uhdm, handle, sources),
    }
    size = _integer(uhdm, uhdm.vpiSize, handle)
    if size is not None:
        result["size"] = size
    return result


def _port(uhdm: Any, handle: Any, sources: list[Path]) -> dict[str, Any]:
    result = _named_object(uhdm, handle, sources)
    direction = int(uhdm.vpi_get(uhdm.vpiDirection, handle))
    directions = {
        int(getattr(uhdm, "vpiInput", -1)): "input",
        int(getattr(uhdm, "vpiOutput", -2)): "output",
        int(getattr(uhdm, "vpiInout", -3)): "inout",
        int(getattr(uhdm, "vpiMixedIO", -4)): "mixed",
        int(getattr(uhdm, "vpiNoDirection", -5)): "none",
    }
    result["direction"] = directions.get(direction, f"unknown:{direction}")
    handle_function = getattr(uhdm, "vpi_handle", None)
    if handle_function:
        for property_name, result_name in (
            ("vpiHighConn", "high_conn"),
            ("vpiLowConn", "low_conn"),
        ):
            property_id = getattr(uhdm, property_name, None)
            if property_id is None:
                continue
            connection = handle_function(property_id, handle)
            if connection is not None:
                name = _string(uhdm, uhdm.vpiName, connection)
                if name:
                    result[result_name] = name
    return result


def _module(
    uhdm: Any, handle: Any, sources: list[Path], *, include_children: bool
) -> dict[str, Any]:
    result = _named_object(uhdm, handle, sources)
    result["definition"] = _string(uhdm, uhdm.vpiDefName, handle)
    result["ports"] = [
        _port(uhdm, item, sources) for item in _scan(uhdm, uhdm.vpiPort, handle)
    ]
    result["parameters"] = [
        _named_object(uhdm, item, sources)
        for item in _scan(uhdm, uhdm.vpiParameter, handle)
    ]
    result["signals"] = [
        _named_object(uhdm, item, sources)
        for item in _scan_named_relations(
            uhdm, ("vpiNet", "vpiReg", "vpiVariables"), handle
        )
    ]
    result["imports"] = [
        _named_object(uhdm, item, sources)
        for item in _scan_named_relations(
            uhdm, ("vpiImport", "vpiImportedPackage"), handle
        )
    ]
    result["instances"] = []
    if include_children:
        result["instances"] = [
            _module(uhdm, item, sources, include_children=True)
            for item in _scan(uhdm, uhdm.vpiModule, handle)
        ]
    return result


def _unqualified(value: str | None) -> str:
    return (value or "").rsplit("@", 1)[-1]


def export_uhdm_structure(
    database: Path, sources: list[Path], reference_top: str
) -> dict[str, Any]:
    """Restore one UHDM database and export definition and elaborated views."""
    try:
        import uhdm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "UHDM Python binding is unavailable; use the eda-uhdm image"
        ) from exc

    serializer = uhdm.Serializer()
    roots = serializer.Restore(str(database))
    if not roots:
        raise RuntimeError("UHDM database contains no design root")
    design = roots[0]
    definitions = [
        _module(uhdm, item, sources, include_children=True)
        for item in _scan(uhdm, uhdm.uhdmallModules, design)
    ]
    top_modules = [
        _module(uhdm, item, sources, include_children=True)
        for item in _scan(uhdm, uhdm.uhdmtopModules, design)
    ]
    packages = [
        _named_object(uhdm, item, sources)
        for item in _scan_named_relations(
            uhdm, ("uhdmallPackages", "vpiPackage"), design
        )
    ]
    if not any(
        reference_top
        in {
            _unqualified(module.get("name")),
            _unqualified(module.get("definition")),
        }
        for module in top_modules
    ):
        raise RuntimeError(f"UHDM elaborated view does not contain top {reference_top}")
    return {
        "schema_version": 1,
        "backend": "uhdm-python-vpi",
        "database": {
            "path": str(database),
            "sha256": file_digest(database),
            "size": database.stat().st_size,
        },
        "reference_top": reference_top,
        "top_modules": top_modules,
        "modules": definitions,
        "packages": packages,
    }
