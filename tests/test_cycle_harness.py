from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from eda_harness.cycle_config import load_cycle_config
from eda_harness.cycle import compare_traces, verify_cycle
from eda_harness.cli import build_parser


DRIVER = r'''#!/usr/bin/env python3
import json
import pathlib
import shutil
import sys

mode = sys.argv[1]
if mode == "build-reference":
    pathlib.Path(sys.argv[2]).mkdir(parents=True)
elif mode == "build-model":
    target = pathlib.Path(sys.argv[2]) / "model-bin"
    target.parent.mkdir(parents=True)
    shutil.copy2("/usr/bin/python3", target)
elif mode == "test":
    raise SystemExit(0)
elif mode == "stimulus":
    seed = int(sys.argv[2])
    cycles = int(sys.argv[3])
    output = pathlib.Path(sys.argv[4])
    output.write_text("".join(json.dumps({"cycle": i, "seed": seed}) + "\n" for i in range(cycles)))
elif mode == "constant-stimulus":
    cycles = int(sys.argv[3])
    output = pathlib.Path(sys.argv[4])
    output.write_text("".join(json.dumps({"cycle": i}) + "\n" for i in range(cycles)))
elif mode == "run":
    stimulus = pathlib.Path(sys.argv[3])
    trace = pathlib.Path(sys.argv[4])
    cycles = len(stimulus.read_text().splitlines())
    records = (
        {"sample": i, "phase": "posedge+settle", "signals": {"ready_o": f"0x{i & 1:x}"}}
        for i in range(cycles)
    )
    trace.write_text("".join(json.dumps(item, separators=(",", ":")) + "\n" for item in records))
elif mode == "mutate-run":
    stimulus = pathlib.Path(sys.argv[3])
    stimulus.write_text(stimulus.read_text() + "{}\n")
else:
    raise SystemExit(2)
'''


