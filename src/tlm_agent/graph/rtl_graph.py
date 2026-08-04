"""将经过门禁的 EDA 结构快照转换为 canonical RTL 图事实。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..io import file_digest, relative_to_project
from .schema import entity, relationship


def _unqualified(value: object) -> str:
    """去掉可选的 SystemVerilog 库限定名。"""
    return str(value or "").rsplit("@", 1)[-1]


def _records(value: object, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"RTL structure field {field} must be a list of objects")
    return value


def _source_ref(
    record: dict[str, Any], project: Path, sources: list[Path],
    source_digests: Mapping[Path, str] | None = None,
) -> list[dict[str, Any]]:
    path_text = record.get("path")
    recorded_digest = record.get("sha256")
    source = next(
        (
            candidate for candidate in sources
            if str(candidate) == path_text
            or candidate.name == Path(str(path_text or "")).name
            or (
                isinstance(recorded_digest, str)
                and recorded_digest == (
                    source_digests[candidate]
                    if source_digests is not None
                    else file_digest(candidate)
                )
            )
        ),
        None,
    )
    if source is None:
        return []
    line = record.get("line")
    locator = f"line:{line}" if isinstance(line, int) and line > 0 else "unknown"
    return [{
        "source_path": relative_to_project(project, source),
        "source_digest": (
            source_digests[source]
            if source_digests is not None
            else file_digest(source)
        ),
        "locator": locator,
        **({"line": line} if isinstance(line, int) and line > 0 else {}),
    }]


def structure_to_graph(
    structure: dict[str, Any], project: Path, sources: list[Path]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """从经过验证的商业或开源 EDA 结构快照创建 RTL 图。

    The export contains both definition and elaborated views.  Definitions own
    ports, signals, parameters, and imports; elaborated modules become Instance
    nodes linked to their definition by ``OF`` and to their parent by
    ``INSTANTIATES``.
    """
    if not isinstance(structure, dict):
        raise ValueError("RTL structure must be a JSON object")
    backend = structure.get("backend")
    if backend not in {"vcs-vpi", "uhdm-python-vpi"}:
        raise ValueError(f"unsupported RTL structure backend: {backend}")
    modules = _records(structure.get("modules"), "modules")
    top_modules = _records(structure.get("top_modules"), "top_modules")
    packages = _records(structure.get("packages"), "packages")
    if not modules or not top_modules:
        raise ValueError("RTL structure must contain definition and top modules")

    project = project.resolve()
    sources = sorted((path.resolve() for path in sources), key=str)
    # 一次图构建内输入文件是已门禁的不可变快照；缓存摘要避免每个未匹配
    # 的 VPI 记录重新读取所有源文件。
    source_digests = {source: file_digest(source) for source in sources}
    provenance = {
        "extractor": f"{backend}-graph/1",
        "backend": backend,
        "deterministic": True,
        "source_backed": True,
    }
    entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    files: dict[Path, dict[str, Any]] = {}
    definitions: dict[str, dict[str, Any]] = {}
    package_nodes: dict[str, dict[str, Any]] = {}

    for source in sources:
        ref = {
            "source_path": relative_to_project(project, source),
            "source_digest": source_digests[source],
            "locator": "file",
        }
        node = entity(
            entity_type="File", name=source.name,
            properties={"path": ref["source_path"], "sha256": ref["source_digest"]},
            source_refs=[ref], provenance=provenance,
            identity={"kind": "File", "path": ref["source_path"], "sha256": ref["source_digest"]},
        )
        files[source] = node
        entities.append(node)

    def locate(node: dict[str, Any], refs: list[dict[str, Any]]) -> None:
        if not refs:
            return
        source_path = refs[0]["source_path"]
        target = next(
            (file_node for path, file_node in files.items()
             if relative_to_project(project, path) == source_path),
            None,
        )
        if target is not None:
            relationships.append(relationship(
                relation_type="LOCATED_IN", source_id=node["id"], target_id=target["id"],
                source_refs=refs, provenance=provenance,
            ))

    def add_definition(record: dict[str, Any]) -> dict[str, Any]:
        raw_definition = record.get("definition") or record.get("name")
        name = _unqualified(raw_definition)
        if not name:
            raise ValueError("RTL module definition is missing a name")
        existing = definitions.get(name)
        if existing is not None:
            return existing
        refs = _source_ref(record, project, sources, source_digests)
        node = entity(
            entity_type="Module", name=name,
            properties={"definition": str(raw_definition)}, source_refs=refs,
            provenance=provenance, identity={"kind": "Module", "definition": str(raw_definition)},
        )
        definitions[name] = node
        entities.append(node)
        locate(node, refs)
        for field, entity_type, properties in (
            ("ports", "Port", lambda item: {key: item[key] for key in ("direction", "size") if key in item}),
            ("parameters", "Parameter", lambda item: {key: item[key] for key in ("size",) if key in item}),
            ("signals", "Signal", lambda item: {key: item[key] for key in ("size",) if key in item}),
        ):
            for child in _records(record.get(field), field):
                child_name = child.get("name")
                if not isinstance(child_name, str) or not child_name:
                    raise ValueError(f"RTL {field} entry is missing a name")
                child_refs = _source_ref(child, project, sources, source_digests) or refs
                child_node = entity(
                    entity_type=entity_type, name=child_name,
                    properties=properties(child), source_refs=child_refs,
                    provenance=provenance,
                    identity={"kind": entity_type, "scope": node["id"], "name": child_name},
                )
                entities.append(child_node)
                relationships.append(relationship(
                    relation_type="DECLARES", source_id=node["id"], target_id=child_node["id"],
                    source_refs=child_refs, provenance=provenance,
                ))
                locate(child_node, child_refs)
        return node

    for module in modules:
        add_definition(module)

    for package in packages:
        name = _unqualified(package.get("name"))
        if not name or name in package_nodes:
            continue
        refs = _source_ref(package, project, sources, source_digests)
        node = entity(entity_type="Package", name=name, source_refs=refs,
                      provenance=provenance, identity={"kind": "Package", "name": name})
        package_nodes[name] = node
        entities.append(node)
        locate(node, refs)

    for record in modules:
        module = add_definition(record)
        for imported in _records(record.get("imports"), "imports"):
            name = _unqualified(imported.get("name"))
            target = package_nodes.get(name)
            if target is not None:
                relationships.append(relationship(
                    relation_type="IMPORTS", source_id=module["id"], target_id=target["id"],
                    source_refs=_source_ref(imported, project, sources, source_digests), provenance=provenance,
                ))

    def add_instance(record: dict[str, Any], parent: dict[str, Any] | None, is_top: bool) -> None:
        definition = add_definition(record)
        name = _unqualified(record.get("name") or record.get("definition"))
        if not name:
            raise ValueError("RTL elaborated module is missing a name")
        refs = _source_ref(record, project, sources, source_digests)
        hierarchy = record.get("hierarchy")
        path = (
            hierarchy
            if isinstance(hierarchy, str) and hierarchy
            else name if parent is None else f"{parent['properties']['path']}.{name}"
        )
        instance = entity(
            entity_type="Instance", name=name,
            properties={"path": path, "definition": definition["name"], "is_top": is_top},
            source_refs=refs, provenance=provenance,
            identity={"kind": "Instance", "path": path, "definition": definition["id"]},
        )
        entities.append(instance)
        relationships.append(relationship(
            relation_type="OF", source_id=instance["id"], target_id=definition["id"],
            source_refs=refs, provenance=provenance,
        ))
        if parent is not None:
            relationships.append(relationship(
                relation_type="INSTANTIATES", source_id=parent["id"], target_id=instance["id"],
                source_refs=refs, provenance=provenance,
            ))
        locate(instance, refs)
        for child in _records(record.get("instances"), "instances"):
            add_instance(child, instance, False)

    for top in top_modules:
        add_instance(top, None, True)
    return entities, relationships, []
