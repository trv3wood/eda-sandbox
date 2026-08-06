# 中等规模 RTL 修改基准：OpenTitan GPIO 可编程输入滤波周期

## 选择理由

OpenTitan GPIO 是合适的中等规模 IP：它有技术规格、寄存器描述、模板 RTL、UVM DV、lint 配置和自动生成流程，但数据通路与状态规模仍足以在单个迭代内理解。基准应固定一个 OpenTitan commit，修改 `hw/ip_templates/gpio/` 源模板，不直接编辑 top 下的自动生成副本。

现有规格为每个 GPIO 提供独立 filter enable，但滤波时间固定为输入稳定 16 个模块时钟周期。任务把固定常量改为软件可配置阈值，同时保持复位后的既有行为。

## 修改需求

新增全局 RW 寄存器 `CTRL_INPUT_FILTER_CYCLES`：

- `cycles[7:0]` 复位值为 `16`。
- 合法配置范围为 `1..255`；写入 `0` 时硬件按 `1` 周期处理。
- `CTRL_EN_INPUT_FILTER[n] == 0` 时，第 `n` 个输入保持现有直通行为。
- filter enable 时，输入必须连续稳定 `effective_cycles` 个采样周期才更新 filtered value。
- 更新 filtered value 后计数器清零；输入再次翻转时重新计数。
- 软件在计数过程中修改周期值时，所有已启用 filter 的未完成计数清零，新阈值从下一次采样开始生效。
- `DATA_IN` 和 GPIO interrupt detection 继续消费同一个 filtered value。
- strap sampling、输出寄存器、output enable 和现有中断寄存器语义不变。
- 默认值 `16` 必须与修改前 cycle behavior 一致。

## 预期修改面

- `data/*.hjson`：新增寄存器及字段说明，重新生成寄存器 RTL/文档。
- `doc/`：把固定 16-cycle 描述改为可编程语义，补充 0 值与动态重配置规则。
- `rtl/gpio.sv.tpl`：将固定深度 filter 改为共享阈值、每 pin 独立稳定计数；保留现有 filtered-data/interrupt 路径。
- `dv/`：扩展寄存器模型、scoreboard/sequence 和 functional coverage。
- 软件 DIF 如仅暴露 raw MMIO 可保持不变；若项目约定每个控制寄存器都有 helper，则新增设置/读取 API 和单元测试。

## 验收场景

1. 复位后输入在第 16 个连续稳定采样后更新，行为与基线一致。
2. 阈值为 1、2、16、255 时，恰好在对应周期更新，不能早一拍或晚一拍。
3. 稳定计数完成前输入翻转，旧方向计数被丢弃并从新值重新开始。
4. 两个 pin 使用相同全局阈值但独立计数，互不干扰。
5. 某 pin filter disabled 时立即反映输入，其他 enabled pin 仍受阈值控制。
6. 计数中修改阈值会清零进行中的计数。
7. filtered rising/falling edge 只在 filtered value 实际更新时触发一次中断。
8. level-high/level-low interrupt、W1C interrupt state 和 interrupt enable 保持既有语义。
9. 写入 0 等价于阈值 1，不出现永不完成或计数下溢。
10. lint、编译、目标 GPIO DV tests 和寄存器一致性检查通过。

## 用于本后端的推荐方式

- 将上述需求和验收场景直接保存到 `task.md`。
- `allowed_changes` 只包含 GPIO 源模板、HJSON、文档和相关 DV；自动生成的寄存器文件通过 OpenTitan regtool 更新。
- 在修改前运行 `eda-harness snapshot`，最终用 integrity gate 检查是否误改无关文件。
- 把 OpenTitan 原生 reggen、lint、compile 和目标 DV 命令写入 `harness.yaml`；缺少商业 simulator 时报告 `blocked`，不要把较低层验证描述为完整通过。
