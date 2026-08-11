---
name: cycle-systemc-modeling
description: Read RTL and specifications, use EDA elaboration, simulation, waveform, and query evidence to understand cycle semantics, transcribe an independent cycle-accurate SystemC model, and prove it with strict RTL differential verification. Use for RTL-to-SystemC conversion where clock-edge behavior, reset, state, FIFO/RAM latency, handshake, arbitration, or per-cycle outputs must match; do not use for loosely timed TLM models.
---

# Cycle-SystemC 建模

阅读设计并用 EDA 工具验证理解，再转写独立 SystemC。

## 工作流

1. 完整阅读 `references/workflow.md` 和 `references/cycle-harness.md`。
2. 检查 RTL、spec、filelist、top、已有 testbench 和构建脚本。调用
   `$eda-tool-assistant` 运行 discovery；缺少 simulator、SystemC SDK、工程 wrapper 或
   环境激活信息时，由它向用户确认并准备外置配置。
3. 恢复工程真实 source closure。优先使用工程原生 simulator；没有可用原生流程时才用
   Verilator 作为 reference oracle，并明确这个选择。
4. 在写模型前调用 EDA 工具验证关键语义。至少覆盖任务适用的端口/位宽、时钟与复位、
   状态更新优先级、memory/FIFO latency、ready/valid、背压与仲裁。每项写入
   `cycle-evidence.yaml`，包含 RTL 位置、实际命令、观测 artifact 和模型映射。
5. 转写 SystemC。以 RTL 可观察的周期行为划分状态和组合逻辑，显式处理定宽运算、边沿、
   异步复位、delta settle 和每个 process 的唯一 driver。
6. 创建 `cycle-harness.yaml` 和共享 stimulus 驱动，分别输出标准 JSONL reference/model
   trace。先局部编译和调试，最终必须运行：

   ```bash
   eda-harness verify-cycle PROJECT --config cycle-harness.yaml
   ```

7. 差分失败时只定位首个 mismatch，回到 RTL 与 EDA 证据复核；修复后重跑完整门禁。
   只有报告状态为 `passed` 且 result 为 `cycle-equivalent` 才能宣称完成。

## 建模边界

- 默认契约是单时钟、明确复位和合法二态 stimulus。
- 多时钟/CDC、X/Z、模拟时序或厂商原语必须拥有额外契约和差分测试；否则报告 blocked
  或范围外。
- 编译通过、SystemC unit test 通过或单条 trace 通过都不是 cycle 等价。
- 不削弱 observable、随机批次、采样 phase、证据或反逃逸检查来获得绿色结果。
- 使用 RTL、原生 elaboration/simulation、波形及可用结构查询。
