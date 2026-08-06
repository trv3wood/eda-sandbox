"""显式工具链配置；只接受与工具定位有关的白名单变量。"""

from __future__ import annotations

import os
from pathlib import Path

from .tool_registry import TOOL_BY_NAME, TOOL_SPECS


CONFIG_ENV = "EDA_HARNESS_TOOLCHAIN_CONFIG"

TOOL_VARIABLES = {item.name: item.environment_variable for item in TOOL_SPECS}

SDK_VARIABLES = {
    "EDA_SCC_HOME",
    "EDA_SCC_DEPS",
    "EDA_SYSTEMC_HOME",
    "VCS_HOME",
    "VERDI_HOME",
    "XCELIUM_HOME",
    "CDS_INST_DIR",
    "QUESTA_HOME",
    "MODELSIM_HOME",
    "ALDEC_HOME",
    "XILINX_VIVADO",
    "QUARTUS_ROOTDIR",
    "CMAKE_PREFIX_PATH",
    "CMAKE_MODULE_PATH",
    "LD_LIBRARY_PATH",
}

ALLOWED_VARIABLES = frozenset({*TOOL_VARIABLES.values(), *SDK_VARIABLES})


def load_toolchain_config(path_value: str | None = None) -> Path | None:
    """读取简单 KEY=VALUE 配置并更新当前进程环境。"""
    selected = path_value or os.environ.get(CONFIG_ENV)
    if not selected:
        return None
    path = Path(selected).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"toolchain config does not exist: {path}")
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in ALLOWED_VARIABLES:
            raise ValueError(
                f"invalid toolchain config entry at {path}:{number}; "
                "expected a supported KEY=VALUE assignment"
            )
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not value:
            raise ValueError(f"toolchain config value is empty at {path}:{number}")
        os.environ[key] = value
    os.environ[CONFIG_ENV] = str(path)
    return path


def configured_tool(name: str) -> tuple[str, str]:
    """返回工具候选值及其来源。"""
    spec = TOOL_BY_NAME[name]
    variable = spec.environment_variable
    if os.environ.get(variable):
        return os.environ[variable], f"environment:{variable}"
    return spec.executables[0], "PATH"
