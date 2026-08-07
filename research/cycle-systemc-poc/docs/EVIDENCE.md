# Cycle-Level SystemC PoC 语义证据

本文件只记录已经由工具或测试观察到的事实。CIRCT 当前不可用；SystemC/TLM 已在
本地 SCC 镜像中验证，不把源码推断写成验证结论。

## valid/ready 接收与完成条件

- RTL 依据：`research/cycle-systemc-poc/rtl/stream_accel.sv:19` 定义输入 ready；
  `:33-41` 定义 start、输入接收、剩余计数和完成条件。
- 规格依据：`task.md` 的真实模块选择条件与事务等价验收条件。
- EDA 证据：Verilator 5.032 编译并运行 `tb_stream_accel`，3 个输入
  `5, 7, 11` 在 `scale=2, bias=3` 时观察到 `out_valid` 和结果 55。
- 复现：
  `verilator --binary --timing --top-module tb_stream_accel --Mdir /tmp/eda-cycle-systemc-verilator research/cycle-systemc-poc/rtl/stream_accel.sv research/cycle-systemc-poc/rtl/tb_stream_accel.sv`
  后运行 `/tmp/eda-cycle-systemc-verilator/Vtb_stream_accel`。
- 模型复刻：`research/cycle-systemc-poc/src/model.cpp:30-54`。
- 验证：`model_equivalence` 检查 1000 个固定 seed 随机事务，并验证每笔事务为
  `samples.size() + 2` 个适配器周期。

## 算术与 32 位自然溢出

- RTL 依据：`research/cycle-systemc-poc/rtl/stream_accel.sv:17,38` 使用 32 位累加器，
  每个输入计算 `in_data * scale + bias`。
- 规格依据：PoC 以 RTL 位宽为真值；真实模块接入后必须回到其原始规格。
- EDA 证据：Verilator lint 首次发现 bias 隐式扩展警告；显式零扩展后 lint 通过，
  directed simulation 得到结果 55。
- 模型复刻：`research/cycle-systemc-poc/src/model.cpp:20-24,43-45,61-66`。
- 验证：cycle adapter 与 functional model 的 1000 个随机事务响应完全一致。

## 架构可见事务计数

- RTL 依据：参考 RTL 没有该寄存器；这是 PoC adapter 为演示事务级可见状态而新增，
  不能声称来自 RTL。
- 规格依据：`task.md` 要求比较响应和架构可见状态。
- 工具证据：`model_equivalence` 连续执行 1000 笔事务，两个实现的计数逐笔一致。
- 模型复刻：`research/cycle-systemc-poc/src/model.cpp:53-54,66`。
- 验证：`research/cycle-systemc-poc/tests/test_models.cpp`。

## TLM 地址、错误响应和时延

- RTL 依据：无；TLM 地址映射是 wrapper 协议，不是参考 RTL 的寄存器接口。
- 规格依据：`research/cycle-systemc-poc/include/tlm_adapter.hpp` 中的线协议说明。
- EDA 证据：`ghcr.io/trv3wood/eda-scc:main`（image ID `c4faf6d76632`）中，
  CMake 使用 `/opt/scc:/opt/scc-deps` 找到 SystemC，`tlm_contract` 编译并通过。
- 模型复刻：`research/cycle-systemc-poc/src/tlm_adapter.cpp:28-72`。
- 验证：`tlm_contract` 覆盖正常访问、非法地址、非法长度和每次成功访问
  10 ns delay annotation。

## CIRCT 转换覆盖范围

- RTL 依据：`research/cycle-systemc-poc/rtl/` 的组合、层次、寄存器、FSM、memory、
  parameter、inout 和有状态数据通路八档用例。
- 规格依据：`task.md` 的五阶段转换验收条件。
- 工具证据：`run_feature_ladder.py` 在当前环境生成 `blocked` 报告，缺少
  `circt-verilog`、`circt-opt`、`circt-translate`；没有执行转换。
- 复现：`python3 research/cycle-systemc-poc/tools/run_feature_ladder.py --work /tmp/eda-cycle-systemc-circt`。
- 结论限制：当前不能声称组合或顺序转换成功，也不能把缺工具写成转换失败。
