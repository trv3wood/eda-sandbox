from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_schema import read_jsonl
from .io import dump_json, load_json

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"


def _duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "Graph storage requires the graph extra: pip install 'systemc-tlm-agent[graph]'"
        ) from exc
    return duckdb


def build_parquet_store(project: Path) -> dict[str, Any]:
    graph = project / ".systemc-agent" / "graph"
    manifest = load_json(graph / "manifest.json")
    if manifest.get("status") != "ready":
        raise ValueError("canonical graph is not ready")
    entities = read_jsonl(graph / "entities.jsonl")
    relationships = read_jsonl(graph / "relationships.jsonl")
    text_units = read_jsonl(graph / "text_units.jsonl")
    store = graph / "store"
    store.mkdir(parents=True, exist_ok=True)
    duckdb = _duckdb()
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TABLE entities(id VARCHAR, type VARCHAR, name VARCHAR, "
            "description VARCHAR, properties_json VARCHAR, source_refs_json VARCHAR, "
            "provenance_json VARCHAR)"
        )
        entity_rows = [
            (
                item["id"],
                item["type"],
                item.get("name", ""),
                item.get("description", ""),
                json.dumps(item.get("properties", {}), sort_keys=True),
                json.dumps(item.get("source_refs", []), sort_keys=True),
                json.dumps(item.get("provenance", {}), sort_keys=True),
            )
            for item in entities
        ]
        if entity_rows:
            connection.executemany(
                "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?)",
                entity_rows,
            )
        connection.execute(
            "CREATE TABLE relationships(id VARCHAR, type VARCHAR, source_id VARCHAR, "
            "target_id VARCHAR, description VARCHAR, properties_json VARCHAR, "
            "source_refs_json VARCHAR, provenance_json VARCHAR)"
        )
        relationship_rows = [
            (
                item["id"],
                item["type"],
                item["source_id"],
                item["target_id"],
                item.get("description", ""),
                json.dumps(item.get("properties", {}), sort_keys=True),
                json.dumps(item.get("source_refs", []), sort_keys=True),
                json.dumps(item.get("provenance", {}), sort_keys=True),
            )
            for item in relationships
        ]
        if relationship_rows:
            connection.executemany(
                "INSERT INTO relationships VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                relationship_rows,
            )
        connection.execute(
            "CREATE TABLE text_units(id VARCHAR, text VARCHAR, section_path_json VARCHAR, "
            "source_path VARCHAR, source_digest VARCHAR, locator VARCHAR)"
        )
        text_rows = [
                (
                    item["id"],
                    item["text"],
                    json.dumps(item.get("section_path", []), ensure_ascii=False),
                    item["source_path"],
                    item["source_digest"],
                    item["locator"],
                )
                for item in text_units
            ]
        if text_rows:
            connection.executemany(
                "INSERT INTO text_units VALUES (?, ?, ?, ?, ?, ?)",
                text_rows,
            )
        for name in ("entities", "relationships", "text_units"):
            target = (store / f"{name}.parquet").as_posix().replace("'", "''")
            connection.execute(
                f"COPY (SELECT * FROM {name} ORDER BY id) "
                f"TO '{target}' (FORMAT PARQUET)"
            )
    finally:
        connection.close()
    return {
        "status": "built",
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "text_unit_count": len(text_units),
        "store": str(store),
    }


def _graph_paths(project: Path) -> tuple[Path, Path]:
    store = project / ".systemc-agent" / "graph" / "store"
    entities = store / "entities.parquet"
    relationships = store / "relationships.parquet"
    if not entities.is_file() or not relationships.is_file():
        raise FileNotFoundError("Parquet graph store is missing; run graph build")
    return entities, relationships


def lookup(
    project: Path, *, name: str, entity_type: str | None = None
) -> dict[str, Any]:
    entities, _ = _graph_paths(project)
    connection = _duckdb().connect()
    try:
        sql = (
            "SELECT id, type, name, description, properties_json, source_refs_json, "
            "provenance_json FROM read_parquet(?) WHERE name = ?"
        )
        parameters: list[Any] = [str(entities), name]
        if entity_type:
            sql += " AND type = ?"
            parameters.append(entity_type)
        sql += " ORDER BY id"
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    return {
        "schema_version": 1,
        "status": "ok" if rows else "empty",
        "items": [
            {
                "id": row[0],
                "type": row[1],
                "name": row[2],
                "description": row[3],
                "properties": json.loads(row[4]),
                "source_refs": json.loads(row[5]),
                "provenance": json.loads(row[6]),
            }
            for row in rows
        ],
    }


def _networkx_graph(project: Path, relation_type: str | None = None) -> Any:
    try:
        import networkx as nx
    except ImportError as exc:
        raise RuntimeError(
            "Graph traversal requires the graph extra: "
            "pip install 'systemc-tlm-agent[graph]'"
        ) from exc
    _, relationships = _graph_paths(project)
    connection = _duckdb().connect()
    try:
        sql = (
            "SELECT id, type, source_id, target_id, properties_json "
            "FROM read_parquet(?)"
        )
        parameters: list[Any] = [str(relationships)]
        if relation_type:
            sql += " WHERE type = ?"
            parameters.append(relation_type)
        sql += " ORDER BY id"
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    graph = nx.MultiDiGraph()
    for identifier, kind, source, target, properties in rows:
        graph.add_edge(
            source,
            target,
            key=identifier,
            id=identifier,
            type=kind,
            properties=json.loads(properties),
        )
    return graph


