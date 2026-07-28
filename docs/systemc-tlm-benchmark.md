# SystemC TLM 技能基准测试

本基准测试对 `gpt-5.6-luna` 模型进行盲化、匹配的 A/B 评估。
基线组和技能组接收相同的用例输入、种子、预算、工具、阶段边界和隐藏测试。仅技能组可使用仓库建模技能。此 SystemC 扩展与 ChipBench 论文中的 pass@k 不直接可比。

智能体根据 [EDA 证据协议](eda-evidence-protocol.md) 查询和注册解析器原生观察结果。

## 安全准备

```bash
scripts/benchmark-systemc-tlm prepare --work ~/Work/eda-sandbox
```

准备阶段不下载或编译任何内容。它会写入 `sources/FETCH_COMMANDS.txt`；用户运行这些可能耗时较长的命令，然后固定两个仓库：

```bash
scripts/benchmark-systemc-tlm lock --work ~/Work/eda-sandbox
```

锁文件记录仓库 URL、许可证、提交和完整 Git 树列表的 SHA-256 摘要。在执行智能体之前，用不可变的输入路径填充每个生成的 `corpus/*/*/case.json`。

在任一实验组之前，于已有的智能体镜像中生成共享的 EDA 证据：

```bash
scripts/benchmark-systemc-tlm extract --work ~/Work/eda-sandbox \
  --case ctrl --top TopModule --reference-top RefModule \
  --agent-image localhost/eda-agent:local \
  --uhdm-image localhost/eda-uhdm:local \
  --rtl-image localhost/eda-rtl:local --execute
```

五步流程分别初始化/提取文本、生成 UHDM、生成 RTL 工具视图，再合并 producer
记录。容器之间仅共享 benchmark work tree，不在容器内启动 Podman。`--image`
仍作为兼容选项，可把同一旧镜像用于所有角色。

UHDM producer 保留原生 `surelog.uhdm`，不生成固定语义 JSON。运行阶段把整个
中立工具目录复制到两个实验组，并移除文件写权限；因此两组获得逐字节相同的
UHDM 数据库、Yosys/Verilator JSON、日志和 producer 记录。直接宿主机模式下，
同一宿主用户仍可主动恢复写权限，这一限制会记录在试验解释中。

## 运行与架构门控

不带 `--execute` 时，`run` 仅创建可检查的计划：

```bash
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --model gpt-5.6-luna --arm baseline --trials 3
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --model gpt-5.6-luna --arm skill --trials 3
```

加上 `--execute` 以调用 `codex exec`。架构阶段持久化其提示词、命令、时间戳、提交锁定、退出状态和 JSONL。在实现阶段之前，将 `architecture-review.json` 放入每个运行目录：

Claude Code 使用相同的语料库、证据、实验组和门控：

```bash
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --runner claude --model sonnet --arm baseline --case ctrl --trials 1
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --runner claude --model sonnet --arm skill --case ctrl --trials 1
```

检查计划后再添加 `--execute`。Claude 保留在宿主机上以便其 OAuth 会话保持可用；仅确定性的 EDA 提取在容器中运行。运行器隔离默认为 `none`，以便 Claude Code 可以保留自定义模型提供者配置和宿主机 EDA 工具。此类运行是提示词盲化的，而非文件系统盲化的，`run.json` 记录了这一限制。仅在已知运行器配置可在受限文件系统内正常工作时，才使用 `--isolation bubblewrap-selective`。

Claude 基线运行额外使用安全模式，禁用斜杠命令，从工具集中移除 `Skill`、`Agent` 和 `Task`，并加载每次运行的拒绝设置文件。这可以防止实验组技能/角色调用，即使这些自定义配置已安装在宿主机 Claude 配置文件中。在 `--isolation none` 模式下，Bash 仍然可以读取宿主机可见的文件，因此这是能力隔离而非文件系统机密性边界。

