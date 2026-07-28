from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from systemc_tlm_agent.benchmark import (
    _claude_actual_model, _run_claude_filtered, _summarize_claude_jsonl,
    _summarize_codex_jsonl,
    architecture_is_approved, extract_case_with_container, prepare_workspace,
    report_benchmark,
    repository_root, run_benchmark, SANDBOX_MANIFEST, SANDBOX_ROOT,
    SANDBOX_TREATMENT, SANDBOX_WORKSPACE, score_benchmark,
)
from systemc_tlm_agent.io import dump_json, load_json


class BenchmarkTest(unittest.TestCase):
    def _prepared(self, root: Path) -> None:
        prepare_workspace(root)
        lock = load_json(root / "sources" / "lock.json")
        for source in lock["sources"]:
            source.update({"status": "locked", "commit": "a" * 40,
                           "tree_sha256": "b" * 64})
        dump_json(root / "sources" / "lock.json", lock)

    def test_prepare_and_plan_are_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            result = prepare_workspace(work)
            self.assertEqual(result["cases"], 10)
            config = load_json(work / "benchmark.json")
            self.assertEqual(
                config["modeling"]["skill_path"],
                str(
                    repository_root()
                    / "skills/modeling-systemc-tlm/SKILL.md"
                ),
            )
            with self.assertRaisesRegex(ValueError, "not locked"):
                run_benchmark(work, model="gpt-5.6-luna", arm="baseline", trials=1)
            self._prepared(work)
            result = run_benchmark(
                work, model="luna", arm="skill", trials=1,
                cases=["i2c"], isolation_mode="bubblewrap-selective",
            )
            self.assertEqual(result["status"], "planned")
            run = load_json(work / "runs/luna/i2c/skill/1/run.json")
            self.assertEqual(run["exit_status"], "planned")
            prompt = (work / "runs/luna/i2c/skill/1/architect.prompt.txt").read_text()
            self.assertIn(f"Case manifest: {SANDBOX_MANIFEST}", prompt)
            self.assertIn("modeling-systemc-tlm", prompt)
            self.assertIn("run targeted local EDA commands", prompt)
            self.assertIn("Do not claim a tool is unavailable", prompt)
            command = run["command"]
            self.assertTrue(command[0].endswith("bwrap"))
            self.assertIn("--tmpfs", command)
            self.assertIn("--ro-bind / /", " ".join(command))
            self.assertIn("--ignore-user-config", command)
            agent_dir = work / "runs/luna/i2c/skill/1/agent-workspace"
            self.assertIn(str(agent_dir), command)
            self.assertEqual(
                command[command.index("-C") + 1], str(SANDBOX_WORKSPACE)
            )
            self.assertIn(str(SANDBOX_TREATMENT / "skill"), command)

            run_benchmark(
                work, model="luna", arm="baseline", trials=1,
                cases=["i2c"], isolation_mode="bubblewrap-selective",
            )
            baseline = load_json(
                work / "runs/luna/i2c/baseline/1/run.json"
            )["command"]
            self.assertNotIn(str(SANDBOX_TREATMENT / "skill"), baseline)
            self.assertIn(str(repository_root()), baseline)

    def test_implementation_requires_two_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            with self.assertRaisesRegex(ValueError, "review is missing"):
                run_benchmark(
                    work, model="gpt-5.6-luna", arm="baseline", trials=1,
                    cases=["dma"], stage="implement",
                )
            self.assertTrue(architecture_is_approved({
                "reviews": [
                    {"reviewer": "a", "decision": "approve"},
                    {"reviewer": "b", "decision": "reject"},
                    {"reviewer": "c", "decision": "approve"},
                ]
            }))

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("codex"),
                         "bubblewrap and codex are required")
    def test_selective_sandbox_hides_control_data_and_treatment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            run_benchmark(
                work, model="luna", arm="baseline", trials=1,
                cases=["ctrl"], isolation_mode="bubblewrap-selective",
            )
            run_dir = work / "runs/luna/ctrl/baseline/1"
            command = load_json(run_dir / "run.json")["command"]
            codex_index = len(command) - 1 - command[::-1].index(
                str(SANDBOX_ROOT / "runner-bin/codex")
            )
            probe = command[:codex_index] + [
                "/bin/sh",
                "-c",
                f"test -f {SANDBOX_MANIFEST} && "
                f"test ! -e {SANDBOX_TREATMENT} && "
                f"test ! -e {repository_root()}/skills && "
                f"touch {SANDBOX_WORKSPACE}/probe-ok",
            ]
            subprocess.run(probe, check=True)
            self.assertTrue(
                (run_dir / "agent-workspace/probe-ok").is_file()
            )

    def test_score_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            for arm, points in (("baseline", 60), ("skill", 80)):
                run_benchmark(work, model="luna", arm=arm, trials=1,
                              cases=["ctrl"])
                run_dir = work / f"runs/luna/ctrl/{arm}/1"
                score = {
                    name: {"points": points / 4, "possible": 25}
                    for name in ("evidence", "architecture",
                                 "implementation", "functional")
                }
                score.update({"gate_violations": 0, "fabricated_evidence": 0})
                dump_json(run_dir / "score.json", score)
            result = score_benchmark(work)
            self.assertEqual(result["delta_points"], 20.0)
            report = report_benchmark(work)
            self.assertTrue(Path(report["report"]).exists())

    def test_jsonl_summary_extracts_usage_and_final_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "codex.jsonl"
            path.write_text(
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"done"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":10,'
                '"output_tokens":2}}\n',
                encoding="utf-8",
            )
            usage, message = _summarize_codex_jsonl(path)
            self.assertEqual(usage, {"input_tokens": 10, "output_tokens": 2})
            self.assertEqual(message, "done")

    def test_claude_runner_and_container_extraction_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            rtl = work / "sources/chipbench/smoke.sv"
            rtl.parent.mkdir(parents=True, exist_ok=True)
            rtl.write_text("module TopModule; endmodule\n", encoding="utf-8")
            case_path = work / "corpus/chipbench/ctrl/case.json"
            case = load_json(case_path)
            case["input_paths"] = [str(rtl)]
            case["status"] = "ready"
            dump_json(case_path, case)
            extraction = extract_case_with_container(
                work, case="ctrl", top="TopModule",
            )
            self.assertEqual(extraction["status"], "planned")
            self.assertIn("podman", extraction["commands"][0][0])
            self.assertEqual(len(extraction["commands"]), 5)
            flattened = [" ".join(command) for command in extraction["commands"]]
            self.assertIn("localhost/eda-uhdm:local", flattened[2])
            self.assertIn("localhost/eda-rtl:local", flattened[3])
            self.assertIn("tools finalize", flattened[4])
            self.assertNotIn("/agent-repo", " ".join(flattened))

            run_benchmark(
                work, model="sonnet", runner="claude", arm="baseline",
                trials=1, cases=["ctrl"],
                isolation_mode="bubblewrap-selective",
            )
            command = load_json(
                work / "runs/sonnet/ctrl/baseline/1/run.json"
            )["command"]
            self.assertIn(str(SANDBOX_ROOT / "runner-bin/claude"), command)
            self.assertIn("stream-json", command)
            self.assertIn("--safe-mode", command)
            self.assertIn("--disable-slash-commands", command)
            self.assertIn("--tools", command)
            self.assertIn("--disallowedTools", command)
            self.assertIn("Skill,Agent,Task,Task(systemc-*)", command)
            self.assertNotIn(str(SANDBOX_TREATMENT), command)
            claude_home = (
                work
                / "runs/sonnet/ctrl/baseline/1"
                / ".claude-runtime"
            )
            self.assertIn(str(claude_home), command)
            self.assertIn(str(Path.home() / ".claude"), command)
            self.assertNotIn(str(Path.home() / ".claude/agents"), command)
            baseline_settings = (
                work / "runs/sonnet/ctrl/baseline/1/agent-workspace"
                / ".claude-baseline-settings.json"
            )
            self.assertEqual(
                load_json(baseline_settings)["permissions"]["deny"][0],
                "Skill",
            )

            stream = work / "claude.jsonl"
            stream.write_text(
                '{"type":"system","subtype":"init","model":"deepseek"}\n'
                '{"type":"result","result":"complete",'
                '"usage":{"input_tokens":5,"output_tokens":1}}\n',
                encoding="utf-8",
            )
            usage, message = _summarize_claude_jsonl(stream)
            self.assertEqual(usage["input_tokens"], 5)
            self.assertEqual(message, "complete")
            self.assertEqual(_claude_actual_model(stream), "deepseek")

    def test_claude_filter_drops_thinking_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = [
                sys.executable,
                "-c",
                "print('{\"type\":\"system\","
                "\"subtype\":\"thinking_tokens\"}');"
                "print('{\"type\":\"result\",\"result\":\"done\"}')",
            ]
            returncode, discarded = _run_claude_filtered(
                command,
                cwd=root,
                jsonl_path=root / "events.jsonl",
                stderr_path=root / "stderr.log",
            )
            self.assertEqual(returncode, 0)
            self.assertEqual(discarded, 1)
            self.assertNotIn(
                "thinking_tokens",
                (root / "events.jsonl").read_text(encoding="utf-8"),
            )

    def test_direct_claude_plan_uses_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            result = run_benchmark(
                work, model="sonnet", runner="claude", arm="skill",
                trials=1, cases=["ctrl"], isolation_mode="none",
            )
            run_dir = Path(result["run_directories"][0])
            metadata = load_json(run_dir / "run.json")
            prompt = (run_dir / "architect.prompt.txt").read_text(
                encoding="utf-8"
            )
            self.assertEqual(metadata["isolation"], "none")
            self.assertFalse(metadata["command"][0].endswith("bwrap"))
            self.assertIn(str(run_dir / "direct-case.json"), prompt)
            self.assertIn(
                str(repository_root() / "skills/modeling-systemc-tlm/SKILL.md"),
                prompt,
            )

    def test_shared_eda_bundle_excludes_treatment_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            source = work / "corpus/chipbench/ctrl/eda-project"
            tools = source / ".systemc-agent/tools"
            facts = source / ".systemc-agent/facts"
            contracts = source / ".systemc-agent/contracts"
            for path in (tools, facts, contracts):
                path.mkdir(parents=True)
            (tools / "yosys.json").write_text("{}\n", encoding="utf-8")
            database = tools / "surelog-work/slpp_all/surelog.uhdm"
            database.parent.mkdir(parents=True)
            database.write_bytes(b"shared native database")
            dump_json(facts / "rtl.json", {
                "target_top": "TopModule",
                "reference_top": "RefModule",
                "tools": {"yosys": {"status": "passed", "returncode": 0}},
            })
            (source / ".systemc-agent/evidence.jsonl").write_text(
                '{"id":"treatment-fact"}\n', encoding="utf-8"
            )
            (contracts / "architecture.yaml").write_text(
                "treatment: true\n", encoding="utf-8"
            )
            result = run_benchmark(
                work, model="sonnet", runner="claude", arm="baseline",
                trials=1, cases=["ctrl"], isolation_mode="none",
            )
            run_dir = Path(result["run_directories"][0])
            bundle = run_dir / "shared-eda-evidence"
            self.assertTrue((bundle / "tools/yosys.json").is_file())
            self.assertEqual(
                (bundle / "tools/surelog-work/slpp_all/surelog.uhdm").read_bytes(),
                b"shared native database",
            )
            self.assertEqual(
                (
                    bundle / "tools/surelog-work/slpp_all/surelog.uhdm"
                ).stat().st_mode & 0o222,
                0,
            )
            self.assertTrue((bundle / "eda-status.json").is_file())
            self.assertFalse((bundle / "facts").exists())
            self.assertFalse((bundle / "contracts").exists())
            self.assertFalse((bundle / "evidence.jsonl").exists())
            direct_case = load_json(run_dir / "direct-case.json")
            self.assertEqual(
                direct_case["eda_evidence_path"], str(bundle)
            )


if __name__ == "__main__":
    unittest.main()
