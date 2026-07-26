from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eda_query.uhdm_runtime import query_snapshot


class UhdmRuntimeTest(unittest.TestCase):
    def test_live_query_uses_binary_provenance_and_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "design.uhdm"
            database.write_bytes(b"uhdm")
            data = {
                "schema_version": 1,
                "format": "uhdm-json",
                "objects": [
                    {
                        "id": 1, "kind": "module", "name": "dma",
                        "definition": "dma", "module": "dma", "file": "dma.sv",
                        "line": 1,
                    },
                    {
                        "id": 2, "kind": "port", "name": "clk_i",
                        "module": "dma", "direction": "input", "size": 1,
                        "file": "dma.sv", "line": 2,
                    },
                ],
            }
            result = query_snapshot(
                data, database, kind="ports", selectors={"module": "dma"},
                limit=1, offset=0,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["source"]["format"], "uhdm-binary")
            self.assertEqual(result["items"][0]["name"], "clk_i")

    def test_live_query_rejects_unbounded_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "design.uhdm"
            database.write_bytes(b"uhdm")
            with self.assertRaises(ValueError):
                query_snapshot(
                    {"objects": []}, database, kind="ports", selectors={},
                    limit=10_001, offset=0,
                )


if __name__ == "__main__":
    unittest.main()
