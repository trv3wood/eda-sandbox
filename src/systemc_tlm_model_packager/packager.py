from __future__ import annotations

"""Create source-only model archives using the generated Git ignore policy."""

import gzip
import subprocess
import tarfile
import tempfile
from pathlib import Path


def _regular_files(source_dir: Path, output: Path) -> list[Path]:
    """List archive candidates without following symlinks or adding the output."""
    return [
        path
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.resolve() != output
    ]


def _ignored_by_git(
    source_dir: Path, candidates: list[Path], ignore_file: Path
) -> set[Path]:
    """Ask Git to apply the model-local .gitignore policy to candidates.

    A temporary bare repository makes this work for a standalone model
    directory too; no repository metadata is created in the user's project.
    """
    ignored: set[Path] = set()
    with tempfile.TemporaryDirectory(prefix="systemc-tlm-package-") as temporary:
        git_dir = Path(temporary) / "ignore.git"
        initialized = subprocess.run(
            ["git", "init", "--bare", "--quiet", str(git_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if initialized.returncode:
            raise RuntimeError(f"Git initialization failed: {initialized.stderr.strip()}")
        for path in candidates:
            relative = path.relative_to(source_dir).as_posix()
            checked = subprocess.run(
                [
                    "git",
                    "-c",
                    f"core.excludesFile={ignore_file}",
                    f"--git-dir={git_dir}",
                    f"--work-tree={source_dir}",
                    "check-ignore",
                    "--no-index",
                    "--quiet",
                    "--",
                    relative,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if checked.returncode == 0:
                ignored.add(path)
            elif checked.returncode != 1:
                raise RuntimeError(
                    f"Git ignore check failed for {relative}: {checked.stderr.strip()}"
                )
    return ignored


def _add_file(
    archive: tarfile.TarFile, source_dir: Path, archive_root: str, path: Path
) -> None:
    """Add one regular file with stable archive metadata."""
    relative = path.relative_to(source_dir).as_posix()
    info = archive.gettarinfo(str(path), arcname=f"{archive_root}/{relative}")
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    with path.open("rb") as stream:
        archive.addfile(info, stream)


def package_model(project_dir: Path, output: Path | None = None) -> dict[str, object]:
    """Package the model and immutable contract tests through Git ignore rules."""
    project_dir = project_dir.resolve()
    model_dir = project_dir / "model"
    if not model_dir.is_dir():
        raise FileNotFoundError("model directory is missing; run generate first")
    testbench_dir = project_dir / ".systemc-agent" / "contracts" / "testbench"
    if not testbench_dir.is_dir():
        raise FileNotFoundError("contract testbench is missing; run architect first")
    ignore_file = model_dir / ".gitignore"
    if not ignore_file.is_file():
        raise FileNotFoundError("model/.gitignore is missing; run generate first")
    archive_path = (
        output or (project_dir / f"{project_dir.name}-model.tar.gz")
    ).resolve()
    if archive_path.is_relative_to(model_dir):
        raise ValueError("package output must be outside the model directory")
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    source_roots = [
        (model_dir, "model"),
        (testbench_dir, "contracts/testbench"),
    ]
    included: list[tuple[Path, str, Path]] = []
    ignored_count = 0
    for source_dir, archive_root in source_roots:
        candidates = _regular_files(source_dir, archive_path)
        ignored = _ignored_by_git(source_dir, candidates, ignore_file)
        ignored_count += len(ignored)
        included.extend(
            (source_dir, archive_root, path)
            for path in candidates
            if path not in ignored
        )
    with archive_path.open("wb") as raw_stream:
        with gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for source_dir, archive_root, path in included:
                    _add_file(archive, source_dir, archive_root, path)
    return {
        "archive": str(archive_path),
        "file_count": len(included),
        "ignored_count": ignored_count,
    }
