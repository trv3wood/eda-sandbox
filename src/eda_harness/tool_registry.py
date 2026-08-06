"""EDA 工具注册表；只描述安全的发现和轻量版本探测。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    """单个命令行工具的发现元数据。"""

    name: str
    category: str
    capabilities: tuple[str, ...]
    executables: tuple[str, ...]
    environment_variable: str
    version_arguments: tuple[str, ...] = ("--version",)
    probe_safe: bool = True


def _tool(
    name: str,
    category: str,
    capabilities: tuple[str, ...],
    environment_variable: str,
    *executables: str,
    version_arguments: tuple[str, ...] = ("--version",),
    probe_safe: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        category=category,
        capabilities=capabilities,
        executables=executables or (name,),
        environment_variable=environment_variable,
        version_arguments=version_arguments,
        probe_safe=probe_safe,
    )


TOOL_SPECS = (
    # 通用构建与工程编排。
    _tool("cc", "build", ("c-compile",), "EDA_TOOL_CC"),
    _tool("c++", "build", ("cxx-compile", "systemc-compile"), "EDA_TOOL_CXX"),
    _tool("cmake", "build", ("configure", "build"), "EDA_TOOL_CMAKE"),
    _tool("ctest", "build", ("test",), "EDA_TOOL_CTEST"),
    _tool("ninja", "build", ("build",), "EDA_TOOL_NINJA"),
    _tool("make", "build", ("build",), "EDA_TOOL_MAKE"),
    _tool("bazel", "build", ("build", "test"), "EDA_TOOL_BAZEL"),
    _tool("conan", "build", ("dependency-management",), "EDA_TOOL_CONAN"),
    _tool("pkg-config", "build", ("sdk-discovery",), "EDA_TOOL_PKG_CONFIG"),
    _tool("fusesoc", "build", ("core-discovery", "build"), "EDA_TOOL_FUSESOC"),
    _tool("git", "build", ("source-control",), "EDA_TOOL_GIT"),
    _tool("uv", "build", ("python-environment",), "EDA_TOOL_UV"),
    # SystemVerilog 前端、lint 与仿真。
    _tool("verilator", "rtl", ("sv-parse", "lint", "compile", "simulate"), "EDA_TOOL_VERILATOR"),
    _tool(
        "iverilog", "rtl", ("verilog-compile", "simulate"),
        "EDA_TOOL_IVERILOG", version_arguments=("-V",),
    ),
    _tool("slang", "rtl", ("sv-parse", "lint", "elaborate"), "EDA_TOOL_SLANG"),
    _tool("surelog", "rtl", ("sv-parse", "uhdm", "elaborate"), "EDA_TOOL_SURELOG"),
    _tool("uhdm-lint", "rtl", ("uhdm-validate",), "EDA_TOOL_UHDM_LINT"),
    _tool("uhdm-hier", "rtl", ("uhdm-hierarchy",), "EDA_TOOL_UHDM_HIER"),
    _tool("eda-uhdm", "rtl", ("uhdm-query",), "EDA_TOOL_UHDM", version_arguments=("version",)),
    _tool(
        "vcs", "simulation", ("sv-compile", "elaborate", "simulate", "coverage"),
        "EDA_TOOL_VCS", version_arguments=("-ID",),
    ),
    _tool(
        "xrun", "simulation", ("sv-compile", "elaborate", "simulate", "coverage"),
        "EDA_TOOL_XRUN", version_arguments=("-version",),
    ),
    _tool(
        "irun", "simulation", ("sv-compile", "simulate"),
        "EDA_TOOL_IRUN", version_arguments=("-version",),
    ),
    _tool(
        "vsim", "simulation", ("sv-compile", "simulate", "coverage"),
        "EDA_TOOL_VSIM", version_arguments=("-version",),
    ),
    _tool(
        "qrun", "simulation", ("sv-compile", "simulate"),
        "EDA_TOOL_QRUN", version_arguments=("-version",),
    ),
    _tool(
        "riviera", "simulation", ("sv-compile", "simulate"),
        "EDA_TOOL_RIVIERA", "vsimsa", version_arguments=("-version",),
    ),
    _tool("dsim", "simulation", ("sv-compile", "simulate"), "EDA_TOOL_DSIM"),
    # 综合、形式验证和静态检查。
    _tool(
        "yosys", "synthesis", ("synthesis", "formal"),
        "EDA_TOOL_YOSYS", version_arguments=("-V",),
    ),
    _tool("sby", "formal", ("formal-orchestration",), "EDA_TOOL_SBY"),
    _tool("yosys-smtbmc", "formal", ("formal-engine",), "EDA_TOOL_YOSYS_SMTBMC"),
    _tool("boolector", "formal", ("smt-solver",), "EDA_TOOL_BOOLECTOR"),
    _tool("z3", "formal", ("smt-solver",), "EDA_TOOL_Z3", version_arguments=("-version",)),
    _tool(
        "dc-shell", "synthesis", ("asic-synthesis",),
        "EDA_TOOL_DC_SHELL", "dc_shell", probe_safe=False,
    ),
    _tool("genus", "synthesis", ("asic-synthesis",), "EDA_TOOL_GENUS", probe_safe=False),
    _tool("spyglass", "lint", ("lint", "cdc", "rdc"), "EDA_TOOL_SPYGLASS", probe_safe=False),
    _tool("jaspergold", "formal", ("formal",), "EDA_TOOL_JASPERGOLD", "jg", probe_safe=False),
    _tool("vc-formal", "formal", ("formal",), "EDA_TOOL_VC_FORMAL", "vcf", probe_safe=False),
    # FPGA、寄存器生成和波形调试。
    _tool(
        "vivado", "fpga", ("fpga-synthesis", "implementation", "simulation"),
        "EDA_TOOL_VIVADO", version_arguments=("-version",),
    ),
    _tool(
        "quartus", "fpga", ("fpga-synthesis", "implementation"),
        "EDA_TOOL_QUARTUS", "quartus_sh", version_arguments=("--version",),
    ),
    _tool("regtool", "generation", ("register-generation",), "EDA_TOOL_REGTOOL", probe_safe=False),
    _tool("verdi", "debug", ("waveform", "debug"), "EDA_TOOL_VERDI", probe_safe=False),
    _tool("dve", "debug", ("waveform", "debug"), "EDA_TOOL_DVE", probe_safe=False),
    _tool("gtkwave", "debug", ("waveform",), "EDA_TOOL_GTKWAVE"),
    # 环境和容器。
    _tool(
        "modulecmd", "environment", ("environment-modules",),
        "EDA_TOOL_MODULECMD", version_arguments=("--version",),
    ),
    _tool("podman", "container", ("container-runtime",), "EDA_TOOL_PODMAN"),
    _tool("podman-compose", "container", ("container-compose",), "EDA_TOOL_PODMAN_COMPOSE"),
    _tool("docker", "container", ("container-runtime",), "EDA_TOOL_DOCKER"),
)


TOOL_BY_NAME = {item.name: item for item in TOOL_SPECS}
