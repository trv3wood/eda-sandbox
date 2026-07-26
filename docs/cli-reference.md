# SystemC/TLM 命令行接口

本仓库有两个命令行入口点，它们的设计职责范围有意不同：

| 命令 | 范围 | 主状态目录 |
|---|---|---|
| `scripts/systemc-tlm-agent` | 构建并验证一个 SystemC/TLM 模型 | 一个建模 `PROJECT`（项目目录） |
| `scripts/benchmark-systemc-tlm` | 编排可重复的 A/B 智能体评估 | 一个基准测试 `--work` 工作树 |

基准测试 CLI 可能会调用建模 CLI 或将其暴露给实验组智能体，但建模 CLI 本身不承担基准测试、模型运行器、评分或盲化（blinding）的任何职责。

## `systemc-tlm-agent`

实现位置：

- 入口点：`src/systemc_tlm_agent/cli.py`
- 提取：`src/systemc_tlm_agent/extractors.py`
- 合约与审批：`src/systemc_tlm_agent/workflow.py`
- 生成：`src/systemc_tlm_agent/generator.py`
- 验证：`src/systemc_tlm_agent/verifier.py`

### 项目布局

```text
PROJECT/
├── manifest.yaml
└── .systemc-agent/
    ├── evidence.jsonl
    ├── facts/{documents,registers,rtl,summary}.json
    ├── contracts/{architecture,conflicts,approval}.yaml
    ├── model/
    └── verification/report.yaml
```

`manifest.yaml` 用于区分待生成的模型与已有的验证源：

```yaml
name: ctrl
target_top: TopModule
reference_top: RefModule
documents: []
registers: []
rtl:
  - Prob001_controller_ref.sv
testbench:
  - Prob001_controller_test.sv
backend: local
```

`target_top` 是待生成的 DUT。`reference_top` 是已有的黄金 RTL 模块，供结构化 EDA 使用。Surelog 会处理设计 RTL 和测试平台源文件；Verilator 和 Yosys 仅接收设计 RTL。

### 命令

#### `init`

创建 `manifest.yaml`。不执行提取、编译或生成操作。

```bash
scripts/systemc-tlm-agent init PROJECT \
  --name ctrl --top TopModule --reference-top RefModule \
  --rtl ref.sv --tb test.sv --backend local
```

`--docx`、`--xlsx`、`--rtl` 和 `--tb` 可重复指定。RTL 参数也可以命名为目录或 glob 模式。旧版 manifest 中使用 `top` 而非 `target_top` 的写法仍然可读。

#### `extract`

解析 manifest 输入，计算源文件摘要，写入证据/事实，并可选择运行 Surelog、Verilator 和 Yosys。

```bash
scripts/systemc-tlm-agent extract PROJECT
scripts/systemc-tlm-agent extract PROJECT --skip-tools
```

当前证据提取支持 DOCX、XLSX 和轻量级 SystemVerilog 模块/端口发现。结构化 EDA 结果记录在 `facts/rtl.json` 和 `.systemc-agent/tools/` 下。CLI 目前不支持将外部基准测试 EDA 包导入 `evidence.jsonl`，也没有专门的 TXT/Markdown 证据注册命令。智能体可以直接读取这些文件，但当前 CLI 无法确定性地将此类观察结果转换为证据 ID。

#### `architect`

创建八类合约框架，或验证已编辑的合约：

```bash
scripts/systemc-tlm-agent architect PROJECT
scripts/systemc-tlm-agent architect PROJECT --validate
```

八个类别分别是 `functional_intent`（功能意图）、`transaction_entry`（事务入口）、`input_domain`（输入域）、`algorithm_transform`（算法变换）、`data_flow`（数据流）、`state_concurrency`（状态与并发）、`boundaries_exceptions`（边界与异常）和 `observable_results`（可观察结果）。

验证检查类别状态、必填项、证据 ID 存在性、模型分区存在性以及未解决的冲突记录。这是一个结构性的门控检查；它并不证明引用的证据在语义上支持某个声明。

#### `approve`

要求指定的人类决策者并哈希所有受审批控制的产物：

```bash
scripts/systemc-tlm-agent approve PROJECT --approver NAME
```

此后任何 manifest、事实、架构或冲突的更改都会使审批失效。

#### `generate`

从当前已审批的架构生成 C++17 SystemC/TLM 模型和测试源文件：

```bash
scripts/systemc-tlm-agent generate PROJECT
```

如果审批缺失、无效或已过期，生成操作将拒绝执行。

#### `verify`

配置、构建并测试生成的项目：