def neighbors(
    project: Path,
    *,
    entity_id: str,
    depth: int = 1,
    relation_type: str | None = None,
) -> dict[str, Any]:
    if not 1 <= depth <= 8:
        raise ValueError("depth must be between 1 and 8")
    graph = _networkx_graph(project, relation_type)
    if entity_id not in graph:
        return {"schema_version": 1, "status": "empty", "nodes": [], "edges": []}
    visited = {entity_id}
    frontier = {entity_id}
    edge_ids: set[str] = set()
    for _ in range(depth):
        following: set[str] = set()
        for node in sorted(frontier):
            for source, target, key, data in sorted(
                graph.out_edges(node, keys=True, data=True),
                key=lambda value: (value[1], value[2]),
            ):
                following.add(target)
                edge_ids.add(data["id"])
            for source, target, key, data in sorted(
                graph.in_edges(node, keys=True, data=True),
                key=lambda value: (value[0], value[2]),
            ):
                following.add(source)
                edge_ids.add(data["id"])
        following -= visited
        visited |= following
        frontier = following
    return {
        "schema_version": 1,
        "status": "ok",
        "nodes": sorted(visited),
        "edges": sorted(edge_ids),
    }


def shortest_path(
    project: Path,
    *,
    source_id: str,
    target_id: str,
    max_depth: int = 8,
) -> dict[str, Any]:
    if not 1 <= max_depth <= 8:
        raise ValueError("max_depth must be between 1 and 8")
    graph = _networkx_graph(project)
    try:
        import networkx as nx

        candidates = nx.all_shortest_paths(
            graph.to_undirected(), source_id, target_id
        )
        paths = sorted(tuple(path) for path in candidates)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        paths = []
    paths = [path for path in paths if len(path) - 1 <= max_depth]
    return {
        "schema_version": 1,
        "status": "ok" if paths else "empty",
        "path": list(paths[0]) if paths else [],
    }


def build_faiss_index(project: Path) -> dict[str, Any]:
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "FAISS indexing requires the vector extra: "
            "pip install 'systemc-tlm-agent[vector]'"
        ) from exc
    graph = project / ".systemc-agent" / "graph"
    entities = read_jsonl(graph / "entities.jsonl")
    units = read_jsonl(graph / "text_units.jsonl")
    try:
        model = SentenceTransformer(
            EMBEDDING_MODEL,
            revision=EMBEDDING_REVISION,
            local_files_only=True,
        )
    except Exception as exc:
        raise RuntimeError(
            "embedding model is not available locally; run: "
            f"hf download {EMBEDDING_MODEL} --revision {EMBEDDING_REVISION}"
        ) from exc
    index_dir = graph / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for scope, values, texts in (
        (
            "entities",
            entities,
            [
                "passage: " + " ".join(
                    part for part in (item.get("name", ""), item.get("description", ""))
                    if part
                )
                for item in entities
            ],
        ),
        (
            "chunks",
            units,
            ["passage: " + item["text"] for item in units],
        ),
    ):
        if not values:
            result[scope] = {"count": 0, "status": "skipped"}
            continue
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        faiss.write_index(index, str(index_dir / f"{scope}.faiss"))
        dump_json(
            index_dir / f"{scope}-ids.json",
            {
                "model": EMBEDDING_MODEL,
                "revision": EMBEDDING_REVISION,
                "ids": [item["id"] for item in values],
            },
        )
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            connection.execute(
                "CREATE TABLE vector_map(position INTEGER, entity_id VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO vector_map VALUES (?, ?)",
                [(position, item["id"]) for position, item in enumerate(values)],
            )
            target = (index_dir / f"{scope}-map.parquet").as_posix().replace(
                "'", "''"
            )
            connection.execute(
                "COPY (SELECT * FROM vector_map ORDER BY position) "
                f"TO '{target}' (FORMAT PARQUET)"
            )
        finally:
            connection.close()
        result[scope] = {"count": len(values), "status": "built"}
    return {"status": "built", "indexes": result}


def semantic_search(
    project: Path, *, query: str, scope: str, top_k: int
) -> dict[str, Any]:
    if scope not in {"chunks", "entities"}:
        raise ValueError("scope must be chunks or entities")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("semantic search requires the vector extra") from exc
    index_dir = project / ".systemc-agent" / "graph" / "index"
    mapping = load_json(index_dir / f"{scope}-ids.json")
    model = SentenceTransformer(
        mapping["model"],
        revision=mapping["revision"],
        local_files_only=True,
    )
    vector = model.encode(
        ["query: " + query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype("float32")
    index = faiss.read_index(str(index_dir / f"{scope}.faiss"))
    scores, indexes = index.search(vector, min(top_k, len(mapping["ids"])))
    return {
        "schema_version": 1,
        "status": "ok",
        "scope": scope,
        "items": [
            {"id": mapping["ids"][int(position)], "score": float(score)}
            for score, position in zip(scores[0], indexes[0])
            if position >= 0
        ],
    }
