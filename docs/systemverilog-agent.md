# SystemVerilog 后端

SystemVerilog 后端与 TLM 后端共享 `manifest.yaml`、输入提取和 Canonical Graph，但使用独立的 RTL handoff、冲突、审批、生成目录和验证报告。现有 `systemc-tlm-agent` 命令及 TLM 工件保持兼容。

## 技术边界

后端支持三种模式：

1. `interface`：生成精确参数、端口、import 和带证据的 TODO 区域。
2. `hierarchy`：额外生成内部声明、命名参数绑定、命名端口连接和子模块实例。
3. `patch`：复制原工程到隔离 worktree，仅允许修改获批的 process、continuous assignment 和 module instance CST 节点。

不支持从 UHDM 完整重建源码，也不支持宏体、package、class、interface、function/task 或 generate 的自动改写。UHDM/VPI 可用于确认 elaborated module/instance 和结构差分，但不是源码生成器。

## 安装与入口

```bash
uv sync --extra rtl
scripts/systemverilog-agent --help
```

`rtl` extra 安装 pyslang。Lint、compile 和 simulation 命令由获批 handoff 以 argv 数组配置，并在隔离 worktree 中无 shell 执行。

## 标准流程

```bash
scripts/systemverilog-agent init PROJECT \
  --name image-control --top image_ctrl \
  --docx spec.docx --xlsx registers.xlsx --rtl rtl

scripts/systemverilog-agent extract PROJECT --skip-tools
# 按 manifest 配置完成 RTL producer 与 tools finalize。

scripts/systemverilog-agent architect PROJECT --mode patch
# 人工或 Agent 完成 .systemc-agent/contracts/rtl-handoff.yaml。
scripts/systemverilog-agent architect PROJECT --validate
# 默认无需人工审批，generate 自动锁定当前内容。
# 正式评审或 review_gate: required 时再执行：
# scripts/systemverilog-agent approve PROJECT --approver NAME
scripts/systemverilog-agent generate PROJECT
scripts/systemverilog-agent apply-edits PROJECT edits.json
scripts/systemverilog-agent verify PROJECT
```

默认 handoff 使用 `review_gate: optional`，`generate` 自动创建带摘要的 `rtl-checkpoint.yaml`。它弱化了人工流程，但输入、图谱、源码索引或 handoff 漂移仍会阻断 edit/verify。正式交付可设置 `review_gate: required` 并执行具名审批。

`generate` 不覆盖已有 worktree 或 baseline。新一轮生成前应先保存已有 diff/report，再明确处理旧的生成目录。

## LLM 编辑协议

LLM不直接修改原始 RTL，只输出结构化 edit：

```json
{
  "edits": [
    {
      "target_id": "syn-0123...",
      "base_sha256": "节点原文摘要",
      "replacement_text": "always_comb begin\n  ...\nend",
      "requirement_ids": ["RTL-FUNC-001"]
    }
  ]
}
```

工具拒绝未知或重复 target、摘要过期、requirement 不匹配、重叠区间和路径穿越。通过校验后只修改隔离 worktree，并生成 `changes.diff`。

## 验证报告

`verification.json` 独立记录 worktree 完整性、pyslang parse、结构差分、lint、compile 和用户已有 simulation tests。任何失败使总状态为 `failed`；缺少 pyslang、外部工具或现有 testbench 时为 `blocked`，不会伪装成通过。
