# EDA 与 SystemC 工具使用

先运行 `eda-harness discover PROJECT`。它检查显式 toolchain 配置、PATH、Python 模块、SDK 环境、容器引擎和工程构建信号，但不会拉镜像、启动 elaboration 或验证许可证可用性。

`scripts/eda-run` 不是通用 EDA 工具选择器，只封装本仓库维护的运行环境：

- `agent`：本地 Python/uv 工具。
- `uhdm`：Surelog/UHDM 和直接 Python 查询。
- `rtl`：RTL lint、仿真和差分工具。
- `scc`：SystemC/minres-SCC 构建与测试。
- `rocky`：Rocky Linux 8 兼容性环境。

示例：

```bash
scripts/eda-run --work WORK uhdm eda-uhdm run \
  /workspace/design.uhdm /workspace/query.py --output-dir /workspace/query-output -- TOP
scripts/eda-run --work WORK scc \
  cmake -S /workspace/PROJECT/model -B /workspace/PROJECT/model/build
```

优先使用工程已有的构建、仿真和验证命令。VCS、Xcelium、Questa 等外部或商业工具直接使用用户提供的项目命令、wrapper 或已激活环境，不要为了统一形式套一层 `eda-run`。

`discovery.json` 记录环境事实；只有需要冻结改动范围和重复执行验收时，才把最终命令记录进 `harness.yaml`。工具缺失是 `blocked`，语法、编译、测试或比较失败是 `failed`。商业工具、长任务和大型镜像操作仍由用户明确启动。

## 语义验证的 EDA 工具映射

工作流第 5 步（语义抽取与证据）的交叉验证手段，按理解任务选工具：
|理解任务|工具|用法|
|---|---|---|
| 源码追踪 / 层级 / 信号定义 | Verdi nTrace | `verdid -f <filelist> -top <tb>` 溯源信号、模块 |
| 行为验证（探针）| VCS/Xcelium/Questa 仿真 | 复用工程 testbench: `$display`、XMR、事务日志 |
| 波形复核（关键语义）| VCS dump+ Verdi nWave | FSDB（Verdi 原生, `-P` 编译）为主，VPD（`+vcs+vcdpluson`，零编译改动）回退 |
| 结构化查询 / 交叉检查 | VCS vpi / (UHDM/Surelog) | 官方 Python binding + `eda-uhdm`; 不替代 Spec/RTL 原文 |
| 结构 / 位宽 / 端口检查 | VCS elaboration / verible | 编译期警告、lint |

波形 dump 建议 **门控在 plusarg 后**（如 `+DUMP_FSDB`），默认仿真不受影响；证据产物与复现命令一并写进 `docs/EVIDENCE.md`