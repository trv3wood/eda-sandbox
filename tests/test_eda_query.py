from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eda_query.cli import main
from eda_query.core import catalog_bundle, query_bundle, raw_query, validate_result


class EdaQueryTest(unittest.TestCase):
    bundle = Path(__file__).parent / "fixtures" / "eda_query"

    def test_catalog_and_independent_backend_queries(self) -> None:
        catalog = catalog_bundle(self.bundle)
        self.assertEqual(
            [item["backend"] for item in catalog["backends"]],
            ["uhdm", "verilator", "yosys"],
        )
        yosys = query_bundle(
            self.bundle,
            backend="yosys",
            kind="hierarchy",
            selectors={"module": "packet_engine_top"},
        )
        self.assertEqual(yosys["items"][0]["child"], "child")
        validate_result(yosys, verify_source=True)

        verilator = query_bundle(
            self.bundle,
            backend="verilator",
            kind="ports",
            selectors={"module": "packet_engine_top"},
        )
        self.assertEqual([item["name"] for item in verilator["items"]], ["clk", "out"])
        validate_result(verilator)
        hierarchy = query_bundle(
            self.bundle,
            backend="verilator",
            kind="hierarchy",
            selectors={"module": "packet_engine_top"},
        )
        self.assertEqual(hierarchy["items"][0]["child"], "child")

        enums = query_bundle(
            self.bundle,
            backend="uhdm",
            kind="enums",
            selectors={"module": "packet_engine_top"},
        )
        self.assertEqual(
            [item["name"] for item in enums["items"][0]["constants"]],
            ["Idle", "Run"],
        )
        fsm = query_bundle(
            self.bundle,
            backend="uhdm",
            kind="fsm-candidates",
            selectors={"module": "packet_engine_top"},
        )
        self.assertEqual(fsm["items"][0]["state_variable"], "state_q")
        self.assertEqual(fsm["items"][0]["states"], ["Idle", "Run"])

    def test_pagination_unsupported_and_raw_pointer(self) -> None:
        first = query_bundle(
            self.bundle, backend="yosys", kind="modules", limit=1
        )
        self.assertTrue(first["truncated"])
        self.assertEqual(first["next_offset"], 1)
        second = query_bundle(
            self.bundle, backend="yosys", kind="modules", limit=1, offset=1
        )
        self.assertNotEqual(first["query_id"], second["query_id"])
        unsupported = query_bundle(
            self.bundle, backend="verilator", kind="cells"
        )
        self.assertEqual(unsupported["status"], "unsupported")
        raw = raw_query(
            self.bundle,
            backend="yosys",
            pointer="/modules/packet_engine_top/ports/out/direction",
        )
        self.assertEqual(raw["items"], ["output"])

    def test_cli_atomic_output_and_no_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with patch.object(
                subprocess, "run", side_effect=AssertionError("must stay offline")
            ):
                returncode = main(
                    [
                        "query", str(self.bundle), "--backend", "yosys",
                        "--kind", "ports", "--module", "child",
                        "--output", str(output),
                    ]
                )
            self.assertEqual(returncode, 0)
            self.assertEqual(json.loads(output.read_text())["status"], "ok")

    def test_invalid_pointer_and_tampered_query_id(self) -> None:
        with self.assertRaises(ValueError):
            raw_query(self.bundle, backend="yosys", pointer="../modules")
        result = query_bundle(self.bundle, backend="yosys", kind="modules")
        result["items"][0]["name"] = "tampered"
        with self.assertRaisesRegex(ValueError, "query_id"):
            validate_result(result)


if __name__ == "__main__":
    unittest.main()
