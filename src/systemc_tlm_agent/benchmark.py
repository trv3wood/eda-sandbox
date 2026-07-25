from __future__ import annotations

"""Reproducible A/B benchmark orchestration for SystemC/TLM modeling."""

import hashlib
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .io import dump_json, load_json
from .workflow import CONTRACT_CATEGORIES

ARMS = ("baseline", "skill")
CASES = (
    ("chipbench", "FracWidthConv_24to128"),
    ("chipbench", "data_accumulation_output"),
    ("chipbench", "least_common_multiple"),
    ("chipbench", "synchronous_FIFO"),
    ("chipbench", "asynchronous_FIFO"),
    ("chipbench", "cpu_top"),
    ("chipbench", "div"),
    ("chipbench", "ctrl"),
    ("opentitan", "i2c"),
    ("opentitan", "dma"),
)
SOURCES = {
    "chipbench": {
        "url": "https://github.com/zhongkaiyu/ChipBench.git",
        "license": "Apache-2.0",
    },
    "opentitan": {
        "url": "https://github.com/lowRISC/opentitan.git",
        "license": "Apache-2.0",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def prepare_workspace(work: Path) -> dict[str, Any]:
    """Create metadata only; deliberately do not clone or build large projects."""
    work = work.resolve()
    for relative in (
        "sources", "corpus/chipbench", "corpus/opentitan",
        "oracle/contracts", "oracle/stimuli", "oracle/expected",
        "runs/luna", "reports",
    ):
        (work / relative).mkdir(parents=True, exist_ok=True)
    sources, commands = [], []
    for name, metadata in SOURCES.items():
        destination = work / "sources" / name
        sources.append({
            "name": name, **metadata, "commit": None, "tree_sha256": None,
            "status": "pending", "path": str(destination),
        })
        commands.append(
            f"git clone --filter=blob:none {shlex.quote(metadata['url'])} "
            f"{shlex.quote(str(destination))}"
        )
    dump_json(work / "sources" / "lock.json",
              {"schema_version": 1, "sources": sources})
    dump_json(work / "benchmark.json", {
        "schema_version": 1, "created_at": utc_now(), "model": "gpt-5.6-luna",
        "trials": 3,
        "cases": [{"suite": suite, "case": case, "enabled": True}
                  for suite, case in CASES],
        "contract_categories": [key for key, _ in CONTRACT_CATEGORIES],
        "seeds": [104729, 130363, 155921],
    })
    fetch = work / "sources" / "FETCH_COMMANDS.txt"
    fetch.write_text(
        "\n".join(commands) + "\n\n# Then pin commits and tree digests:\n"
        f"scripts/benchmark-systemc-tlm lock --work {shlex.quote(str(work))}\n",
        encoding="utf-8",
    )
    for suite, case in CASES:
        case_dir = work / "corpus" / suite / case
        case_dir.mkdir(parents=True, exist_ok=True)
        dump_json(case_dir / "case.json", {
            "schema_version": 1, "suite": suite, "case": case,
            "input_paths": [], "status": "requires-corpus-adapter",
        })
    return {"work": str(work), "cases": len(CASES),
            "status": "prepared-metadata", "next": f"run commands in {fetch}"}


def lock_sources(work: Path) -> dict[str, Any]:
    """Pin already downloaded repositories and record their Git tree IDs."""
    lock_path = work.resolve() / "sources" / "lock.json"
    lock = load_json(lock_path)
    for source in lock["sources"]:
        path = Path(source["path"])
        if not (path / ".git").exists():
            raise FileNotFoundError(f"source checkout is missing: {path}")
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], check=True,
            text=True, capture_output=True,
        ).stdout.strip()
        tree_listing = subprocess.run(
            ["git", "-C", str(path), "ls-tree", "-r", "--full-tree", "HEAD"], check=True,
            text=True, capture_output=True,
        ).stdout
        source.update({"commit": commit,
                       "tree_sha256": sha256_text(tree_listing),
                       "status": "locked", "locked_at": utc_now()})
    dump_json(lock_path, lock)
    return {"lock": str(lock_path), "sources": lock["sources"]}


def _assert_ready(work: Path) -> dict[str, Any]:
    lock = load_json(work / "sources" / "lock.json")
    pending = [x["name"] for x in lock["sources"] if x["status"] != "locked"]
    if pending:
        raise ValueError("source commits are not locked: " + ", ".join(pending))
    return lock


