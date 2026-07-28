# SystemC/TLM 命令行接口

本仓库提供一个命令行入口点，用于构建并验证一个 SystemC/TLM 模型：
`scripts/systemc-tlm-agent`。其主状态目录是一个建模 `PROJECT`（项目目录）。

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

当前证据提取支持 DOCX、XLSX 和轻量级 SystemVerilog 模块/端口发现。结构化 EDA 结果记录在 `facts/rtl.json` 和 `.systemc-agent/tools/` 下。Surelog 的原生数据库保留为 `tools/surelog-work/slpp_all/surelog.uhdm`，不会再导出为仓库专用的固定 UHDM JSON。

`eda-query` 只离线读取 Yosys/Verilator JSON；`eda-uhdm run DATABASE QUERY.py --output-dir OUTPUT -- ARGS...` 则在 UHDM 镜像中执行 Agent 编写的原生 Python API 查询，保存原始 stdout/stderr 和运行元数据。后者是探索信息，不直接生成证据 ID，必须回到有定位的 RTL/规格证据确认。详细接口见 `docs/agent-eda-query.md`。

CLI 目前不支持将外部基准测试 EDA 包导入 `evidence.jsonl`，也没有专门的 TXT/Markdown 证据注册命令。智能体可以直接读取这些文件，但当前 CLI 无法确定性地将此类观察结果转换为证据 ID。

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
