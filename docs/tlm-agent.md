# SystemC/TLM Agent 设计文档

`src/systemc_tlm_agent` 是一个**证据到事务级模型**的确定性工作流内核。
它不尝试把 RTL 自动翻译成逐周期 SystemC；它负责保存证据、校验由 Architect
作出的事务语义决策、锁定人工审批，并从已批准的 TLM handoff 生成可继续实现的
C++17/SystemC 骨架。

## 设计目标与边界

- **证据可追溯**：每个来自 DOCX、XLSX、RTL 或 EDA query 的事实都有来源位置和
  内容摘要。
- **语义由人/Agent 决策**：Architect 将事实归纳为合同；Implementer 不从 RTL
  时钟、信号、流水线或握手重新推测行为。
- **默认 loosely timed**：v2 handoff 固定为 TLM-2.0 `b_transport` 和 delay
  annotation，不表达周期级调度。
- **审批可失效**：输入、facts、evidence、architecture 或 conflict 任一改变，均会
  使批准哈希过期并阻断生成。

当前生成器生成事务接口、功能组件、时延和 smoke test 的骨架；具体算法、队列策略、
寄存器副作用和中断行为仍由 Implementer 按已批准 handoff 实现。解析 RTL 成功也不
代表模型与 RTL 等价。

## 分层和责任

```text
Spec / register map / RTL / EDA bundle
             │ extract
             ▼
  facts + source-located evidence
             │ Architect（推理、冲突决策）
             ▼
  architecture.yaml: 八类合同 + tlm_handoff
             │ validate + named human approval
             ▼
  implementation-handoff.yaml
             │ Implementer
             ▼
  SystemC/TLM functional model + tests
```

`extractors.py` 仅产生事实；`workflow.py` 产生草案、校验和审批；`generator.py`
仅消费批准的 `tlm_handoff`；`verifier.py` 构建并运行测试。CLI 只是把这些模块
编排为命令。

## 项目状态与命令

每个建模项目是独立工作单元：

```text
PROJECT/
├── manifest.yaml
├── model/
│   ├── implementation-handoff.yaml
│   ├── include/, src/, tests/, CMakeLists.txt
│   └── generation.yaml
└── .systemc-agent/
    ├── facts/{documents,registers,rtl,summary}.json
    ├── evidence.jsonl
    ├── query-evidence.jsonl
    ├── contracts/{architecture,conflicts,approval}.yaml
    ├── tools/
    └── verification/report.json
```

正常流程：

```bash
scripts/systemc-tlm-agent init PROJECT --name NAME --top DUT_TOP \
  --docx spec.docx --xlsx registers.xlsx --rtl rtl
scripts/systemc-tlm-agent extract PROJECT
scripts/systemc-tlm-agent architect PROJECT
# Architect 填写 architecture.yaml 和 conflicts.yaml
scripts/systemc-tlm-agent architect PROJECT --validate
scripts/systemc-tlm-agent approve PROJECT --approver NAME
scripts/systemc-tlm-agent generate PROJECT
scripts/systemc-tlm-agent verify PROJECT --backend auto
```

`run` 会执行 extraction 和草案创建，但在 architecture gate 或 approval gate 返回
退出码 `2`，不会绕过人工决策。`status` 只报告状态与门禁错误，不改变项目。

## 事实与 EDA 工具

`extract` 会读取 DOCX 段落/表格、XLSX 单元格和 RTL module/instance 的轻量 fallback，
并为每项写入 evidence ID。默认本机还会尝试 Surelog/UHDM、Verilator、Yosys；失败和
不可用会分别记录，不会互相掩盖。

主机没有工具时，先提取但跳过本地工具，再使用角色镜像产生独立结果：

```bash
scripts/systemc-tlm-agent extract PROJECT --skip-tools
scripts/eda-run --work WORK uhdm eda-uhdm-produce /workspace/PROJECT
scripts/eda-run --work WORK rtl  eda-rtl-produce  /workspace/PROJECT
scripts/eda-run --work WORK agent \
  systemc-tlm-agent tools finalize /workspace/PROJECT
```

`eda-query` 只查询已有的 Yosys/Verilator JSON。成功的 QueryResult 可以经
`systemc-tlm-agent evidence record` 写入 `query-evidence.jsonl`。UHDM Python
脚本输出仅用于探索和定位，必须回到 RTL/Spec 的源定位后才能成为合同证据。

## Architecture v2 与 Implementer handoff

`architect` 创建 `schema_version: 2` 草案。审批时，除了八类合同和无未决冲突外，
还必须存在完整 `tlm_handoff`：

- `policy`：固定 `loosely-timed-tlm-2.0`、`b_transport`，并禁止 RTL/周期级细节。
- `transaction_types`：命名事务、字段类型和可选位宽，以及成功/错误响应语义。
- `functional_modules`：按职责而非 RTL hierarchy 划分。每个模块定义 endpoint、
  operation effect/completion、状态/并发、服务时延、错误处理和 observable。
- `channels`：明确连接 source/destination endpoint、事务、顺序、所有权、背压和
  completion 规则。
- `acceptance_scenarios`：带 evidence ID 的 Given/When/Then 事务级验收场景。

`rtl_traceability` 可保留功能组件与 RTL 证据的关联，但它不决定 TLM 模块边界。
校验器会检查名称唯一性、evidence ID、事务和 endpoint 引用、端点方向、时延值及全部
必填语义。旧版 v1 architecture 不可获批准。

批准后的 `generate` 把 `tlm_handoff` 原样写到
`model/implementation-handoff.yaml`。这是 Implementer 的唯一行为输入；如果它不足
以实现，Implementer 必须请求 Architect 补充并重新批准，而不是从 facts/RTL 作决定。

## 生成与验证

生成器为每个 `functional_modules` 条目创建一个 `sc_module`：inbound endpoint 映射为
target socket，outbound endpoint 映射为 initiator socket，服务时延成为构造参数，并把
operation 规则保留为实现提示。生成器不自动连接 channel，也不生成 IP 特定算法。

验证分为四层，报告中必须分开解释：

1. CMake configure 与 C++ compile。
2. CTest smoke/unit tests。
3. 合同导向 transaction tests。
4. 使用相同 stimulus 和明确 normalization/comparison adapter 的 RTL differential test。

`verify --backend auto` 在主机存在 `/opt/scc` 时走 local；否则调用 Compose 的 `eda-scc`
服务。当前 differential test 没有通用 adapter，因此即使 Verilator 已成功，也会明确报告
`blocked`，而不是宣称 RTL equivalence。

## 维护约束

- 改动 architecture schema 时，同时更新草案、validator、generator、角色说明和测试。
- 不要将 UHDM 探索输出直接写入 evidence；不要把一个 EDA backend 的成功外推到另一个。
- 大镜像拉取、容器构建和 minres-SCC 编译可能耗时，应由用户显式执行。
