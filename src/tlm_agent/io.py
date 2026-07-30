from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
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


def resolve_filelist_inputs(
    project_dir: Path,
    values: list[str],
    *,
    working_directory: Path | None = None,
) -> tuple[list[Path], list[Path], list[Path]]:
    """解析 VCS 风格 filelist 的嵌套清单和源码依赖。

    返回顶层 filelist、包含嵌套清单的全部 filelist，以及按清单首次出现
    顺序排列的 RTL 源文件。解析结果只用于摘要和源码定位；EDA 命令仍原样
    使用顶层 ``-f``，不会由这里重建编译参数。
    """
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ValueError("eda_compile.filelists must be a list of strings")
    compile_root = (working_directory or project_dir).resolve()
    if not compile_root.is_dir():
        raise FileNotFoundError(
            f"EDA working directory does not exist: {compile_root}"
        )
    roots = resolve_inputs(project_dir, values) if values else []
    all_filelists: list[Path] = []
    sources: list[Path] = []
    visited: set[tuple[Path, Path]] = set()
    active: list[Path] = []

    def resolve_token(base: Path, token: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(token))
        if "$" in expanded:
            raise ValueError(f"unresolved environment variable in filelist: {token}")
        path = Path(expanded)
        return (path if path.is_absolute() else base / path).resolve()

    def add_source(base: Path, token: str, owner: Path) -> None:
        source = resolve_token(base, token)
        if source.suffix.lower() not in RTL_SOURCE_SUFFIXES:
            return
        if not source.is_file():
            raise FileNotFoundError(f"{owner}: RTL source does not exist: {token}")
        if source not in sources:
            sources.append(source)

    def visit(path: Path, content_base: Path) -> None:
        resolved = path.resolve()
        if resolved in active:
            chain = " -> ".join(str(item) for item in [*active, resolved])
            raise ValueError(f"recursive filelist include: {chain}")
        visit_key = (resolved, content_base.resolve())
        if visit_key in visited:
            return
        if not resolved.is_file():
            raise FileNotFoundError(f"filelist does not exist: {resolved}")
        visited.add(visit_key)
        active.append(resolved)
        if resolved not in all_filelists:
            all_filelists.append(resolved)
        # 常见工程允许 // 注释；只在行首或空白后识别，保留路径中的双斜线。
        text = "\n".join(
            re.sub(r"(?<!\S)//.*$", "", line)
            for line in resolved.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        )
        try:
            tokens = shlex.split(text, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"invalid filelist syntax in {resolved}: {exc}") from exc
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in {"-f", "-F"}:
                index += 1
                if index >= len(tokens):
                    raise ValueError(f"{resolved}: {token} requires a filelist path")
                nested = resolve_token(content_base, tokens[index])
                visit(
                    nested,
                    nested.parent if token == "-F" else compile_root,
                )
            elif token.startswith("-f") and len(token) > 2:
                visit(resolve_token(content_base, token[2:]), compile_root)
            elif token.startswith("-F") and len(token) > 2:
                nested = resolve_token(content_base, token[2:])
                visit(nested, nested.parent)
            elif token == "-v":
                index += 1
                if index >= len(tokens):
                    raise ValueError(f"{resolved}: -v requires an RTL source path")
                add_source(content_base, tokens[index], resolved)
            elif token.startswith("-v") and len(token) > 2:
                add_source(content_base, token[2:], resolved)
            elif not token.startswith(("-", "+")):
                add_source(content_base, token, resolved)
            index += 1
        active.pop()

    for root in roots:
        visit(root, compile_root)
    return roots, all_filelists, sources


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
