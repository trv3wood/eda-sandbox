from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def binding_info() -> dict[str, str]:
    try:
        import uhdm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "UHDM Python binding is unavailable; use the eda-uhdm image"
        ) from exc
    serializer = uhdm.Serializer()
    return {
        "module": str(Path(uhdm.__file__).resolve()),
        "serializer_format_version": str(
            getattr(serializer, "kVersion", "unknown")
        ),
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _capture(
    command: list[str],
    *,
    environment: dict[str, str],
    timeout: int,
    max_output_bytes: int,
) -> tuple[int, bytes, bytes, str | None]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    streams = {
        process.stdout.fileno(): ("stdout", process.stdout),
        process.stderr.fileno(): ("stderr", process.stderr),
    }
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    for descriptor, (_, stream) in streams.items():
        selector.register(stream, selectors.EVENT_READ, descriptor)

    started = time.monotonic()
    stop_reason: str | None = None
    while selector.get_map():
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0 and stop_reason is None:
            stop_reason = "timeout"
            process.kill()
        events = selector.select(timeout=max(0.0, min(0.1, remaining)))
        for key, _ in events:
            descriptor = int(key.data)
            label, stream = streams[descriptor]
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                selector.unregister(stream)
                continue
            room = max_output_bytes - sum(len(value) for value in buffers.values())
            if room > 0:
                buffers[label].extend(chunk[:room])
            if len(chunk) > room and stop_reason is None:
                stop_reason = "output_limit"
                process.kill()
        if stop_reason is not None and process.poll() is not None and not events:
            # Pipes become readable at EOF; keep looping until both are drained.
            continue
    returncode = process.wait()
    selector.close()
    process.stdout.close()
    process.stderr.close()
    return returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"]), stop_reason


def run_query(
    database: Path,
    script: Path,
    output_dir: Path,
    *,
    script_args: Sequence[str] = (),
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    if timeout < 1:
        raise ValueError("timeout must be a positive number of seconds")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be positive")
    database = database.resolve()
    script = script.resolve()
    output_dir = output_dir.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if not script.is_file():
        raise FileNotFoundError(script)
    if script.suffix.lower() != ".py":
        raise ValueError("UHDM query script must have a .py suffix")
    output_dir.mkdir(parents=True, exist_ok=True)

    info = binding_info()
    arguments = list(script_args)
    command = [sys.executable, str(script), *arguments]
    environment = dict(os.environ)
    environment["UHDM_DATABASE"] = str(database)
    started_at = _utc_now()
    started = time.monotonic()
    returncode, stdout, stderr, stop_reason = _capture(
        command,
        environment=environment,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
    )
    ended_at = _utc_now()
    stdout_path = output_dir / "stdout.log"
    stderr_path = output_dir / "stderr.log"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    status = (
        stop_reason
        if stop_reason is not None
        else "passed"
        if returncode == 0
        else "failed"
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "database": {
            "path": str(database),
            "sha256": _digest(database),
            "size": database.stat().st_size,
        },
        "script": {
            "path": str(script),
            "sha256": _digest(script),
        },
        "arguments": arguments,
        "binding": info,
        "image_revision": os.environ.get("IMAGE_REVISION", "unknown"),
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "timeout_seconds": timeout,
        "max_output_bytes": max_output_bytes,
        "returncode": returncode,
        "stdout": {
            "path": str(stdout_path),
            "sha256": hashlib.sha256(stdout).hexdigest(),
            "bytes": len(stdout),
        },
        "stderr": {
            "path": str(stderr_path),
            "sha256": hashlib.sha256(stderr).hexdigest(),
            "bytes": len(stderr),
        },
    }
    _write_json_atomic(output_dir / "run.json", result)
    return result


class _ArgumentParser(argparse.ArgumentParser):
    """Accept query-script arguments after ``--`` on all supported Python versions."""

    def parse_args(
        self, args: list[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        values = list(sys.argv[1:] if args is None else args)
        if "--" not in values:
            return super().parse_args(values, namespace)
        separator = values.index("--")
        parsed = super().parse_args(values[:separator], namespace)
        if getattr(parsed, "command", None) != "run":
            self.error("query script arguments are only valid with the run command")
        parsed.script_args.extend(values[separator + 1:])
        return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="eda-uhdm")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version")
    run = commands.add_parser("run")
    run.add_argument("database")
    run.add_argument("script")
    run.add_argument("--output-dir", required=True)
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    run.add_argument(
        "--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES
    )
    run.add_argument("script_args", nargs="*")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "version":
            info = binding_info()
            print(
                "eda-uhdm runner schema 1; "
                f"binding={info['module']}; "
                f"serializer-format={info['serializer_format_version']}"
            )
            return 0
        script_args = list(args.script_args)
        result = run_query(
            Path(args.database),
            Path(args.script),
            Path(args.output_dir),
            script_args=script_args,
            timeout=args.timeout,
            max_output_bytes=args.max_output_bytes,
        )
        sys.stdout.buffer.write(Path(result["stdout"]["path"]).read_bytes())
        sys.stdout.buffer.flush()
        sys.stderr.buffer.write(Path(result["stderr"]["path"]).read_bytes())
        print(
            f"eda-uhdm run metadata: {Path(args.output_dir).resolve() / 'run.json'}",
            file=sys.stderr,
        )
        return 0 if result["status"] == "passed" else 1
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
