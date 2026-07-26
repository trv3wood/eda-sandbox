from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from eda_query import validate_result

from .extractors import _evidence
from .io import project_paths


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} must contain a JSON object")
        result.append(value)
    return result


def all_evidence(project_dir: Path) -> list[dict[str, Any]]:
    paths = project_paths(project_dir)
    return _read_jsonl(paths["evidence"]) + _read_jsonl(paths["query_evidence"])


def record_query_evidence(
    project_dir: Path, result_path: Path, *, statement: str
) -> dict[str, Any]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_result(result, verify_source=True)
    if result["status"] != "ok":
        raise ValueError("only a successful, non-empty QueryResult can be evidence")
    source = Path(result["source"]["path"])
    pointers = sorted(
        {
            item["pointer"]
            for item in result["items"]
            if isinstance(item, dict) and item.get("pointer")
        }
    )
    locator = f"query:{result['query_id']}/kind:{result['kind']}"
    if pointers:
        locator += "/pointers:" + ",".join(pointers)
    evidence = _evidence(
        kind=f"eda-{result['backend']}",
        path=source,
        project_dir=project_dir,
        locator=locator,
        text=statement,
        extractor=f"eda-query/{result['schema_version']}",
    )
    paths = project_paths(project_dir)
    existing = _read_jsonl(paths["query_evidence"])
    for item in existing:
        if item.get("id") == evidence.id:
            if item != asdict(evidence):
                raise ValueError(f"evidence ID collision: {evidence.id}")
            return {"status": "existing", "evidence": item}
    paths["query_evidence"].parent.mkdir(parents=True, exist_ok=True)
    with paths["query_evidence"].open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(evidence), sort_keys=True, ensure_ascii=False))
        stream.write("\n")
    return {"status": "recorded", "evidence": asdict(evidence)}


def list_evidence(project_dir: Path) -> dict[str, Any]:
    paths = project_paths(project_dir)
    extracted = _read_jsonl(paths["evidence"])
    queried = _read_jsonl(paths["query_evidence"])
    return {
        "extracted_count": len(extracted),
        "query_count": len(queried),
        "total_count": len(extracted) + len(queried),
        "items": extracted + queried,
    }
