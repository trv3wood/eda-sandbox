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

## 后端选择规则

不要按产品名称硬编码流程。先按本任务真正需要的能力选择，并将结论写进
`task.md`：

```text
工具后端：<工程原生命令/厂商与产品>
覆盖能力：<parse/elaboration/lint/simulation/waveform/query>
选择依据：<现有许可证、项目既有脚本、目标平台>
复现命令：<最终 argv 或 wrapper>
不可替代项：<例如完整 elaboration、FSDB、特定 lint rule>
允许降级：<明确列出；未列出即不允许>
```

选择优先级如下：

1. 项目已经验证过的原生命令和 filelist/wrapper；不要重建另一条工具流。
2. 有有效许可证的商业编译/elaboration 与仿真器，作为 SystemVerilog 语义和
   行为证据的主后端。
3. 同一厂商或项目既有的 lint/CDC/结构检查，作为对应 signoff 或质量检查后端。
4. UHDM/Surelog 只用于可移植结构化查询、开源流程或商业工具之外的补充导航。
   它不是商业数据库的导入/导出格式替代品。
5. verible、verilator 等开源工具只可覆盖其实际执行的检查；不能把它们的通过
   表述为商业 elaboration、仿真或专有 lint 的通过。

Rocky 8 无法使用容器时，跳过本仓库的 UHDM 容器即可；若商业命令能覆盖任务所需
的编译、elaboration、仿真或 lint，不应因此将任务标记为 blocked。反之，任务明确
要求读取 `.uhdm`、调用 UHDM Python API 或复用现有 UHDM 查询脚本时，商业工具不构成
直接替代，必须保留该需求并向用户确认可用的二进制分发或改写方案。

`discover` 只能盘点候选工具和环境变量，不能证明许可证、项目 wrapper 或数据库接口
可用。首次真正的商业工具命令须在用户允许的范围内执行；失败后记录错误与后端，不得
静默改用覆盖较弱的工具。

## 语义验证的 EDA 工具映射

工作流第 5 步（语义抽取与证据）的交叉验证手段，按理解任务选工具：

| 理解任务 | 主后端 | 可选补充 | 证据 |
|---|---|---|---|
| 源码追踪、层级、信号定义 | 项目既有的 Verdi/SimVision/Questa 可视化或 simulator report | UHDM 查询 | 顶层、实例路径、端口/参数报告 |
| 行为验证（探针） | VCS、Xcelium 或 Questa 仿真 | 无 | 复用工程 testbench 的事务日志、XMR 或断言结果 |
| 波形复核 | 项目既有波形格式与查看器 | FSDB/Verdi、SHM/SimVision、WLF/Questa | 受控 dump、信号、时间点与复现命令 |
| 结构化查询 | UHDM/Surelog（若已可用）或厂商 VPI/Tcl 查询 | 文本搜索仅用于定位 | 查询脚本、工具版本与结果；厂商接口不假定可移植 |
| 结构、位宽、端口、规则检查 | 项目既有 commercial lint 或 simulator elaboration | verible/verilator | 完整命令、rule set、错误/警告摘要 |

波形 dump 建议 **门控在 plusarg 后**（如 `+DUMP_FSDB`），默认仿真不受影响；证据产物与复现命令一并写进 `docs/EVIDENCE.md`
