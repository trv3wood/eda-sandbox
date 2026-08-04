from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tlm_agent.toolchain import CONFIG_ENV, load_toolchain_config, tool_command


class ToolchainConfigTests(unittest.TestCase):
    def test_loads_explicit_binary_and_sdk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "toolchain.env"
            config.write_text(
                "# local installation\n"
                "EDA_TOOL_SURELOG=/tools/surelog/bin/surelog\n"
                "EDA_SCC_HOME=/tools/scc\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_toolchain_config(str(config))
                self.assertEqual(loaded, config.resolve())
                self.assertEqual(
                    tool_command("EDA_TOOL_SURELOG", "surelog"),
                    ["/tools/surelog/bin/surelog"],
                )
                self.assertEqual(os.environ[CONFIG_ENV], str(config.resolve()))

    def test_rejects_shell_code_and_unknown_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "toolchain.env"
            config.write_text("PATH=/unsafe\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "supported KEY=VALUE"):
                load_toolchain_config(str(config))