```json
{
  "reviews": [
    {"reviewer": "blind-A", "decision": "approve"},
    {"reviewer": "blind-B", "decision": "approve"}
  ]
}
```

如果前两位评审者意见不一致，则追加第三位裁决者的决定。实现阶段仅在两位初始评审者都批准，或者第三位裁决者以 `approve` 解决分歧时才会继续：

```bash
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --model gpt-5.6-luna --arm skill --trials 3 --stage implement --execute
```

oracle 目录绝不能出现在智能体提示词或工作输入中。评审者在每个运行目录中创建 `score.json`，包含 `evidence`（证据）、`architecture`（架构）、`implementation`（实现）和 `functional`（功能）的 `points`（得分）和 `possible`（满分）；效率单独报告。评分还包含 `gate_violations`（门控违规）和 `fabricated_evidence`（伪造证据）。

```bash
scripts/benchmark-systemc-tlm score --work ~/Work/eda-sandbox
scripts/benchmark-systemc-tlm report --work ~/Work/eda-sandbox
```

完整的 ChipBench/OpenTitan 下载、容器构建、SCC 编译和完整回归测试仍然是用户操作的长时运行命令。

## 架构冒烟测试结果 (2026-07-26)

一个 `ctrl` 用例通过 Claude Code 使用 `deepseek-v4-flash[1M]` 对每个实验组运行了一次。这是一次框架和架构阶段的冒烟测试，而非已完成的 Pilot 测试或有统计意义的技能评分。

已验证的框架属性：

- 两个实验组使用相同的模型和逐字节相同的中立 Surelog 原生数据库、Verilator、Yosys 和状态产物。
- 基线组启动时没有自定义技能，仅有内置的 `claude`、`Explore`、`general-purpose` 和 `Plan` 智能体。其工具集中不包含 `Skill`、`Agent` 或 `Task`，其 JSONL 未显示任何实验组调用。
- 技能组收到了仓库技能和角色适配器。它生成了规范的八类架构 YAML，注册了 36 条证据记录，没有未知的合约证据 ID，通过了 `architect --validate`，并在人类批准门控处停止。
- 基线组生成了一个有用的独立架构，但使用了不同的八类模式，并在报告 JALR 歧义时选择了 RTL 解释而未经人类裁决。其最终的 `ARCHITECT_COMPLETE` 状态与 `conflicts.yaml` 中未解决的条目不一致。

观察到的资源使用：

| 实验组 | 挂钟时间 | 输入 token | 输出 token | 报告成本 |
|---|---:|---:|---:|---:|
| 基线 | 约 105 s | 65,810 | 13,393 | USD 0.87 |
| 技能 | 约 197 s | 81,541 | 23,588 | USD 2.15 |

这些效率数据不是被接受的基准测试测量结果。两次运行从不同终端启动，重叠了约 82 秒，因此提供者争用、缓存行为和本地 I/O 未受控制。没有强制执行相同的最大成本、挂钟超时或轮次上限。

进一步的局限：

- 这仅是一个用例和一次试验，没有盲审评分或隐藏的功能 oracle。
- 直接宿主机模式提供的是能力隔离，而非文件系统机密性；基线 Bash 理论上有能力读取其他宿主机可见的文件，尽管运行中未显示此类访问。
- 技能结果仍包含审查发现：声称完全的 RV32I 兼容性比所提供的证据更广泛，JALR 省略的 ALUOp 分组应表示为歧义而非无条件一致性，X/Z 等价性表述比综合证据所能支持的更强。
- 共享的中立 EDA 包评估的是证据解释和架构构建。它不衡量技能端到端选择、配置和执行 EDA 工具的能力。

因此，本次运行支持一个初步的定性信号，表明技能改善了合约模式合规性、证据可追溯性和审批门控行为。它并未建立 Pilot 测试所需的评分改进。
在正式试验之前，两个实验组必须接收相同的显式交付模式，按随机顺序依次运行，并共享相同的强制成本/时间上限。证据提取和架构评估应作为独立阶段分别报告。
