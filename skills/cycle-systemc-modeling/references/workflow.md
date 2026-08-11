# EDA 增强的 RTL 到 Cycle-SystemC 工作流

## 1. 建立可执行设计闭包

- 从工程原生 filelist、core manager 或 build target 取得源文件顺序、include、defines、参数和 top。
- 用选定 simulator 完成 clean compile/elaboration 和 reset/idle baseline。
- 把实际源闭包写入 manifest；不要用手写片段替代真实依赖。

## 2. 用工具形成理解

阅读 RTL 后，对每个影响周期输出的结论至少执行一种 EDA 验证：

| 语义 | 优先证据 |
|---|---|
| 端口、位宽、参数、实例 | elaboration/hierarchy report |
| 边沿、复位、更新优先级 | 定向仿真探针或波形 |
| FIFO/RAM、bypass、read-return | 连续读写的逐周期 trace |
| ready/valid、背压、仲裁 | 竞争、停顿、满空边界 trace |
| 状态机完成、中断、错误 | 定向事务和状态/输出观察 |

`cycle-evidence.yaml` 示例：

```yaml
schema_version: 1
top: fifo_top
semantics:
  - id: fifo-fall-through
    claim: 空 FIFO 在同周期写入后即可观察到 valid 和 data
    rtl_locations: [rtl/fifo.sv:42]
    tool_evidence:
      - command: [make, sim, TEST=fifo_fall_through]
        observation: 上升沿后固定 settle 点 valid=1 且 data 等于本周期写数据
        artifact: evidence/fifo-fall-through.log
    systemc_locations: [model/fifo.cpp:31]
```

证据 artifact 必须保存在 workspace 内。不能只写“阅读代码可知”。

## 3. 转写模型

- 先列出 SystemC 状态及其 RTL 对应，再实现 sequential update 和 combinational output。
- 单 bit 时钟/复位优先使用 `sc_in<bool>`；其他信号使用明确位宽类型。
- 一个 signal 只由一个 process 驱动。不要从一个 process 直接调用另一个输出 process。
- 使用与安装的 SystemC ABI 一致的 C++ 标准；没有工程约束时默认 C++17。
- testbench 写入 `sc_signal` 后按设计需要推进 delta cycle，再在契约规定的 phase 采样。
- 独立实现模型，不包含 reference headers、对象、trace、外部进程或预录输出。

## 4. 差分收敛

- 同一 stimulus 文件同时驱动 reference 和 model；不要分别随机生成。
- 定向场景覆盖 reset、状态边界、冲突优先级、背压和异常路径。
- 公开随机批次用于开发回归；`verify-cycle` 另生成一批新 seeds 做最终门禁。
- mismatch 时保存首错前后窗口，回到对应 RTL 锥并新增证据；不要用容差窗口掩盖采样错误。
