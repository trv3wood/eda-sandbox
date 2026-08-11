"""Cycle-accurate SystemC 强门禁的流程编排。"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cycle_config import CycleCase, CycleHarnessConfig
from .cycle_evidence import EvidenceValidator, ModelAuditor, file_digest
from .cycle_runtime import CommandContext, CommandRunner
from .cycle_trace import TraceComparator
from .state import STATE_DIR


class ProtectedInputs:
    """记录并检查验收期间不可变化的输入。"""

    def __init__(self, paths: list[Path]) -> None:
        self.hashes = {str(path): file_digest(path) for path in paths}

    def changed_paths(self) -> list[str]:
        return [
            name
            for name, digest in self.hashes.items()
            if not Path(name).is_file() or file_digest(Path(name)) != digest
        ]

    def digest(self, path: Path) -> str:
        return self.hashes[str(path)]


@dataclass(frozen=True)
class CasePaths:
    """单个差分用例的隔离产物。"""

    directory: Path
    stimulus: Path
    reference_trace: Path
    model_trace: Path

    @classmethod
    def create(cls, run_dir: Path, index: int, case: CycleCase) -> "CasePaths":
        directory = run_dir / f"case-{index:03d}-{case.kind}-{case.seed}"
        directory.mkdir()
        return cls(
            directory=directory,
            stimulus=directory / "stimulus.jsonl",
            reference_trace=directory / "reference.jsonl",
            model_trace=directory / "model.jsonl",
        )


class CycleVerifier:
    """编排证据、构建、定向与随机差分门禁。"""

    def __init__(
        self, root: Path, config_path: Path, config: CycleHarnessConfig
    ) -> None:
        self.root = root.resolve()
        self.config_path = config_path.resolve()
        self.config = config
        self.workspace = (self.root / config.workspace).resolve()
        self.state_dir = self.root / STATE_DIR
        self.run_dir = (
            self.state_dir / "cycle-runs" / f"{time.time_ns()}-{os.getpid()}"
        )
        self.logs = self.run_dir / "logs"
        self.logs.mkdir(parents=True)
        self.runner = CommandRunner(self.workspace, self.logs)
        self.auditor = ModelAuditor(self.workspace, config.model_sources)
        self.comparator = TraceComparator(
            config.observable_widths, config.sample_phase
        )
        self.checks: list[dict[str, Any]] = []
        self.case_reports: list[dict[str, Any]] = []
        self.status = "passed"
        self.protected = ProtectedInputs(self._protected_paths())
        self.fresh_seeds = self._fresh_seeds()

    def verify(self) -> dict[str, Any]:
        self._validate_evidence_and_sources()
        if self.status == "passed":
            self._run_build_gates()
        if self.status == "passed":
            self._run_cases()
        self._check_protected_inputs()
        report = self._build_report()
        self._write_report(report)
        return report

    def _protected_paths(self) -> list[Path]:
        return [
            self.config_path,
            self.workspace / self.config.evidence,
            self.workspace / self.config.source_manifest,
            *[
                self.workspace / relative
                for relative in self.config.model_sources
            ],
        ]

    def _validate_evidence_and_sources(self) -> None:
        try:
            EvidenceValidator(self.workspace, self.config.top).validate(
                self.workspace / self.config.evidence
            )
            self.auditor.audit_sources()
            self.checks.append({"id": "evidence-and-audit", "status": "passed"})
        except (FileNotFoundError, ValueError) as exc:
            self._fail("evidence-and-audit", exc)

    def _run_build_gates(self) -> None:
        context = CommandContext(self.run_dir)
        for role in ("reference_build", "model_build", "model_test"):
            result = self.runner.run(role, self.config.command(role), context)
            self.checks.append(result)
            if result["status"] != "passed":
                self.status = result["status"]
                return
            if role == "model_build" and not self._audit_binary():
                return

    def _audit_binary(self) -> bool:
        try:
            audit = self.auditor.audit_binary(
                self.config.model_binary_path(self.run_dir)
            )
            self.checks.append({
                "id": "model-binary-audit", "status": "passed", **audit,
            })
            return True
        except (FileNotFoundError, ValueError) as exc:
            self._fail("model-binary-audit", exc)
            return False

    def _run_cases(self) -> None:
        for index, case in enumerate(self._cases()):
            paths = CasePaths.create(self.run_dir, index, case)
            self.case_reports.append(self._run_case(index, case, paths))
            if self.status != "passed":
                return

    def _run_case(
        self, index: int, case: CycleCase, paths: CasePaths
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "kind": case.kind, "seed": case.seed, "cycles": case.cycles,
        }
        stimulus_digest = self._generate_stimulus(index, case, paths, report)
        if stimulus_digest is None:
            return report
        if not self._run_models(index, case, paths, stimulus_digest, report):
            return report
        return self._compare_case(case, paths, stimulus_digest, report)

    def _generate_stimulus(
        self,
        index: int,
        case: CycleCase,
        paths: CasePaths,
        report: dict[str, Any],
    ) -> str | None:
        context = CommandContext(
            self.run_dir, case.seed, case.cycles, paths.stimulus
        )
        result = self.runner.run(
            f"{index:03d}-stimulus", self.config.command("stimulus"), context
        )
        self.checks.append(result)
        if result["status"] != "passed":
            self.status = result["status"]
            report.update({"status": self.status, "reason": result.get("reason")})
            return None
        if not paths.stimulus.is_file():
            self.status = "failed"
            report.update({
                "status": "failed", "reason": "stimulus was not produced",
            })
            return None
        return file_digest(paths.stimulus)

    def _run_models(
        self,
        index: int,
        case: CycleCase,
        paths: CasePaths,
        stimulus_digest: str,
        report: dict[str, Any],
    ) -> bool:
        for role, trace in (
            ("reference_run", paths.reference_trace),
            ("model_run", paths.model_trace),
        ):
            context = CommandContext(
                self.run_dir, case.seed, case.cycles, paths.stimulus, trace
            )
            result = self.runner.run(
                f"{index:03d}-{role}", self.config.command(role), context
            )
            self.checks.append(result)
            if result["status"] != "passed":
                self.status = result["status"]
                report.update({"status": self.status, "reason": result.get("reason")})
                return False
            if file_digest(paths.stimulus) != stimulus_digest:
                self.status = "failed"
                report.update({
                    "status": "failed", "reason": f"{role} modified stimulus",
                })
                return False
        return True

    def _compare_case(
        self,
        case: CycleCase,
        paths: CasePaths,
        stimulus_digest: str,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            comparison = self.comparator.compare(
                paths.reference_trace, paths.model_trace, case.cycles
            )
            report.update({
                "status": "passed",
                **comparison,
                "stimulus_sha256": stimulus_digest,
            })
        except (FileNotFoundError, ValueError) as exc:
            self.status = "failed"
            report.update({"status": "failed", "reason": str(exc)})
        return report

    def _cases(self) -> list[CycleCase]:
        return [
            self.config.directed_case,
            *self.config.public_cases(),
            *[
                CycleCase("fresh-random", seed, self.config.cycles_per_seed)
                for seed in self.fresh_seeds
            ],
        ]

    def _fresh_seeds(self) -> list[int]:
        used = {*self.config.public_seeds, self.config.directed_case.seed}
        result: list[int] = []
        while len(result) < self.config.fresh_seed_count:
            seed = secrets.randbits(63)
            if seed not in used:
                used.add(seed)
                result.append(seed)
        return result

    def _check_protected_inputs(self) -> None:
        changed = self.protected.changed_paths()
        if changed:
            self.status = "failed"
            self.checks.append({
                "id": "protected-inputs",
                "status": "failed",
                "reason": f"verification modified protected inputs: {changed}",
            })
        else:
            self.checks.append({"id": "protected-inputs", "status": "passed"})

    def _fail(self, identifier: str, error: Exception) -> None:
        self.status = "failed"
        self.checks.append({
            "id": identifier, "status": "failed", "reason": str(error),
        })

    def _build_report(self) -> dict[str, Any]:
        evidence = self.workspace / self.config.evidence
        manifest = self.workspace / self.config.source_manifest
        return {
            "schema_version": 1,
            "status": self.status,
            "result": self._result_name(),
            "config": {
                "path": str(self.config_path),
                "sha256": self.protected.digest(self.config_path),
            },
            "evidence": {
                "path": self.config.evidence,
                "sha256": self.protected.digest(evidence),
            },
            "source_manifest": {
                "path": self.config.source_manifest,
                "sha256": self.protected.digest(manifest),
            },
            "run_dir": str(self.run_dir),
            "public_seeds": list(self.config.public_seeds),
            "fresh_seeds": self.fresh_seeds,
            "checks": self.checks,
            "cases": self.case_reports,
        }

    def _result_name(self) -> str:
        if self.status == "passed":
            return "cycle-equivalent"
        if self.status == "blocked":
            return "blocked"
        return "not-cycle-equivalent"

    def _write_report(self, report: dict[str, Any]) -> None:
        self.state_dir.mkdir(exist_ok=True)
        (self.state_dir / "cycle-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def validate_evidence(workspace: Path, path: Path, top: str) -> dict[str, Any]:
    """兼容入口：校验证据文件。"""
    return EvidenceValidator(workspace, top).validate(path)


def audit_model(workspace: Path, model_sources: list[str]) -> None:
    """兼容入口：审计模型源码。"""
    ModelAuditor(workspace, tuple(model_sources)).audit_sources()


def audit_model_binary(path: Path) -> dict[str, Any]:
    """兼容入口：审计模型二进制。"""
    return ModelAuditor(path.parent, ()).audit_binary(path)


def compare_traces(
    reference: Path,
    model: Path,
    observables: dict[str, int],
    sample_phase: str,
    expected_samples: int | None = None,
) -> dict[str, Any]:
    """兼容入口：逐样点比较两份标准 JSONL trace。"""
    return TraceComparator(observables, sample_phase).compare(
        reference, model, expected_samples
    )


def verify_cycle(
    root: Path, *, config_path: Path, config: CycleHarnessConfig
) -> dict[str, Any]:
    """兼容入口：执行 Cycle-SystemC 强门禁。"""
    return CycleVerifier(root, config_path, config).verify()
