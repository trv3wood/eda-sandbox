from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eda_query.uhdm_runtime import build_parser, run_query


class UhdmRuntimeTest(unittest.TestCase):
    binding = {
        "module": "/opt/uhdm/uhdm.py",
        "serializer_format_version": "1",
    }

    def _files(self, temporary: str, source: str) -> tuple[Path, Path, Path]:
        root = Path(temporary)
        database = root / "design.uhdm"
        database.write_bytes(b"binary database")
        script = root / "query.py"
        script.write_text(source, encoding="utf-8")
        return database, script, root / "output"

    def test_run_preserves_raw_streams_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database, script, output = self._files(
                temporary,
                "import os, sys\n"
                "print(os.environ['UHDM_DATABASE'])\n"
                "print('|'.join(sys.argv[1:]))\n"
                "print('diagnostic', file=sys.stderr)\n",
            )
            with patch(
                "eda_query.uhdm_runtime.binding_info",
                return_value=self.binding,
            ):
                result = run_query(
                    database, script, output, script_args=["alpha", "beta"]
                )

            self.assertEqual(result["status"], "passed")
            stdout = (output / "stdout.log").read_text(encoding="utf-8")
            self.assertEqual(stdout, f"{database.resolve()}\nalpha|beta\n")
            self.assertEqual(
                (output / "stderr.log").read_text(encoding="utf-8"),
                "diagnostic\n",
            )
            saved = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["database"]["sha256"], result["database"]["sha256"])
            self.assertEqual(saved["script"]["sha256"], result["script"]["sha256"])
            self.assertEqual(saved["binding"]["serializer_format_version"], "1")

    def test_nonzero_exit_is_reported_without_rewriting_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database, script, output = self._files(
                temporary,
                "import sys\nprint('partial')\nsys.exit(7)\n",
            )
            with patch(
                "eda_query.uhdm_runtime.binding_info",
                return_value=self.binding,
            ):
                result = run_query(database, script, output)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["returncode"], 7)
            self.assertEqual((output / "stdout.log").read_bytes(), b"partial\n")

    def test_timeout_kills_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database, script, output = self._files(
                temporary,
                "import time\nprint('started', flush=True)\ntime.sleep(5)\n",
            )
            with patch(
                "eda_query.uhdm_runtime.binding_info",
                return_value=self.binding,
            ):
                result = run_query(database, script, output, timeout=1)
            self.assertEqual(result["status"], "timeout")
            self.assertEqual((output / "stdout.log").read_bytes(), b"started\n")

    def test_combined_output_limit_kills_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database, script, output = self._files(
                temporary,
                "import sys, time\n"
                "sys.stdout.write('x' * 128)\nsys.stdout.flush()\ntime.sleep(5)\n",
            )
            with patch(
                "eda_query.uhdm_runtime.binding_info",
                return_value=self.binding,
            ):
                result = run_query(
                    database, script, output, max_output_bytes=32
                )
            self.assertEqual(result["status"], "output_limit")
            self.assertEqual(len((output / "stdout.log").read_bytes()), 32)

    def test_validation_and_cli_script_arguments(self) -> None:
        arguments = build_parser().parse_args(
            [
                "run", "design.uhdm", "query.py",
                "--output-dir", "output", "--", "top",
            ]
        )
        self.assertEqual(arguments.output_dir, "output")
        self.assertEqual(arguments.script_args, ["top"])
        with tempfile.TemporaryDirectory() as temporary:
            database, script, output = self._files(temporary, "pass\n")
            with self.assertRaises(ValueError):
                run_query(database, script, output, timeout=0)
            not_python = script.with_suffix(".txt")
            not_python.write_text("pass\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"\.py"):
                run_query(database, not_python, output)


if __name__ == "__main__":
    unittest.main()
