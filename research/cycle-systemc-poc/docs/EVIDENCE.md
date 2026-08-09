# Cycle-Level SystemC PoC 语义证据

本文件只记录已经由工具或测试观察到的事实。CIRCT firtool-1.154.0 已完成工具探测和
八档 feature ladder；SystemC/TLM 已在本地 SCC 镜像和宿主机 SystemC 3.0.2 中验证，
不把源码推断写成验证结论。

## CIRCT 层次与 SystemC 分区替换

- RTL 依据：`rtl/hybrid_stream_accel.sv:1-8` 是组合 transform，`:10-52` 是有状态
  accumulator，`:54-90` 的顶层只包含两个实例和连线。
- 规格依据：`task.md` 的“CIRCT 引导的混合 SystemC 组合器”目标和首版限制。
- EDA 证据：CIRCT firtool-1.154.0 `circt-verilog --ir-hw` 产生两个
  `hw.instance`；manifest 记录 `transform.term -> accumulator.term`。Verilator 5.032
  分别以 `--sc --pins-sc-uint` 编译原始 `stream_accel` 和两个叶分区，SystemC 3.0.2
  成功链接运行。
- 模型复刻：`src/stream_accumulator_sc.cpp:3-43`；其中 `:26-32` 保留 SystemVerilog
  非阻塞赋值在同一时钟沿观察旧 `active` 的语义。
- 验证：`tools/run_hybrid.py` 使用同一 stimulus 比较单体、全 Verilated 分区和混合
  分区。2026-08-09 以 seed `20260809` 完成 1000 笔事务，三份 trace 逐字节一致；
  覆盖 length=1/255、32 位溢出数据、随机空洞/backpressure 和 active reset。
- 原始证据：`/tmp/eda-cycle-hybrid-1000/` 中的 hierarchy、生成的结构壳、stimulus、
  三个 executable 和 `trace_{golden,all_verilated,mixed}.csv`。
- 复现：

  ```bash
  python3 tools/run_hybrid.py \
    --circt-verilog "$CIRCT_HOME/bin/circt-verilog" \
    --work /tmp/eda-cycle-hybrid-1000 --transactions 1000 --seed 20260809
  ```

- 结论限制：这是共享 stimulus 的逐周期差分验证，不是形式等价；文本 MLIR 解析器只
  接受声明的 canonical HW 子集，生产版本需要替换为链接 CIRCT SDK 的 C++ pass。

## valid/ready 接收与完成条件

- RTL 依据：`rtl/stream_accel.sv:19` 定义输入 ready；
  `:33-41` 定义 start、输入接收、剩余计数和完成条件。
- 规格依据：`task.md` 的真实模块选择条件与事务等价验收条件。
- EDA 证据：Verilator 5.032 编译并运行 `tb_stream_accel`，3 个输入
  `5, 7, 11` 在 `scale=2, bias=3` 时观察到 `out_valid` 和结果 55。
- 复现：
  `verilator --binary --timing --top-module tb_stream_accel --Mdir /tmp/eda-cycle-systemc-verilator rtl/stream_accel.sv rtl/tb_stream_accel.sv`
  后运行 `/tmp/eda-cycle-systemc-verilator/Vtb_stream_accel`。
- 模型复刻：`src/model.cpp:30-54`。
- 验证：`model_equivalence` 检查 1000 个固定 seed 随机事务，并验证每笔事务为
  `samples.size() + 2` 个适配器周期。

## 算术与 32 位自然溢出

- RTL 依据：`rtl/stream_accel.sv:17,38` 使用 32 位累加器，
  每个输入计算 `in_data * scale + bias`。
- 规格依据：PoC 以 RTL 位宽为真值；真实模块接入后必须回到其原始规格。
- EDA 证据：Verilator lint 首次发现 bias 隐式扩展警告；显式零扩展后 lint 通过，
  directed simulation 得到结果 55。
- 模型复刻：`src/model.cpp:20-24,43-45,61-66`。
- 验证：cycle adapter 与 functional model 的 1000 个随机事务响应完全一致。

## 架构可见事务计数

- RTL 依据：参考 RTL 没有该寄存器；这是 PoC adapter 为演示事务级可见状态而新增，
  不能声称来自 RTL。
- 规格依据：`task.md` 要求比较响应和架构可见状态。
- 工具证据：`model_equivalence` 连续执行 1000 笔事务，两个实现的计数逐笔一致。
- 模型复刻：`src/model.cpp:53-54,66`。
- 验证：`tests/test_models.cpp`。

## TLM 地址、错误响应和时延

- RTL 依据：无；TLM 地址映射是 wrapper 协议，不是参考 RTL 的寄存器接口。
- 规格依据：`include/tlm_adapter.hpp` 中的线协议说明。
- EDA 证据：`ghcr.io/trv3wood/eda-scc:main`（image ID `c4faf6d76632`）中，
  CMake 使用 `/opt/scc:/opt/scc-deps` 找到 SystemC，`tlm_contract` 编译并通过。
- 模型复刻：`src/tlm_adapter.cpp:28-72`。
- 验证：`tlm_contract` 覆盖正常访问、非法地址、非法长度和每次成功访问
  10 ns delay annotation。

## CIRCT 转换覆盖范围

- RTL 依据：`rtl/` 的组合、层次、寄存器、FSM、memory、
  parameter、inout 和有状态数据通路八档用例。
- 规格依据：`task.md` 的五阶段转换验收条件。
- 工具版本：官方 Linux x64 静态包 `firtool-1.154.0`，tag commit
  `87898a876f730a2ebc607dc9b83da487cba49119`，归档 SHA256
  `11eed2d6487bd547fc024905d9f92b205e5f69d4967668f5eb0ce1a91a91da8b`；
  `circt-verilog` 报告 slang 11.0.0+0，三个必需二进制均为静态 x86-64 ELF。
- 2026-08-09 实测：八档 frontend 全部通过；comb、hierarchy、parameterized 的
  HW-to-SystemC conversion 通过，其余五档 conversion 失败；没有用例完成 emission。
- 首个失败 operation：counter/FSM/memory/stream_accel 为 `seq.to_clock`，inout 为
  `llhd.prb`；comb 和 parameterized emission 为 `systemc.convert`，并同时缺少
  `comb.add` 等 emission pattern；hierarchy 的 SystemC MLIR 重解析时报告重复
  `sym_visibility`。
- 原始证据：`~/Work/cycle-systemc-poc/circt-1.154.0/` 下的
  `feature-ladder.json`、Core/SystemC MLIR 和逐阶段日志。
- 复现：先将 `$CIRCT_HOME/bin` 前置到
  `PATH`，再运行以下命令：

  ```bash
  python3 tools/run_feature_ladder.py \
    --work ~/Work/cycle-systemc-poc/circt-1.154.0
  ```

- 结论限制：工具链已达到 `usable`，且 frontend 和部分 conversion 已由项目探针验证；
  仍不能声称任一用例完成 SV→SystemC，也不能进入生成代码编译和运行验证。
