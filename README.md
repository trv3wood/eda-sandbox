# 开源 EDA 建模沙盒

本仓库采用“薄 skill + 验证型 harness”的工作方式：Agent 直接理解任务、使用工程
原生 EDA 工具并修改代码；程序负责发现工具、执行可重复验证，并为 Cycle-SystemC
提供机器可判定的强差分门禁。

仓库提供一个环境辅助 skill 和三个领域建模 skill：

- `eda-tool-assistant`：发现、确认并配置本地、研发网、module、SDK 和容器工具环境。
- `modeling-systemc-tlm`：直接实现 loosely timed SystemC/TLM 模型与测试。
- `cycle-systemc-modeling`：读取 RTL、用 EDA 工具验证周期语义并转写 Cycle-SystemC，
  通过专用 RTL 差分门禁验收。
- `modeling-systemverilog`：直接实现或修改 SystemVerilog RTL/DV。

## 快速开始

```bash
uv sync
uv run eda-harness discover PROJECT
```

标准输出和 `.eda-harness/discovery-summary.json` 是面向 Agent 的紧凑可用工具集；
完整诊断保存在 `.eda-harness/discovery.json`。需要直接打印完整报告时使用
`eda-harness discover PROJECT --full`。

在项目下准备自由格式的 `task.md` 和轻量验证配置：

```yaml
# PROJECT/harness.yaml
schema_version: 1
workspace: .
checks:
  - id: syntax
    category: syntax
    command: [python3, -m, compileall, -q, src, tests]
  - id: tests
    category: test
    command: [python3, -m, unittest, discover, -s, tests, -v]
    depends_on: [syntax]
```

完成后验证：

```bash
uv run eda-harness verify PROJECT
uv run eda-harness status PROJECT
```

Cycle-SystemC 任务不使用 `task.md`，改用独立机器契约：

```bash
uv run eda-harness verify-cycle PROJECT --config cycle-harness.yaml
```

其配置、证据和 JSONL trace 接口见
`skills/cycle-systemc-modeling/references/cycle-harness.md`。

## EDA 环境路由

`discover` 检查显式 toolchain 配置、PATH、Python 模块、SystemC/SCC 与厂商 SDK、
environment modules、许可证环境存在性和本地容器镜像，并按 capability 汇总仿真、
lint、综合、形式验证、FPGA、生成和调试工具。它不会拉取镜像、执行 `module load`、
启动 elaboration 或证明许可证可用。缺少任务所需能力时，使用
`eda-tool-assistant` 向用户确认研发网、module、wrapper 和项目原生命令。

专用工具通过 `scripts/eda-run` 进入相应环境：

```bash
scripts/eda-run --work WORK agent eda-harness discover /workspace/PROJECT
scripts/eda-run --work WORK uhdm eda-uhdm run \
  /workspace/design.uhdm /workspace/query.py --output-dir /workspace/query-output -- top
scripts/eda-run --work WORK scc cmake \
  -S /workspace/PROJECT/model -B /workspace/PROJECT/model/build
```

角色包括本地 `agent`，以及本仓库维护的容器化 `uhdm`、`rtl`、`scc`、`rocky`。项目原生命令和商业 EDA wrapper 直接调用，不经过 `eda-run`。
大型镜像下载、SCC 重编和长时间商业 EDA 作业由用户显式启动。

如需固定工具位置，复制 `env/toolchain.env.example` 到工作目录外并设置：

```bash
export EDA_HARNESS_TOOLCHAIN_CONFIG="$HOME/Work/eda-sandbox/toolchain.env"
```

## 开发验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m eda_harness.cli --help
```

容器和 SDK 回归仍可使用 `scripts/regress.sh PROFILE`；详见
[`docs/harness.md`](docs/harness.md)。