def _prompt(work: Path, case: str, arm: str, stage: str) -> str:
    matches = list(work.glob(f"corpus/*/{case}/case.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"unknown or ambiguous case: {case}")
    common = (
        "You are participating in a blinded SystemC TLM benchmark.\n"
        f"Case manifest: {matches[0]}\n"
        f"Stage: {stage}. Do not inspect oracle/ or reports/. Use only supplied "
        "inputs. Every design claim must cite a source locator. Do not invent "
        "missing behavior. Produce all eight contract categories and stop on "
        "unresolved evidence or conflicts. "
    )
    common += (
        "Do not implement code yet.\n" if stage == "architect" else
        "Implement only the approved contracts. Keep minres-SCC isolated behind adapters "
        "and emit contract-traceable tests.\n"
    )
    if arm == "baseline":
        return common + "Do not use the repository-specific modeling Skill.\n"
    return common + (
        "Use the modeling-systemc-tlm Skill and deterministic CLI; respect its "
        "role separation and explicit approval gate.\n"
    )


def architecture_is_approved(review: dict[str, Any]) -> bool:
    reviews = review.get("reviews", [])
    if len(reviews) < 2:
        return False
    reviewers = [item.get("reviewer") for item in reviews]
    if any(not name for name in reviewers) or len(reviewers) != len(set(reviewers)):
        return False
    first, second = reviews[0].get("decision"), reviews[1].get("decision")
    if first == second:
        return first == "approve"
    return len(reviews) >= 3 and reviews[2].get("decision") == "approve"


def run_benchmark(
    work: Path, *, model: str, arm: str, trials: int,
    cases: list[str] | None = None, execute: bool = False,
    stage: str = "architect",
) -> dict[str, Any]:
    work = work.resolve()
    if arm not in ARMS:
        raise ValueError(f"arm must be one of: {', '.join(ARMS)}")
    if stage not in {"architect", "implement"}:
        raise ValueError("stage must be architect or implement")
    lock = _assert_ready(work)
    config = load_json(work / "benchmark.json")
    selected = cases or [x["case"] for x in config["cases"] if x["enabled"]]
    planned = []
    for case in selected:
        for trial in range(1, trials + 1):
            run_dir = work / "runs" / model / case / arm / str(trial)
            run_dir.mkdir(parents=True, exist_ok=True)
            if stage == "implement":
                review_path = run_dir / "architecture-review.json"
                if not review_path.exists():
                    raise ValueError(f"architecture review is missing: {review_path}")
                review = load_json(review_path)
                if not architecture_is_approved(review):
                    raise ValueError(
                        "two matching blind reviews, or a positive third "
                        f"adjudication, are required: {review_path}"
                    )
            prompt = _prompt(work, case, arm, stage)
            (run_dir / f"{stage}.prompt.txt").write_text(prompt, encoding="utf-8")
            command = ["codex", "exec", "--skip-git-repo-check",
                       "-m", model, "--json", "--ephemeral",
                       "-C", str(run_dir), prompt]
            metadata = {
                "schema_version": 1, "case": case, "arm": arm, "trial": trial,
                "model": model, "stage": stage,
                "prompt_sha256": sha256_text(prompt),
                "input_commits": {x["name"]: x["commit"] for x in lock["sources"]},
                "command": command, "created_at": utc_now(), "started_at": None,
                "ended_at": None, "token_usage": None, "exit_status": "planned",
            }
            dump_json(run_dir / "run.json", metadata)
            if execute:
                metadata["started_at"] = utc_now()
                with (run_dir / f"{stage}.codex.jsonl").open(
                    "w", encoding="utf-8"
                ) as out:
                    proc = subprocess.run(
                        command, cwd=run_dir, text=True, stdout=out,
                        stderr=subprocess.STDOUT,
                    )
                metadata.update({
                    "ended_at": utc_now(), "exit_code": proc.returncode,
                    "exit_status": "completed" if proc.returncode == 0 else "failed",
                })
                dump_json(run_dir / "run.json", metadata)
            planned.append(str(run_dir))
    return {
        "arm": arm, "model": model, "runs": len(planned),
        "status": "executed" if execute else "planned",
        "run_directories": planned,
        "stage": stage,
        "note": "two blind approvals are required before implementation",
    }


def _percent(points: float, possible: float) -> float | None:
    return round(100 * points / possible, 2) if possible else None


def score_benchmark(work: Path) -> dict[str, Any]:
    """Aggregate reviewer-owned scores without exposing hidden oracles."""
    work = work.resolve()
    rows = []
    for path in sorted((work / "runs").glob("*/*/*/*/score.json")):
        score, run = load_json(path), load_json(path.parent / "run.json")
        sections = ("evidence", "architecture", "implementation", "functional")
        missing = [x for x in sections if x not in score]
        if missing:
            raise ValueError(f"{path} misses score sections: {missing}")
        points = sum(float(score[x]["points"]) for x in sections)
        possible = sum(float(score[x]["possible"]) for x in sections)
        rows.append({
            "case": run["case"], "arm": run["arm"], "trial": run["trial"],
            "points": points, "possible": possible,
            "percent": _percent(points, possible),
            "gate_violations": score.get("gate_violations", 0),
            "fabricated_evidence": score.get("fabricated_evidence", 0),
        })
    if not rows:
        raise ValueError("no reviewer score.json files found")
    arms = {}
    for arm in ARMS:
        selected = [x for x in rows if x["arm"] == arm]
        points, possible = (sum(x[k] for x in selected)
                            for k in ("points", "possible"))
        arms[arm] = {
            "runs": len(selected), "percent": _percent(points, possible),
            "gate_violations": sum(x["gate_violations"] for x in selected),
            "fabricated_evidence": sum(x["fabricated_evidence"] for x in selected),
        }
    b, s = arms["baseline"]["percent"], arms["skill"]["percent"]
    delta = round(s - b, 2) if b is not None and s is not None else None
    result = {"schema_version": 1, "generated_at": utc_now(),
              "arms": arms, "delta_points": delta, "runs": rows}
    dump_json(work / "reports" / "scores.json", result)
    return result


def report_benchmark(work: Path) -> dict[str, Any]:
    work = work.resolve()
    scores = load_json(work / "reports" / "scores.json")
    b, s = scores["arms"]["baseline"], scores["arms"]["skill"]
    lines = [
        "# SystemC TLM Benchmark Report", "", f"Generated: {utc_now()}", "",
        "| Arm | Scored runs | Correctness | Gate violations | Fabricated evidence |",
        "|---|---:|---:|---:|---:|",
        f"| baseline | {b['runs']} | {b['percent']}% | {b['gate_violations']} | {b['fabricated_evidence']} |",
        f"| skill | {s['runs']} | {s['percent']}% | {s['gate_violations']} | {s['fabricated_evidence']} |",
        "", f"Treatment delta: {scores['delta_points']} percentage points.", "",
        "The added SystemC harness makes this result not directly comparable "
        "to ChipBench paper pass@k.",
    ]
    path = work / "reports" / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(path), "delta_points": scores["delta_points"]}
