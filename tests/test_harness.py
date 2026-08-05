from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from eda_harness.config import load_config
from eda_harness.discovery import _probe, discover
from eda_harness.snapshot import create_snapshot
from eda_harness.toolchain import load_toolchain_config
from eda_harness.verification import verify


class HarnessTest(unittest.TestCase):
    def _project(self, root: Path) -> tuple[Path, Path, dict]:
        task = root / "task.md"
        task.write_text("实现并验证一个小修改。\n", encoding="utf-8")
        config_path = root / "harness.yaml"
        config_path.write_text(
            yaml.safe_dump({
                "schema_version": 1,
                "workspace": ".",
                "allowed_changes": ["src/**"],
                "checks": [{
                    "id": "syntax",
                    "category": "syntax",
                    "command": ["python3", "-c", "print('ok')"],
                    "timeout_seconds": 10,
                }],
            }, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (root / "src").mkdir()
        (root / "src" / "model.cpp").write_text("// 基线\n", encoding="utf-8")
        return task, config_path, load_config(root, config_path)

    def test_snapshot_accepts_allowed_increment_and_preserves_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, config = self._project(root)
            create_snapshot(root, config_path=config_path, task_path=task, config=config)
            (root / "src" / "model.cpp").write_text("// 修改\n", encoding="utf-8")
            (root / "src" / "added.cpp").write_text("// 新增\n", encoding="utf-8")

            report = verify(root, config_path=config_path, task_path=task, config=config)

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["integrity"]["modified"], ["src/model.cpp"])
            self.assertEqual(report["integrity"]["added"], ["src/added.cpp"])

    def test_change_outside_locked_scope_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, config = self._project(root)
            (root / "README.md").write_text("原内容\n", encoding="utf-8")
            create_snapshot(root, config_path=config_path, task_path=task, config=config)
            (root / "README.md").write_text("越界内容\n", encoding="utf-8")
            config["allowed_changes"] = ["**"]

            report = verify(root, config_path=config_path, task_path=task, config=config)

            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["integrity"]["violations"], ["README.md"])

    def test_missing_required_tool_blocks_and_optional_failure_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, config = self._project(root)
            config["checks"] = [
                {
                    "id": "missing", "category": "lint",
                    "command": ["definitely-not-an-eda-tool"], "cwd": ".",
                    "timeout_seconds": 1, "required": True, "depends_on": [],
                },
                {
                    "id": "optional", "category": "test",
                    "command": ["python3", "-c", "raise SystemExit(2)"], "cwd": ".",
                    "timeout_seconds": 10, "required": False, "depends_on": [],
                },
            ]
            create_snapshot(root, config_path=config_path, task_path=task, config=config)

            report = verify(root, config_path=config_path, task_path=task, config=config)

            self.assertEqual(report["status"], "blocked")
            self.assertEqual([item["status"] for item in report["checks"]], ["blocked", "failed"])

    def test_config_rejects_shell_string_and_forward_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, _ = self._project(root)
            del task
            value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            value["checks"][0]["command"] = "make && make test"
            config_path.write_text(yaml.safe_dump(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "argv"):
                load_config(root, config_path)

            value["checks"] = [
                {"id": "test", "command": ["true"], "depends_on": ["build"]},
                {"id": "build", "command": ["true"]},
            ]
            config_path.write_text(yaml.safe_dump(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown or later"):
                load_config(root, config_path)

    @unittest.skipUnless(shutil.which("git"), "Git is unavailable")
    def test_git_dirty_content_at_snapshot_is_the_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, config = self._project(root)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "src/model.cpp"], check=True)
            (root / "src" / "model.cpp").write_text("// 用户已有脏改动\n", encoding="utf-8")
            create_snapshot(root, config_path=config_path, task_path=task, config=config)
            (root / "src" / "model.cpp").write_text("// 本次任务改动\n", encoding="utf-8")
            report = verify(root, config_path=config_path, task_path=task, config=config)
            self.assertEqual(report["integrity"]["modified"], ["src/model.cpp"])
            self.assertEqual(report["status"], "passed")

    def test_workspace_symlink_cannot_escape_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            (root / "external").symlink_to(outside, target_is_directory=True)
            config_path = root / "harness.yaml"
            config_path.write_text(yaml.safe_dump({
                "schema_version": 1,
                "workspace": "external",
                "allowed_changes": ["**"],
                "checks": [{"id": "ok", "command": ["true"]}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                load_config(root, config_path)

    @patch("eda_harness.discovery.subprocess.run")
    @patch("eda_harness.discovery.shutil.which")
    def test_discovery_reports_without_exposing_license_values(self, which, run) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"SNPSLMD_LICENSE_FILE": "secret-server"}, clear=False
        ):
            which.return_value = None
            result = discover(Path(temporary))
            encoded = json.dumps(result)
            self.assertTrue(result["license_environment"]["SNPSLMD_LICENSE_FILE"])
            self.assertNotIn("secret-server", encoded)
            run.assert_not_called()

    def test_toolchain_rejects_unknown_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tools.env"
            path.write_text("DANGEROUS=value\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "supported KEY=VALUE"):
                load_toolchain_config(str(path))

    def test_explicit_tool_path_precedes_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "verilator-custom"
            tool.write_text(
                "#!/usr/bin/env bash\nprintf 'custom verilator\\n'\n",
                encoding="utf-8",
            )
            tool.chmod(0o755)
            with patch.dict("os.environ", {"EDA_TOOL_VERILATOR": str(tool)}):
                result = _probe("verilator")
            self.assertTrue(result["usable"])
            self.assertEqual(result["path"], str(tool.resolve()))
            self.assertEqual(result["source"], "environment:EDA_TOOL_VERILATOR")

    def test_relative_executable_and_dependency_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, config = self._project(root)
            script = root / "check.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            config["checks"] = [
                {
                    "id": "local", "category": "custom", "command": ["./check.sh"],
                    "cwd": ".", "timeout_seconds": 10, "required": True, "depends_on": [],
                },
                {
                    "id": "after", "category": "test", "command": ["python3", "-c", "pass"],
                    "cwd": ".", "timeout_seconds": 10, "required": True, "depends_on": ["local"],
                },
            ]
            create_snapshot(root, config_path=config_path, task_path=task, config=config)
            report = verify(root, config_path=config_path, task_path=task, config=config)
            self.assertEqual(report["status"], "passed")
            self.assertEqual([item["status"] for item in report["checks"]], ["passed", "passed"])

    def test_timeout_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, config_path, config = self._project(root)
            config["checks"] = [{
                "id": "slow", "category": "test",
                "command": ["python3", "-c", "import time; time.sleep(5)"],
                "cwd": ".", "timeout_seconds": 1, "required": True, "depends_on": [],
            }]
            create_snapshot(root, config_path=config_path, task_path=task, config=config)
            report = verify(root, config_path=config_path, task_path=task, config=config)
            self.assertEqual(report["status"], "failed")
            self.assertIn("timed out", report["checks"][0]["reason"])

    @unittest.skipUnless(shutil.which("verilator"), "Verilator is unavailable")
    def test_systemverilog_fixture_discover_snapshot_and_lint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rtl = root / "rtl"
            rtl.mkdir()
            source = rtl / "top.sv"
            source.write_text(
                "module top(input logic a, output logic y); assign y = a; endmodule\n",
                encoding="utf-8",
            )
            task = root / "task.md"
            task.write_text("修改组合逻辑并通过 Verilator lint。\n", encoding="utf-8")
            config_path = root / "harness.yaml"
            config_path.write_text(yaml.safe_dump({
                "schema_version": 1,
                "workspace": ".",
                "allowed_changes": ["rtl/**"],
                "checks": [{
                    "id": "verilator-lint", "category": "lint",
                    "command": ["verilator", "--lint-only", "--top-module", "top", "rtl/top.sv"],
                }],
            }, sort_keys=False), encoding="utf-8")
            discover(root)
            config = load_config(root, config_path)
            create_snapshot(root, config_path=config_path, task_path=task, config=config)
            source.write_text(
                "module top(input logic a, output logic y); always_comb y = a; endmodule\n",
                encoding="utf-8",
            )
            report = verify(root, config_path=config_path, task_path=task, config=config)
            self.assertEqual(report["status"], "passed")


if __name__ == "__main__":
    unittest.main()
