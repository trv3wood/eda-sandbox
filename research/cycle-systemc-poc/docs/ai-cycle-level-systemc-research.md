# AI 辅助 Cycle-Level SystemC 建模工作流：首轮调研与 PoC

## 当前结论

建议把路线拆成三个相互独立的验证问题，而不是一次性承诺 RTL 自动生成高性能模型：

1. CIRCT 是否能把目标 RTL 的具体语法和 `hw/comb/seq` operation 完整导出 SystemC；
2. AI 能否在明确事务边界后，把已确认的 cycle 语义安全抽象成 functional core；
3. functional core 是否能用薄 TLM wrapper 接入 SCC/VCML 或混合仿真环境。

PoC 已实现后两个问题的代码结构；TLM 已在 SCC 镜像中完成编译和 contract test。
官方 CIRCT firtool-1.154.0 静态工具链已经部署并运行 feature ladder；环境阻塞已解除，
但当前 backend 尚未让任何用例完成 SystemC C++ emission。作为绕开该阻塞的工程路径，
PoC 已实现“CIRCT 提取结构 + Verilator `--sc` 保留分区行为 + 原生 SystemC 按分区替换”。

## 能力矩阵

| 能力 | 当前状态 | 证据或阻塞 |
|---|---|---|
| C++ core configure/build | passed | GCC 15.2、CMake Release 构建 |
| CL 参考适配器↔Functional 事务等价 | passed | 固定 seed 的 1000 个随机事务 |
| 参考 RTL directed simulation | passed | Verilator 5.032，结果 55 |
| Functional 性能收益 | observed | 20,000×32 samples，五次原始数据由 benchmark 输出 |
| CIRCT SV frontend | passed | firtool-1.154.0 + slang 11.0.0+0，8/8 用例通过 |
| HW-to-SystemC conversion | partial | comb、hierarchy、parameterized 通过，3/8 |
| SystemC C++ emission | failed | 0/3；缺少 `systemc.convert`/`comb.*` pattern，层次 IR 重解析失败 |
| CIRCT 生成 SystemC 编译运行 | blocked | emission 无成功输出，尚无可编译生成物 |
| CIRCT 引导的结构壳 | passed | `hw.module`/`hw.instance` manifest 与生成的 SystemC 连线 |
| Verilated/SystemC 混合替换 | passed | 三路 1000 笔逐周期 trace 一致，含分区边界检查 |
| 手写 TLM wrapper contract | passed | SCC 镜像内 configure/build，2/2 CTest 通过 |
| 真实项目代表性 | blocked | 尚未提供真实模块、filelist、top 和规格 |

SCC 镜像内一次 Release 运行的五次中位数约为 cycle adapter 613,999 ns、functional
model 88,725 ns，即约 6.92×。该数字只衡量本 PoC 的两个 C++ 实现，不代表 CIRCT
生成模型、SystemC kernel 或真实项目的加速比；正式报告应保存目标机器的原始 CSV
并重新统计。

## 已交付实验设施

- 八档 CIRCT feature ladder：组合、层次、counter、FSM、memory、parameter、inout、
  stream accelerator。
- 五阶段 JSON 结果格式：frontend、conversion、emission、compile、run；上游失败不会
  被误写成下游工具失败。
- `IModel`、Cycle/Functional 两个实现、1000 笔随机事务等价测试及五次性能测量。
- 标准 TLM-2.0 `b_transport` wrapper 和正常/非法地址/非法长度 contract test。
- Verilator directed testbench，验证 valid/ready、完成条件和 32 位累加结果。
- 版本化 hierarchy manifest、纯结构 SystemC 壳生成器，以及单体/全 Verilated/混合
  三路共享 stimulus 对拍。

## CIRCT 实验判定规则

CIRCT 官方的 `convert-hw-to-systemc` 目标是把 HW design 转为 SystemC design，但当前
backend 对不同 dialect 的覆盖必须以目标版本实测。1.154.0 中 parameterized 用例经
Slang elaboration 后已不再携带模块参数，因此 conversion 通过；inout 首败于
`llhd.prb`。顺序 RTL 经 frontend 产生 `seq.*`，counter/FSM/memory/stream_accel 均首败于
`seq.to_clock`，不能由组合用例外推。即便 comb conversion 通过，exporter 仍因
`systemc.convert` 和 `comb.*` 无 emission pattern 而失败。

每个用例必须保留 Core MLIR、SystemC MLIR、生成 header 和日志。只有五阶段全部通过
才能写“该用例 SV→SystemC 成功”；若失败，应报告首个非法 operation 和最小复现。

## 下一步执行顺序

1. 固定使用官方 firtool-1.154.0 静态 artifact，并保留 tag commit、归档 SHA256 和
   feature ladder 原始日志。
2. 不再把未维护的 SystemC exporter 作为交付关键路径；保留最小复现作为 upstream
   能力记录。
3. 当前继续固定使用本地 SCC 镜像；需要宿主开发时再导出 SDK artifact。
4. 提供一个有状态小型真实数据通路及 spec、top、filelist、include、define、reset 和
   完成语义；替换参考模块并建立 RTL trace。
5. 用真实项目的纯结构边界替换 PoC 顶层，复用现有 manifest、结构壳和共享 stimulus；
   然后逐个替换适合抽象的分区。
6. 在后续阶段单独验证 CIRCT `systemc.interop.verilated`，评估已抽象模块与未抽象
   Verilated RTL 的混合替换，不与本轮纯转换结论混淆。

## 决策建议

- 继续投入混合分区路线；不再以“CIRCT 自动转换一般 cycle-level RTL”为产品前提。
- AI 的主要价值放在语义抽取、functional 分解、adapter/test 生成和失败迭代，而不是
  假设一次 prompt 即可保证等价。
- TLM 保持外层通信抽象，functional core 保持纯 C++；需要周期细节时替换 adapter，
  不修改上层 initiator。
- 下一次向 CIRCT 专家咨询时提交最小 SV、Core MLIR、失败 operation 和完整命令，避免
  只描述“转换失败”。

## 参考资料

- [CIRCT `convert-hw-to-systemc` pass](https://circt.llvm.org/docs/Passes/)
- [CIRCT firtool-1.154.0 release](https://github.com/llvm/circt/releases/tag/firtool-1.154.0)
- [CIRCT Verilog frontend](https://circt.llvm.org/docs/Tools/circt-verilog/)
- [CIRCT SystemC dialect](https://circt.llvm.org/docs/Dialects/SystemC/)
- [CIRCT HWToSystemC 当前源码](https://circt.llvm.org/doxygen/HWToSystemC_8cpp_source.html)
- [Verilator SystemC 连接模型](https://verilator.org/guide/latest/connecting.html)
- [SystemC-Components](https://minres.github.io/SystemC-Components/)
