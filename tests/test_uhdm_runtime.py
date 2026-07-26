from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from eda_query.uhdm_runtime import query_snapshot, snapshot


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

    def test_snapshot_falls_back_to_cpp_exporter(self) -> None:
        class Serializer:
            pass

        def run(command: list[str], **_: object) -> types.SimpleNamespace:
            Path(command[2]).write_text(
                '{"format":"uhdm-json","objects":['
                '{"id":1,"kind":"module","name":"dma","file":"/src/dma.sv"}]}',
                encoding="utf-8",
            )
            return types.SimpleNamespace(returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "design.uhdm"
            database.write_bytes(b"uhdm")
            fake_binding = types.SimpleNamespace(Serializer=Serializer)
            with (
                patch.dict("sys.modules", {"uhdm": fake_binding}),
                patch(
                    "eda_query.uhdm_runtime.shutil.which",
                    return_value="/usr/bin/uhdm-export",
                ),
                patch("eda_query.uhdm_runtime.subprocess.run", side_effect=run) as call,
            ):
                data = snapshot(database)
            self.assertEqual(data["objects"][0]["name"], "dma")
            self.assertEqual(call.call_args.args[0][0], "/usr/bin/uhdm-export")


if __name__ == "__main__":
    unittest.main()
