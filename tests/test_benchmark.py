from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from systemc_tlm_agent.benchmark import (
    architecture_is_approved, prepare_workspace, report_benchmark,
    run_benchmark, score_benchmark,
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
            with self.assertRaisesRegex(ValueError, "not locked"):
                run_benchmark(work, model="gpt-5.6-luna", arm="baseline", trials=1)
            self._prepared(work)
            result = run_benchmark(
                work, model="luna", arm="skill", trials=1,
                cases=["i2c"],
            )
            self.assertEqual(result["status"], "planned")
            run = load_json(work / "runs/luna/i2c/skill/1/run.json")
            self.assertEqual(run["exit_status"], "planned")
            prompt = (work / "runs/luna/i2c/skill/1/architect.prompt.txt").read_text()
            self.assertIn("corpus/opentitan/i2c/case.json", prompt)
            self.assertIn("modeling-systemc-tlm", prompt)

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

    def test_score_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self._prepared(work)
            for arm, points in (("baseline", 60), ("skill", 80)):
                run_benchmark(work, model="gpt-5.6-luna", arm=arm, trials=1,
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


if __name__ == "__main__":
    unittest.main()
