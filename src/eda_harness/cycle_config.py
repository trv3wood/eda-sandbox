"""Cycle-SystemC harness 的类型化配置与解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


COMMAND_ROLES = (
    "reference_build",
    "model_build",
    "model_test",
    "stimulus",
    "reference_run",
    "model_run",
)
ALLOWED_PLACEHOLDERS = frozenset({
    "{run_dir}", "{seed}", "{cycles}", "{stimulus}", "{trace}",
})
REQUIRED_PLACEHOLDERS = {
    "reference_build": {"{run_dir}"},
    "model_build": {"{run_dir}"},
    "model_test": {"{run_dir}"},
    "stimulus": {"{seed}", "{cycles}", "{stimulus}"},
    "reference_run": {"{run_dir}", "{stimulus}", "{trace}"},
    "model_run": {"{run_dir}", "{stimulus}", "{trace}"},
}
FORBIDDEN_MODEL_COMMANDS = re.compile(
    r"(?:^|[/_-])(?:verilator|verilated|vcs|xrun|vsim|qrun|iverilog)(?:$|[/_.-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommandSpec:
    """一个无需 shell 的项目命令。"""

    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int


@dataclass(frozen=True)
class SignalSpec:
    """需要逐周期比较的信号。"""

    name: str
    width: int


@dataclass(frozen=True)
class CycleCase:
    """一组可复现的差分 stimulus。"""

    kind: str
    seed: int
    cycles: int


@dataclass(frozen=True)
class CycleHarnessConfig:
    """完成校验后的 Cycle-SystemC 配置。"""

    workspace: str
    source_manifest: str
    model_sources: tuple[str, ...]
    model_binary: str
    top: str
    clock_name: str
    clock_edge: str
    reset_name: str
    reset_active: str
    sample_phase: str
    observables: tuple[SignalSpec, ...]
    directed_case: CycleCase
    public_seeds: tuple[int, ...]
    cycles_per_seed: int
    fresh_seed_count: int
    minimum_unique_stimulus_ratio: float
    commands: dict[str, CommandSpec]

    @property
    def observable_widths(self) -> dict[str, int]:
        return {item.name: item.width for item in self.observables}

    def command(self, role: str) -> CommandSpec:
        return self.commands[role]

    def public_cases(self) -> list[CycleCase]:
        return [
            CycleCase("public-random", seed, self.cycles_per_seed)
            for seed in self.public_seeds
        ]

    def model_binary_path(self, run_dir: Path) -> Path:
        return Path(self.model_binary.replace("{run_dir}", str(run_dir)))


class CycleConfigLoader:
    """把 YAML 边界数据转换为不可变领域对象。"""

    def __init__(self, root: Path, path: Path) -> None:
        self.root = root.resolve()
        self.path = path
        self.workspace = self.root

    def load(self) -> CycleHarnessConfig:
        raw = self._read_yaml()
        self.workspace = self._workspace(raw)
        source_manifest = self._required_file(raw, "source_manifest")
        model_sources = self._model_sources(raw)
        model_binary = self._model_binary(raw)
        commands = self._commands(raw, model_binary)
        clock = self._named_choice(raw, "clock", "edge", {"rising", "falling"})
        reset = self._named_choice(raw, "reset", "active", {"high", "low"})
        directed = self._directed_case(raw)
        public_seeds, cycles_per_seed, fresh_seed_count, unique_ratio = self._random(raw)
        return CycleHarnessConfig(
            workspace=str(self.workspace.relative_to(self.root)),
            source_manifest=source_manifest,
            model_sources=model_sources,
            model_binary=model_binary,
            top=self._non_empty_string(raw, "top"),
            clock_name=clock["name"],
            clock_edge=clock["edge"],
            reset_name=reset["name"],
            reset_active=reset["active"],
            sample_phase=self._non_empty_string(raw, "sample_phase"),
            observables=self._observables(raw),
            directed_case=directed,
            public_seeds=public_seeds,
            cycles_per_seed=cycles_per_seed,
            fresh_seed_count=fresh_seed_count,
            minimum_unique_stimulus_ratio=unique_ratio,
            commands=commands,
        )

    def _read_yaml(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("cycle harness config must be a YAML mapping")
        if raw.get("schema_version") != 1:
            raise ValueError("cycle harness schema_version must be 1")
        return raw

    def _workspace(self, raw: dict[str, Any]) -> Path:
        value = raw.get("workspace", ".")
        if not isinstance(value, str) or not value:
            raise ValueError("workspace must be a non-empty relative path")
        workspace = self._inside(self.root, value, "workspace")
        if not workspace.is_dir():
            raise FileNotFoundError(f"workspace does not exist: {workspace}")
        return workspace

    @staticmethod
    def _inside(root: Path, value: str, field: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute():
            raise ValueError(f"{field} must be relative")
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"{field} escapes the config root") from exc
        return resolved

    def _required_file(self, raw: dict[str, Any], field: str) -> str:
        value = self._non_empty_string(raw, field)
        path = self._inside(self.workspace, value, field)
        if not path.is_file():
            raise FileNotFoundError(f"{field} does not exist: {path}")
        return str(path.relative_to(self.workspace))

    def _model_sources(self, raw: dict[str, Any]) -> tuple[str, ...]:
        values = raw.get("model_sources")
        if not isinstance(values, list) or not values:
            raise ValueError("model_sources must be a non-empty list")
        sources = tuple(
            self._existing_relative_file(value, f"model_sources[{index}]")
            for index, value in enumerate(values, 1)
        )
        if len(set(sources)) != len(sources):
            raise ValueError("model_sources must be unique")
        return sources

    def _existing_relative_file(self, value: Any, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a relative path")
        path = self._inside(self.workspace, value, field)
        if not path.is_file():
            raise FileNotFoundError(f"{field} does not exist: {path}")
        return str(path.relative_to(self.workspace))

    @staticmethod
    def _model_binary(raw: dict[str, Any]) -> str:
        value = raw.get("model_binary")
        if not isinstance(value, str) or not value.startswith("{run_dir}/"):
            raise ValueError("model_binary must be a path below {run_dir}")
        if set(re.findall(r"\{[^{}]+\}", value)) != {"{run_dir}"}:
            raise ValueError("model_binary only supports the {run_dir} placeholder")
        suffix = Path(value.removeprefix("{run_dir}/"))
        if suffix.is_absolute() or ".." in suffix.parts:
            raise ValueError("model_binary must stay below {run_dir}")
        return value

    def _commands(
        self, raw: dict[str, Any], model_binary: str
    ) -> dict[str, CommandSpec]:
        values = raw.get("commands")
        if not isinstance(values, dict):
            raise ValueError("commands must be a mapping")
        missing = set(COMMAND_ROLES) - set(values)
        extra = set(values) - set(COMMAND_ROLES)
        if missing or extra:
            raise ValueError(
                f"commands must define exactly {list(COMMAND_ROLES)}; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        commands = {
            role: self._command_spec(role, values[role]) for role in COMMAND_ROLES
        }
        for role in ("model_test", "model_run"):
            if commands[role].argv[0] != model_binary:
                raise ValueError(f"commands.{role} must execute model_binary directly")
        return commands

    def _command_spec(self, role: str, raw: Any) -> CommandSpec:
        if not isinstance(raw, dict):
            raise ValueError(f"commands.{role} must be a mapping")
        argv = raw.get("command")
        if not isinstance(argv, list) or not argv or not all(
            isinstance(value, str) and value for value in argv
        ):
            raise ValueError(f"commands.{role}.command must be a non-empty argv list")
        placeholders = {
            placeholder
            for value in argv
            for placeholder in re.findall(r"\{[^{}]+\}", value)
        }
        unknown = placeholders - ALLOWED_PLACEHOLDERS
        if unknown:
            raise ValueError(
                f"commands.{role}.command uses unknown placeholders: {sorted(unknown)}"
            )
        missing = REQUIRED_PLACEHOLDERS[role] - placeholders
        if missing:
            raise ValueError(
                f"commands.{role}.command is missing placeholders: {sorted(missing)}"
            )
        if role.startswith("model_") and any(
            FORBIDDEN_MODEL_COMMANDS.search(value) for value in argv
        ):
            raise ValueError(f"commands.{role} references a forbidden RTL simulator")
        cwd_value = raw.get("cwd", ".")
        if not isinstance(cwd_value, str) or not cwd_value:
            raise ValueError(f"commands.{role}.cwd must be a relative path")
        cwd = self._inside(self.workspace, cwd_value, f"commands.{role}.cwd")
        if not cwd.is_dir():
            raise FileNotFoundError(f"commands.{role}.cwd does not exist: {cwd}")
        timeout = raw.get("timeout_seconds", 1800)
        if not self._positive_int(timeout):
            raise ValueError(
                f"commands.{role}.timeout_seconds must be a positive integer"
            )
        return CommandSpec(tuple(argv), str(cwd.relative_to(self.workspace)), timeout)

    @staticmethod
    def _named_choice(
        raw: dict[str, Any], field: str, choice: str, allowed: set[str]
    ) -> dict[str, str]:
        value = raw.get(field)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("name"), str)
            or not value["name"]
        ):
            raise ValueError(f"{field}.name must be a non-empty string")
        if value.get(choice) not in allowed:
            raise ValueError(f"{field}.{choice} must be one of {sorted(allowed)}")
        return {"name": value["name"], choice: value[choice]}

    @staticmethod
    def _observables(raw: dict[str, Any]) -> tuple[SignalSpec, ...]:
        values = raw.get("observables")
        if not isinstance(values, list) or not values:
            raise ValueError("observables must be a non-empty list")
        result: list[SignalSpec] = []
        names: set[str] = set()
        for index, item in enumerate(values, 1):
            if not isinstance(item, dict):
                raise ValueError(f"observables[{index}] must be a mapping")
            name = item.get("name")
            width = item.get("width")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError(
                    f"observables[{index}].name must be unique and non-empty"
                )
            if not CycleConfigLoader._positive_int(width):
                raise ValueError(
                    f"observables[{index}].width must be a positive integer"
                )
            names.add(name)
            result.append(SignalSpec(name, width))
        return tuple(result)

    @staticmethod
    def _directed_case(raw: dict[str, Any]) -> CycleCase:
        value = raw.get("directed")
        if not isinstance(value, dict):
            raise ValueError("directed must be a mapping")
        seed = value.get("seed", 0)
        cycles = value.get("cycles")
        CycleConfigLoader._validate_seed(seed, "directed.seed")
        if not CycleConfigLoader._positive_int(cycles):
            raise ValueError("directed.cycles must be a positive integer")
        return CycleCase("directed", seed, cycles)

    @staticmethod
    def _random(raw: dict[str, Any]) -> tuple[tuple[int, ...], int, int, float]:
        value = raw.get("random")
        if not isinstance(value, dict):
            raise ValueError("random must be a mapping")
        seeds = value.get("public_seeds")
        if not isinstance(seeds, list) or len(seeds) < 10:
            raise ValueError("random.public_seeds must contain at least 10 seeds")
        for seed in seeds:
            CycleConfigLoader._validate_seed(seed, "random.public_seeds")
        if len(set(seeds)) != len(seeds):
            raise ValueError("random.public_seeds must be unique")
        cycles = value.get("cycles_per_seed", 1000)
        if not CycleConfigLoader._positive_int(cycles) or cycles < 1000:
            raise ValueError("random.cycles_per_seed must be at least 1000")
        fresh_count = value.get("fresh_seed_count", 10)
        if not CycleConfigLoader._positive_int(fresh_count) or fresh_count < 10:
            raise ValueError("random.fresh_seed_count must be at least 10")
        unique_ratio = value.get("minimum_unique_stimulus_ratio", 0.9)
        if (
            not isinstance(unique_ratio, (int, float))
            or isinstance(unique_ratio, bool)
            or not 0 < float(unique_ratio) <= 1
        ):
            raise ValueError(
                "random.minimum_unique_stimulus_ratio must be in (0, 1]"
            )
        return tuple(seeds), cycles, fresh_count, float(unique_ratio)

    @staticmethod
    def _validate_seed(value: Any, field: str) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value < 2**63
        ):
            raise ValueError(f"{field} must be a non-negative 63-bit integer")

    @staticmethod
    def _positive_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @staticmethod
    def _non_empty_string(raw: dict[str, Any], field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a non-empty string")
        return value


def load_cycle_config(root: Path, path: Path) -> CycleHarnessConfig:
    """兼容入口：读取类型化 Cycle-SystemC 配置。"""
    return CycleConfigLoader(root, path).load()
