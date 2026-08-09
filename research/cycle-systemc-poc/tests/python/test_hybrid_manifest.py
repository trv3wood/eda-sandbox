import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

from hybrid_manifest import ManifestError, apply_config, parse_hw_mlir  # noqa: E402
from systemc_codegen import generate_wrapper  # noqa: E402


GOOD_MLIR = """
module {
  hw.module private @leaf(in %a : i8, out y : i8) {
    %c1_i8 = hw.constant 1 : i8
    %0 = comb.add %a, %c1_i8 : i8
    hw.output %0 : i8
  }
  hw.module @top(in %a : i8, out y : i8) {
    %u0.y = hw.instance "u0" @leaf(a: %a: i8) -> (y: i8)
    hw.output %u0.y : i8
  }
}
"""


class ManifestTest(unittest.TestCase):
    def test_extracts_structural_top(self) -> None:
        manifest = parse_hw_mlir(GOOD_MLIR, "top")
        self.assertEqual(manifest["instances"][0]["module"], "leaf")
        self.assertEqual(manifest["outputs"][0]["source"], "%u0.y")

    def test_applies_partition_contract(self) -> None:
        manifest = parse_hw_mlir(GOOD_MLIR, "top")
        configured = apply_config(manifest, {
            "schema_version": 1,
            "partitions": {
                "top.u0": {"backend": "verilated_sc", "prefix": "VLeaf"}
            },
        })
        self.assertEqual(configured["instances"][0]["prefix"], "VLeaf")

    def test_rejects_behavior_in_top(self) -> None:
        bad = GOOD_MLIR.replace(
            '    %u0.y = hw.instance "u0"',
            "    %c1_i8 = hw.constant 1 : i8\n    %u0.y = hw.instance \"u0\"",
        )
        with self.assertRaisesRegex(ManifestError, "不是纯结构"):
            parse_hw_mlir(bad, "top")

    def test_rejects_wide_port(self) -> None:
        with self.assertRaisesRegex(ManifestError, "1～64"):
            parse_hw_mlir(GOOD_MLIR.replace("i8", "i65"), "top")

    def test_rejects_missing_partition(self) -> None:
        manifest = parse_hw_mlir(GOOD_MLIR, "top")
        with self.assertRaisesRegex(ManifestError, "完整匹配"):
            apply_config(manifest, {"schema_version": 1, "partitions": {}})

    def test_generates_systemc_structure(self) -> None:
        manifest = apply_config(parse_hw_mlir(GOOD_MLIR, "top"), {
            "schema_version": 1,
            "partitions": {
                "top.u0": {"backend": "verilated_sc", "prefix": "VLeaf"}
            },
        })
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "top.hpp"
            self.assertEqual(generate_wrapper(manifest, output), "Top")
            generated = output.read_text(encoding="utf-8")
        self.assertIn('#include "VLeaf.h"', generated)
        self.assertIn("u0.a(a);", generated)
        self.assertIn("y.write(sig_u0_y.read());", generated)


if __name__ == "__main__":
    unittest.main()
