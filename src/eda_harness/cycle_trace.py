"""标准 JSONL cycle trace 的解析与比较。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .cycle_evidence import file_digest


class TraceComparator:
    """解析并严格比较标准 JSONL cycle trace。"""

    def __init__(self, observables: dict[str, int], sample_phase: str) -> None:
        self.observables = observables
        self.sample_phase = sample_phase

    def compare(
        self, reference: Path, model: Path, expected_samples: int | None = None
    ) -> dict[str, Any]:
        expected = self._load(reference)
        actual = self._load(model)
        self._validate_lengths(expected, actual, expected_samples)
        for index, (left, right) in enumerate(zip(expected, actual)):
            if left != right:
                mismatches = [
                    name
                    for name in self.observables
                    if left["signals"][name] != right["signals"][name]
                ]
                raise ValueError(
                    f"trace mismatch at sample {index}: signals={mismatches}, "
                    f"reference={left['signals']}, model={right['signals']}"
                )
        return {
            "samples": len(expected),
            "reference_sha256": file_digest(reference),
            "model_sha256": file_digest(model),
        }

    def _load(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            raise FileNotFoundError(f"trace was not produced: {path}")
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if line.strip():
                records.append(self._parse_record(path, line_number, line, len(records)))
        if not records:
            raise ValueError(f"trace is empty: {path}")
        return records

    def _parse_record(
        self, path: Path, line_number: int, line: str, sample: int
    ) -> dict[str, Any]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSONL at {path}:{line_number}: {exc}"
            ) from exc
        if (
            not isinstance(record, dict)
            or isinstance(record.get("sample"), bool)
            or record.get("sample") != sample
        ):
            raise ValueError(
                f"trace sample must be contiguous at {path}:{line_number}"
            )
        if record.get("phase") != self.sample_phase:
            raise ValueError(f"trace phase mismatch at {path}:{line_number}")
        signals = record.get("signals")
        if not isinstance(signals, dict) or set(signals) != set(self.observables):
            raise ValueError(f"trace signals mismatch at {path}:{line_number}")
        return {
            "sample": sample,
            "phase": self.sample_phase,
            "signals": {
                name: self._canonical_value(name, signals[name], width, path, line_number)
                for name, width in self.observables.items()
            },
        }

    @staticmethod
    def _canonical_value(
        name: str, value: Any, width: int, path: Path, line_number: int
    ) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-f]+", value):
            raise ValueError(
                f"{name} must be canonical lowercase hex at {path}:{line_number}"
            )
        number = int(value, 16)
        if number >= 1 << width:
            raise ValueError(f"{name} exceeds declared width at {path}:{line_number}")
        canonical = f"0x{number:0{max(1, (width + 3) // 4)}x}"
        if value != canonical:
            raise ValueError(
                f"{name} is not width-canonical at {path}:{line_number}"
            )
        return canonical

    @staticmethod
    def _validate_lengths(
        expected: list[dict[str, Any]],
        actual: list[dict[str, Any]],
        required: int | None,
    ) -> None:
        if len(expected) != len(actual):
            raise ValueError(
                "trace length mismatch: "
                f"reference={len(expected)}, model={len(actual)}"
            )
        if required is not None and len(expected) != required:
            raise ValueError(
                f"trace sample count mismatch: expected={required}, "
                f"actual={len(expected)}"
            )
