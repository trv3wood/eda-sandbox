---
name: cycle-systemc-modeling
description: Build and verify an independent, input-driven cycle-accurate SystemC model from RTL. Use when reset, state, FIFO/RAM latency, handshake, arbitration, protocol timing, or per-cycle outputs must match RTL; reject trace predictors, runner-embedded DUT behavior, absolute-cycle specialization, and loosely timed TLM models.
---

# Cycle-SystemC 建模

由不同 agent 顺序完成基础设施、模型和最终验收；不得让同一 agent 兼任这些角色。各阶段
只交付代码、配置和机器结果，不写 evidence、architecture、coverage 或迭代说明文档。

1. **Harness Agent**：恢复 RTL closure，建立 reference、BFM、stimulus generator、trace
   schema 和 `cycle-harness.yaml`；调用 `$eda-tool-assistant` 解决工具环境。先证明 RTL
   baseline 可复现，再冻结这些文件和公开回归。它不得实现 SystemC DUT。
2. **Model Agent**：使用全新会话，只读冻结的 harness/RTL，按需调用 EDA 工具澄清语义；
   只修改 SystemC DUT 与必要 build glue。Runner 只能解析、驱动、clock/delta 和序列化；
   DUT 行为只能由输入、配置和显式状态推导，禁止 seed/scenario/sample/绝对 cycle、reference
   trace 或测试 payload 特化。大型设计按可组合功能逐级实现。
3. **Acceptance Agent**：Model Agent 停止且模型冻结后，用另一全新会话复核改动边界并运行
   `eda-harness verify-cycle`；再使用 Model Agent 不可见的 stimulus generator/seeds 做隐藏
   payload、地址、timing、ACK/NACK、stall/stretch、reset 和 idle-shift metamorphic 差分。

Model Agent 不得修改冻结 harness；Harness Agent 不得根据候选模型调整 oracle；Acceptance
Agent 不把隐藏失败反馈给原模型继续拟合。公开门禁通过仅称 `regression-passed`；独立性、
隐藏与 metamorphic 差分全部通过后才称 `cycle-equivalent`。
