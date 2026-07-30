from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


RTL_SOURCE_SUFFIXES = frozenset({".v", ".sv", ".svp"})


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_digest(data: Any) -> str:
    encoded = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_inputs(
    project_dir: Path,
    values: list[str],
    *,
    directory_suffixes: set[str] | None = None,
    exclude_values: list[str] | None = None,
) -> list[Path]:
    """Resolve files, glob patterns, and optionally source directories."""
    result: list[Path] = []
    for value in values:
        path = Path(value)
        pattern = str(path if path.is_absolute() else project_dir / path)
        if any(character in pattern for character in "*?["):
            import glob

            matches = [Path(item).resolve() for item in glob.glob(pattern, recursive=True)]
            if not matches:
                raise FileNotFoundError(f"input pattern matched no files: {value}")
            result.extend(sorted(matches))
        else:
            resolved = Path(pattern).resolve()
            if resolved.is_dir():
                if not directory_suffixes:
                    raise ValueError(f"input must be a file or glob pattern: {value}")
                result.extend(
                    sorted(
                        candidate.resolve()
                        for candidate in resolved.rglob("*")
                        if candidate.is_file()
                        and candidate.suffix.lower() in directory_suffixes
                    )
                )
                continue
            if not resolved.is_file():
                raise FileNotFoundError(f"input file does not exist: {value}")
            result.append(resolved)
    # Overlapping directories/globs should not parse the same source twice.
    resolved = list(dict.fromkeys(result))
    if not exclude_values:
        return resolved
    excluded = set(
        resolve_inputs(
            project_dir,
            exclude_values,
            directory_suffixes=directory_suffixes,
        )
    )
    return [path for path in resolved if path not in excluded]


def relative_to_project(project_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def project_paths(project_dir: Path) -> dict[str, Path]:
    root = project_dir.resolve()
    state = root / ".systemc-agent"
    return {
        "root": root,
        "manifest": root / "manifest.yaml",
        "state": state,
        "contracts": state / "contracts" / "architecture.yaml",
        "conflicts": state / "contracts" / "conflicts.yaml",
        "approval": state / "contracts" / "approval.yaml",
        "contract_testbench": state / "contracts" / "testbench",
        "contract_test_manifest": state / "contracts" / "testbench" / "testbench.yaml",
        "model": root / "model",
        "verification": state / "verification" / "report.json",
        "tools": state / "tools",
        "graph": state / "graph",
        "graph_manifest": state / "graph" / "manifest.json",
        "graph_entities": state / "graph" / "entities.jsonl",
        "graph_relationships": state / "graph" / "relationships.jsonl",
    }
