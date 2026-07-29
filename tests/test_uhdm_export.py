from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tlm_agent.uhdm_export import export_uhdm_structure


class _Serializer:
    design = None

    def Restore(self, database):
        return [self.design]


class UhdmExportTest(unittest.TestCase):
    def test_exports_definition_and_elaborated_views(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "top.sv"
            source.write_text("module top(input logic clk); endmodule\n")
            database = root / "surelog.uhdm"
            database.write_bytes(b"uhdm")
            constants = {
                "vpiFile": 1,
                "vpiLineNo": 2,
                "vpiName": 3,
                "vpiDefName": 4,
                "vpiSize": 5,
                "vpiDirection": 6,
                "vpiPort": 7,
                "vpiParameter": 8,
                "vpiModule": 9,
                "uhdmallModules": 10,
                "uhdmtopModules": 11,
                "vpiInput": 12,
                "vpiOutput": 13,
                "vpiInout": 14,
                "vpiMixedIO": 15,
                "vpiNoDirection": 16,
            }
            port = {
                1: str(source),
                2: 1,
                3: "clk",
                5: 1,
                6: 12,
            }
            module = {
                1: str(source),
                2: 1,
                3: "work@top",
                4: "work@top",
                7: [port],
                8: [],
                9: [],
            }
            design = {10: [module], 11: [module]}
            _Serializer.design = design
            fake = types.ModuleType("uhdm")
            for name, value in constants.items():
                setattr(fake, name, value)
            fake.Serializer = _Serializer
            fake.vpi_iterate = lambda relation, handle: iter(handle.get(relation, []))
            fake.vpi_scan = lambda iterator: next(iterator, None)
            fake.vpi_get_str = lambda property_id, handle: handle.get(property_id)
            fake.vpi_get = lambda property_id, handle: handle.get(property_id, 0)

            with patch.dict(sys.modules, {"uhdm": fake}):
                result = export_uhdm_structure(database, [source], "top")

            self.assertEqual(result["backend"], "uhdm-python-vpi")
            self.assertEqual(result["modules"][0]["definition"], "work@top")
            self.assertEqual(result["top_modules"][0]["ports"][0]["name"], "clk")
            self.assertEqual(
                result["top_modules"][0]["ports"][0]["direction"], "input"
            )
