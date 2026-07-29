from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .schema import (
    canonical_digest,
    read_jsonl,
    relationship,
    validate_graph,
    write_jsonl,
)
from ..io import dump_json, file_digest, load_json
from .rtl_graph import structure_to_graph


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "sha256": file_digest(path),
        "size": path.stat().st_size,
    }


def align_cross_source(
    spec_entities: list[dict[str, Any]],
    rtl_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in rtl_entities:
        name = item.get("name")
        if isinstance(name, str) and name:
            by_name.setdefault(name, []).append(item)
    unique = {
        name: values[0] for name, values in by_name.items() if len(values) == 1
    }
    provenance = {
        "extractor": "exact-cross-source-aligner/1",
        "deterministic": True,
        "source_backed": True,
    }
    result = []
    for spec in spec_entities:
        name = spec.get("name")
        target = unique.get(name)
        if target:
            result.append(
                relationship(
                    relation_type="CORRESPONDS_TO",
                    source_id=spec["id"],
                    target_id=target["id"],
                    properties={"match": "unique_exact_name", "text": name},
                    source_refs=spec.get("source_refs", []),
                    provenance=provenance,
                )
            )
        texts = [
            ref.get("text", "") for ref in spec.get("source_refs", [])
        ]
        for alias, rtl in unique.items():
            if alias == name or not alias:
                continue
            pattern = rf"(?<![A-Za-z0-9_$]){re.escape(alias)}(?![A-Za-z0-9_$])"
            if any(re.search(pattern, text) for text in texts):
                result.append(
                    relationship(
                        relation_type="MENTIONS",
                        source_id=spec["id"],
                        target_id=rtl["id"],
                        properties={"match": "unique_exact_token", "text": alias},
                        source_refs=spec.get("source_refs", []),
                        provenance=provenance,
                    )
                )
    return result


def finalize_graph(
    project: Path,
    *,
    structure: dict[str, Any] | None,
    sources: list[Path],
) -> dict[str, Any]:
    graph = project / ".systemc-agent" / "graph"
    manifest = load_json(graph / "manifest.json")
    spec_status = manifest.get("producers", {}).get("spec", {}).get("status")
    if spec_status not in {"passed", "skipped"}:
        raise ValueError("Spec graph producer is pending; run eda-spec-produce")
    rtl_status = manifest.get("producers", {}).get("rtl", {}).get("status")
    if structure is not None:
        rtl_entities, rtl_relationships, limitations = structure_to_graph(
            structure, project, sources
        )
        write_jsonl(graph / "rtl_entities.jsonl", rtl_entities)
        write_jsonl(graph / "rtl_relationships.jsonl", rtl_relationships)
        manifest["producers"]["rtl"] = {
            "status": "passed",
            "entity_count": len(rtl_entities),
            "relationship_count": len(rtl_relationships),
            "limitations": limitations,
        }
    elif rtl_status not in {"passed", "skipped"}:
        raise ValueError("RTL graph producer is pending")

    spec_entities = read_jsonl(graph / "spec_entities.jsonl")
    spec_relationships = read_jsonl(graph / "spec_relationships.jsonl")
    rtl_entities = read_jsonl(graph / "rtl_entities.jsonl")
    rtl_relationships = read_jsonl(graph / "rtl_relationships.jsonl")
    cross = align_cross_source(spec_entities, rtl_entities)
    write_jsonl(graph / "cross_source_relationships.jsonl", cross)
    manifest["producers"]["cross_source"] = {
        "status": "passed",
        "relationship_count": len(cross),
        "strategy": "unique_exact_name_and_token",
    }
    entities = [*spec_entities, *rtl_entities]
    relationships = [*spec_relationships, *rtl_relationships, *cross]
    write_jsonl(graph / "entities.jsonl", entities)
    write_jsonl(graph / "relationships.jsonl", relationships)
    validation = validate_graph(entities, relationships)

    top_instances = [
        item
        for item in entities
        if item.get("type") == "Instance"
        and item.get("properties", {}).get("is_top")
    ]
    if structure is not None and len(top_instances) != 1:
        validation["errors"].append(
            f"expected exactly one elaborated top Instance, found {len(top_instances)}"
        )
    validation["errors"] = sorted(set(validation["errors"]))
    artifact_names = (
        "document_tree.json",
        "text_units.jsonl",
        "spec_entities.jsonl",
        "spec_relationships.jsonl",
        "rtl_entities.jsonl",
        "rtl_relationships.jsonl",
        "cross_source_relationships.jsonl",
        "entities.jsonl",
        "relationships.jsonl",
    )
    manifest["artifacts"] = {
        name: _artifact(graph / name) for name in artifact_names
    }
    manifest["validation"] = validation
    manifest["status"] = "failed" if validation["errors"] else "ready"
    manifest["content_digest"] = canonical_digest({
        name: value["sha256"] for name, value in manifest["artifacts"].items()
    })
    dump_json(graph / "manifest.json", manifest)
    if validation["errors"]:
        raise ValueError(
            "Graph finalization failed:\n- " + "\n- ".join(validation["errors"])
        )
    return manifest