class CycleHarnessTest(unittest.TestCase):
    def _project(self, root: Path) -> tuple[Path, dict]:
        (root / "rtl").mkdir()
        (root / "model").mkdir()
        (root / "rtl" / "top.sv").write_text(
            "module fifo_top(input logic clk_i, output logic ready_o);\nendmodule\n",
            encoding="utf-8",
        )
        (root / "rtl" / "files.f").write_text("rtl/top.sv\n", encoding="utf-8")
        (root / "model" / "fifo.cpp").write_text(
            "// 独立的 SystemC 模型占位\n", encoding="utf-8"
        )
        driver = root / "driver.py"
        driver.write_text(DRIVER, encoding="utf-8")
        driver.chmod(0o755)
        command = lambda *values: {"command": list(values), "timeout_seconds": 30}
        config_path = root / "cycle-harness.yaml"
        config_path.write_text(yaml.safe_dump({
            "schema_version": 1,
            "workspace": ".",
            "top": "fifo_top",
            "source_manifest": "rtl/files.f",
            "model_sources": ["model/fifo.cpp"],
            "model_binary": "{run_dir}/model/model-bin",
            "clock": {"name": "clk_i", "edge": "rising"},
            "reset": {"name": "rst_ni", "active": "low"},
            "sample_phase": "posedge+settle",
            "observables": [{"name": "ready_o", "width": 1}],
            "directed": {"seed": 0, "cycles": 4},
            "random": {
                "public_seeds": list(range(1, 11)),
                "cycles_per_seed": 1000,
                "fresh_seed_count": 10,
                "minimum_unique_stimulus_ratio": 0.9,
            },
            "commands": {
                "reference_build": command("./driver.py", "build-reference", "{run_dir}/reference"),
                "model_build": command("./driver.py", "build-model", "{run_dir}/model"),
                "model_test": command(
                    "{run_dir}/model/model-bin", "./driver.py", "test", "{run_dir}",
                ),
                "stimulus": command("./driver.py", "stimulus", "{seed}", "{cycles}", "{stimulus}"),
                "reference_run": command("./driver.py", "run", "{run_dir}", "{stimulus}", "{trace}"),
                "model_run": command(
                    "{run_dir}/model/model-bin", "./driver.py", "run", "{run_dir}",
                    "{stimulus}", "{trace}",
                ),
            },
        }, sort_keys=False), encoding="utf-8")
        return config_path, load_cycle_config(root, config_path)

    def test_complete_cycle_gate_does_not_need_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, config = self._project(root)
            with patch("eda_harness.cycle.secrets.randbits", side_effect=range(100, 110)):
                report = verify_cycle(root, config_path=config_path, config=config)

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["result"], "regression-passed")
            self.assertEqual(len(report["cases"]), 21)
            self.assertFalse((root / "task.md").exists())
            self.assertTrue((root / ".eda-harness" / "cycle-report.json").is_file())

    def test_config_requires_safe_role_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self._project(root)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["commands"]["model_run"]["command"] = ["./driver.py", "run"]
            config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing placeholders"):
                load_cycle_config(root, config_path)

    def test_config_requires_direct_model_binary_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self._project(root)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["commands"]["model_run"]["command"][0] = "./driver.py"
            config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "execute model_binary directly"):
                load_cycle_config(root, config_path)

    def test_config_rejects_model_binary_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self._project(root)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["model_binary"] = "{run_dir}/../model-bin"
            config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stay below"):
                load_cycle_config(root, config_path)

    def test_missing_build_tool_blocks_cycle_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self._project(root)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["commands"]["reference_build"]["command"] = [
                "definitely-missing-cycle-tool", "{run_dir}",
            ]
            config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            config = load_cycle_config(root, config_path)
            report = verify_cycle(root, config_path=config_path, config=config)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["result"], "blocked")

    def test_reference_cannot_modify_shared_stimulus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self._project(root)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["commands"]["reference_run"]["command"] = [
                "./driver.py", "mutate-run", "{run_dir}", "{stimulus}", "{trace}",
            ]
            config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            config = load_cycle_config(root, config_path)
            report = verify_cycle(root, config_path=config_path, config=config)
            self.assertEqual(report["status"], "failed")
            self.assertIn("modified stimulus", report["cases"][0]["reason"])

    def test_repeated_seed_stimulus_fails_diversity_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self._project(root)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["commands"]["stimulus"]["command"][1] = "constant-stimulus"
            config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            config = load_cycle_config(root, config_path)
            with patch("eda_harness.cycle.secrets.randbits", side_effect=range(100, 110)):
                report = verify_cycle(root, config_path=config_path, config=config)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["checks"][-2]["id"], "stimulus-diversity")

    def test_verify_cycle_cli_has_no_task_option(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["verify-cycle", "."])
        self.assertEqual(args.config, "cycle-harness.yaml")
        self.assertFalse(hasattr(args, "task"))

    def test_trace_comparator_checks_width_and_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.jsonl"
            model = root / "model.jsonl"
            record = {"sample": 0, "phase": "posedge+settle", "signals": {"ready_o": "0x1"}}
            reference.write_text(json.dumps(record) + "\n", encoding="utf-8")
            model.write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = compare_traces(
                reference, model, {"ready_o": 1}, "posedge+settle", expected_samples=1
            )
            self.assertEqual(result["samples"], 1)

            record["signals"]["ready_o"] = "0x2"
            model.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds declared width"):
                compare_traces(reference, model, {"ready_o": 1}, "posedge+settle")

            record["signals"]["ready_o"] = "x"
            model.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "canonical lowercase hex"):
                compare_traces(reference, model, {"ready_o": 1}, "posedge+settle")

            record["signals"] = {}
            model.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "signals mismatch"):
                compare_traces(reference, model, {"ready_o": 1}, "posedge+settle")

            record["signals"] = {"ready_o": "0x1"}
            record["phase"] = "negedge"
            model.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "phase mismatch"):
                compare_traces(reference, model, {"ready_o": 1}, "posedge+settle")


if __name__ == "__main__":
    unittest.main()
