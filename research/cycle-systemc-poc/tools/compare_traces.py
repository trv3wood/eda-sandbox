#!/usr/bin/env python3
"""比较字段一致的 CSV trace，报告首个周期差异。"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def load(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    reference = load(args.reference)
    candidate = load(args.candidate)
    if len(reference) != len(candidate):
        print(f"行数不同: reference={len(reference)} candidate={len(candidate)}")
        return 1
    for index, (expected, actual) in enumerate(zip(reference, candidate), start=2):
        if expected != actual:
            print(f"第 {index} 行不同: expected={expected} actual={actual}")
            return 1
    print(f"{len(reference)} 个采样点一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())

