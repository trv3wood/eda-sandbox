"""统一 EDA harness 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config, load_cycle_config
from .cycle import verify_cycle
from .discovery import discover, summarize_discovery
from .state import STATE_DIR
from .toolchain import CONFIG_ENV, load_toolchain_config
from .verification import verify


def _path(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eda-harness")
    parser.add_argument(
        "--toolchain-config",
        help=f"白名单 KEY=VALUE 工具链配置（也可使用 {CONFIG_ENV}）",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    discover_parser = commands.add_parser("discover", help="探测 EDA 与构建能力")
    discover_parser.add_argument("root", nargs="?", default=".")
    discover_parser.add_argument(
        "--full",
        action="store_true",
        help="在标准输出打印完整报告；默认打印 Agent 摘要",
    )
    for name, help_text in (("verify", "执行验证命令"),):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("root", nargs="?", default=".")
        command.add_argument("--task", default="task.md")
        command.add_argument("--config", default="harness.yaml")
    cycle = commands.add_parser("verify-cycle", help="执行 Cycle-SystemC 强差分门禁")
    cycle.add_argument("root", nargs="?", default=".")
    cycle.add_argument("--config", default="cycle-harness.yaml")
    status = commands.add_parser("status", help="读取最近的 harness 状态")
    status.add_argument("root", nargs="?", default=".")
    return parser


def _status(root: Path) -> dict[str, object]:
    state = root / STATE_DIR
    result: dict[str, object] = {}
    for name in ("discovery_summary", "discovery", "report", "cycle_report"):
        filename = name.replace("_", "-") if name in {
            "discovery_summary", "cycle_report"
        } else name
        path = state / f"{filename}.json"
        result[name] = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        load_toolchain_config(args.toolchain_config)
        root = Path(args.root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)
        if args.command == "discover":
            full_report = discover(root)
            result = full_report if args.full else summarize_discovery(full_report)
        elif args.command == "status":
            result = _status(root)
        elif args.command == "verify-cycle":
            config_path = _path(root, args.config)
            config = load_cycle_config(root, config_path)
            result = verify_cycle(root, config_path=config_path, config=config)
        else:
            config_path = _path(root, args.config)
            task_path = _path(root, args.task)
            config = load_config(root, config_path)
            result = verify(root, config_path=config_path, task_path=task_path, config=config)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        if args.command in {"verify", "verify-cycle"} and result["status"] != "passed":
            return 1
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
