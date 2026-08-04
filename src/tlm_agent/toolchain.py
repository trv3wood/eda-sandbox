"""显式工具链配置，避免把宿主机安装布局编码进工作流。"""

from __future__ import annotations

import os
from pathlib import Path


CONFIG_ENV = "SYSTEMC_TLM_TOOLCHAIN_CONFIG"

# 配置文件是给 Bash 和 Python 共用的简单 KEY=VALUE 文件，故只允许会影响
# 二进制定位和 SDK 定位的变量，避免把它变成任意环境变量注入入口。
ALLOWED_VARIABLES = frozenset(
    {
        "EDA_TOOL_SURELOG",
        "EDA_TOOL_UHDM_LINT",
        "EDA_TOOL_UHDM_HIER",
        "EDA_TOOL_UHDM",
        "EDA_TOOL_VCS",
        "EDA_TOOL_CC",
        "EDA_TOOL_CMAKE",
        "EDA_TOOL_CXX",
        "EDA_TOOL_CTEST",
        "EDA_TOOL_NINJA",
        "EDA_TOOL_PODMAN",
        "EDA_TOOL_PODMAN_COMPOSE",
        "EDA_TOOL_DOCKER",
        "EDA_TOOL_UV",
        "EDA_SCC_HOME",
        "EDA_SCC_DEPS",
        "EDA_SYSTEMC_HOME",
        "VCS_HOME",
        "CMAKE_PREFIX_PATH",
        "CMAKE_MODULE_PATH",
        "LD_LIBRARY_PATH",
    }
)


def load_toolchain_config(path_value: str | None = None) -> Path | None:
    """读取显式工具链配置，并将白名单变量放入当前进程环境。"""
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
        if not separator or not key or key not in ALLOWED_VARIABLES:
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


def tool_command(variable: str, fallback: str) -> list[str]:
    """返回配置的可执行文件路径，未配置时保留标准 PATH 查找。"""
    return [os.environ.get(variable, fallback)]
