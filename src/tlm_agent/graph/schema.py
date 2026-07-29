from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

GRAPH_SCHEMA_VERSION = 1

SPEC_ENTITY_TYPES = {
    "Section",
    "Requirement",
    "Interface",
    "Transaction",
    "Register",
    "Field",
    "State",
    "Constraint",
    "Error",
    "Observable",
}
SPEC_RELATION_TYPES = {
    "CONTAINS",
    "DEFINES",
    "REQUIRES",
    "CONSTRAINS",
    "TRANSITIONS_TO",
    "RAISES",
    "OBSERVES",
}
RTL_ENTITY_TYPES = {
    "File",
    "Module",
    "Instance",
    "Port",
    "Signal",
    "Parameter",
    "Package",
}
RTL_RELATION_TYPES = {
    "DECLARES",
    "INSTANTIATES",
    "OF",
    "BINDS",
    "CONNECTS",
    "IMPORTS",
    "LOCATED_IN",
}
CROSS_RELATION_TYPES = {"MENTIONS", "CORRESPONDS_TO"}


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_id(prefix: str, identity: Any) -> str:
    return f"{prefix}-{canonical_digest(identity)[:20]}"


def entity(
    *,
    entity_type: str,
    name: str,
    description: str = "",
    properties: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any],
    identity: Any | None = None,
) -> dict[str, Any]:
    value = {
        "type": entity_type,
        "name": name,
        "description": " ".join(description.split()),
        "properties": properties or {},
        "source_refs": source_refs or [],
        "provenance": provenance,
    }
    value["id"] = stable_id(
        "ent",
        identity if identity is not None else value,
    )
    return value


def relationship(
    *,
    relation_type: str,
    source_id: str,
    target_id: str,
    description: str = "",
    properties: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    value = {
        "type": relation_type,
        "source_id": source_id,
        "target_id": target_id,
        "description": " ".join(description.split()),
        "properties": properties or {},
        "source_refs": source_refs or [],
        "provenance": provenance,
    }
    value["id"] = stable_id("rel", value)
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    values = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} must contain a JSON object")
        values.append(value)
    return values


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(values, key=lambda item: item["id"])
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            for value in ordered:
                stream.write(
                    json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
                )
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def validate_graph(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    entity_ids: set[str] = set()
    relation_ids: set[str] = set()
    for item in entities:
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append("entity id is required")
            continue
        if identifier in entity_ids:
            errors.append(f"duplicate entity id {identifier}")
        entity_ids.add(identifier)
        if item.get("type") not in SPEC_ENTITY_TYPES | RTL_ENTITY_TYPES:
            errors.append(f"{identifier}: unsupported entity type {item.get('type')}")
        if not isinstance(item.get("source_refs"), list):
            errors.append(f"{identifier}: source_refs must be a list")
    for item in relationships:
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append("relationship id is required")
            continue
        if identifier in relation_ids:
            errors.append(f"duplicate relationship id {identifier}")
        relation_ids.add(identifier)
        if item.get("type") not in (
            SPEC_RELATION_TYPES | RTL_RELATION_TYPES | CROSS_RELATION_TYPES
        ):
            errors.append(
                f"{identifier}: unsupported relationship type {item.get('type')}"
            )
        for endpoint in ("source_id", "target_id"):
            if item.get(endpoint) not in entity_ids:
                errors.append(
                    f"{identifier}: {endpoint} does not resolve to an entity"
                )

    of_counts: dict[str, int] = {}
    instantiated: set[str] = set()
    for item in relationships:
        if item.get("type") == "OF":
            of_counts[item["source_id"]] = of_counts.get(item["source_id"], 0) + 1
        elif item.get("type") == "INSTANTIATES":
            instantiated.add(item["target_id"])
    for item in entities:
        if item.get("type") != "Instance":
            continue
        count = of_counts.get(item["id"], 0)
        if count != 1:
            errors.append(f"{item['id']}: Instance requires exactly one OF edge")
        if not item.get("properties", {}).get("is_top") and item["id"] not in instantiated:
            errors.append(f"{item['id']}: non-top Instance is orphaned")

    located = {
        item["source_id"]
        for item in relationships
        if item.get("type") == "LOCATED_IN"
    }
    eligible = [
        item
        for item in entities
        if item.get("type") not in {"File"}
        and item.get("provenance", {}).get("source_backed", True)
    ]
    located_count = sum(
        item["id"] in located or bool(item.get("source_refs"))
        for item in eligible
    )
    if eligible and located_count != len(eligible):
        warnings.append(
            f"{len(eligible) - located_count} source-backed entities lack LOCATED_IN"
        )
    return {
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "metrics": {
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "source_location_coverage": (
                located_count / len(eligible) if eligible else 1.0
            ),
        },
    }
