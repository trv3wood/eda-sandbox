# 开源 EDA 建模沙盒

本仓库采用“薄 skill + 验证型 harness”的工作方式：Agent 直接理解任务、使用工程
原生 EDA 工具并修改代码；程序只负责发现工具、记录任务基线、检查改动范围和执行
可重复验证。

仓库提供两个领域 skill：

- `modeling-systemc-tlm`：直接实现 loosely timed SystemC/TLM 模型与测试。
- `modeling-systemverilog`：直接实现或修改 SystemVerilog RTL/DV。

二者共享 `eda-harness`，不再使用 canonical graph、八类合同、handoff、审批状态机、
固定 scaffold generator 或结构化 edits.json。

## 快速开始

```bash
uv sync
uv run eda-harness discover PROJECT
```

在项目下准备自由格式的 `task.md` 和轻量验证配置：

```yaml
# PROJECT/harness.yaml
schema_version: 1
workspace: .
allowed_changes: [src/**, tests/**]
checks:
  - id: syntax
    category: syntax
    command: [python3, -m, compileall, -q, src, tests]
  - id: tests
    category: test
    command: [python3, -m, unittest, discover, -s, tests, -v]
    depends_on: [syntax]
```

首个代码改动前创建 snapshot，完成后验证：

```bash
uv run eda-harness snapshot PROJECT
# Agent 直接修改 PROJECT
uv run eda-harness verify PROJECT
uv run eda-harness status PROJECT
```

Snapshot 会把用户已有的 dirty state 作为基线，只审计此后发生的变化。新增、修改、
删除或重命名若不匹配 snapshot 时锁定的 `allowed_changes`，integrity gate 会失败。

## EDA 环境路由

`discover` 检查显式 toolchain 配置、PATH、Python 模块、SystemC/SCC SDK、VCS 环境
和容器引擎，并结合工程文件给出推荐 argv。它不会拉取镜像、启动 elaboration 或证明
许可证可用。

专用工具通过 `scripts/eda-run` 进入相应环境：

```bash
scripts/eda-run --work WORK agent eda-harness discover /workspace/PROJECT
scripts/eda-run --work WORK vcs vcs -f /workspace/PROJECT/rtl/top.f -top top
scripts/eda-run --work WORK uhdm eda-uhdm run \
  /workspace/design.uhdm /workspace/query.py --output-dir /workspace/query-output -- top
scripts/eda-run --work WORK scc cmake \
  -S /workspace/PROJECT/model -B /workspace/PROJECT/model/build
```

角色包括本地 `agent`、研发网 `vcs`，以及容器化 `uhdm`、`rtl`、`scc`、`rocky`。
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