```bash
scripts/systemc-tlm-agent verify PROJECT --backend auto
```

后端选项为 `auto`、`local` 和 `podman`。验证级别必须分开报告：编译、CTest、合约导向的事务测试和 RTL 差分对比不可互换。

#### `run`

推进提取和架构阶段，然后在下一个强制性门控处停止：

```bash
scripts/systemc-tlm-agent run PROJECT --backend auto
```

退出码 `2` 表示工作流健康但暂停等待架构完成或审批。退出码 `1` 表示错误。

#### `status`

报告哪些产物存在、架构验证错误和审批有效性，不推进工作流：

```bash
scripts/systemc-tlm-agent status PROJECT
```

## `benchmark-systemc-tlm`

实现位置：

- 入口点：`src/systemc_tlm_agent/benchmark_cli.py`
- 编排与评分：`src/systemc_tlm_agent/benchmark.py`

基准测试状态属于 `~/Work/eda-sandbox`；仓库代码位于 `~/Project/eda-sandbox`。

### 工作树布局

```text
WORK/
├── benchmark.json
├── sources/{lock.json,chipbench,opentitan}
├── corpus/SUITE/CASE/
│   ├── case.json
│   └── eda-project/
├── runs/MODEL/CASE/ARM/TRIAL/
└── reports/
```

### 命令

#### `prepare`

创建基准测试元数据、用例框架和用户操作的拉取命令。不克隆仓库或构建镜像。

```bash
scripts/benchmark-systemc-tlm prepare --work WORK
```

#### `lock`

记录每个已获取的源仓库的提交和 Git 树摘要：

```bash
scripts/benchmark-systemc-tlm lock --work WORK
```

#### `extract`

使用选定的已有容器镜像创建共享的解析器输出：

```bash
scripts/benchmark-systemc-tlm extract --work WORK \
  --case ctrl --top TopModule --reference-top RefModule \
  --image localhost/eda-agent:local --execute
```

不带 `--execute` 时，仅打印/持久化计划。每次运行的暂存区提供一个中立的包，包含解析器原生日志、JSON/UHDM 产物和清洗过的工具状态。建模 CLI 的 facts、evidence、contracts 和命令记录不在不同实验组之间共享。

#### `run`

规划或执行一次或多次模型试验：

```bash
scripts/benchmark-systemc-tlm run --work WORK \
  --runner claude --model opus --arm baseline \
  --case ctrl --trials 1 --stage architect --isolation none --execute
```

重要选项：

- `--runner`：`codex` 或 `claude`。
- `--arm`：`baseline`（基线）或 `skill`（技能）。
- `--stage`：`architect`（架构）或 `implement`（实现）。
- `--isolation`：宿主机直接执行 (`none`) 或 `bubblewrap-selective`。
- `--execute`：省略则以创建可检查的计划，而不实际调用模型。

每次运行都会记录其提示词、运行器 JSONL、最终响应、stderr、模型标识、时间戳、用量、命令、隔离模式和能力策略。

Claude 基线运行使用安全模式，禁用斜杠命令，并移除 `Skill`、`Agent` 和 `Task` 工具。技能运行保留宿主实验组的能力。直接宿主机模式是能力隔离，而非文件系统保密：shell 命令仍然可以读取宿主机可见的路径。

实现阶段的运行需要有效的 `architecture-review.json`，其中包含两个匹配的盲审批准或一个肯定的第三方裁决。

CLI 目前不强制执行顺序执行、挂钟超时、最大轮次或通用成本上限。当评估效率时，请按顺序启动各实验组。

#### `score`

聚合评审者编写的 `score.json` 文件：

```bash
scripts/benchmark-systemc-tlm score --work WORK
```

该命令不执行语义审查，也不创建缺失的分数。

#### `report`

渲染聚合的 Markdown 报告：

```bash
scripts/benchmark-systemc-tlm report --work WORK
```

### 职责边界

`benchmark-systemc-tlm` 负责源锁定、用例选择、实验组能力、运行器调用、中立 EDA 暂存、运行元数据、审查门控、评分和报告。

`systemc-tlm-agent` 负责一个建模项目的证据/事实、合约、审批哈希、生成的模型和验证。

两个 CLI 都不应静默地吸收对方的策略。特别地：

- 建模 CLI 不得检查基准测试或 oracle 目录。
- 基准测试 CLI 不得决定设计行为或编辑合约。
- 共享的 EDA 基础设施不得包含实验组生成的事实或证据。
- 对于模糊的 Spec/RTL 行为，人类审查仍然是权威来源。
