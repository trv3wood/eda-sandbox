# AI 辅助 Cycle-Level SystemC 建模工作流：首轮调研与 PoC

## 当前结论

建议把路线拆成三个相互独立的验证问题，而不是一次性承诺 RTL 自动生成高性能模型：

1. CIRCT 是否能把目标 RTL 的具体语法和 `hw/comb/seq` operation 完整导出 SystemC；
2. AI 能否在明确事务边界后，把已确认的 cycle 语义安全抽象成 functional core；
3. functional core 是否能用薄 TLM wrapper 接入 SCC/VCML 或混合仿真环境。

PoC 已实现后两个问题的代码结构；TLM 已在 SCC 镜像中完成编译和 contract test。
第一个问题仍因 CIRCT 环境缺失而 blocked，尚无转换实验结论。

## 能力矩阵

| 能力 | 当前状态 | 证据或阻塞 |
|---|---|---|
| C++ core configure/build | passed | GCC 15.2、CMake Release 构建 |
| CL 参考适配器↔Functional 事务等价 | passed | 固定 seed 的 1000 个随机事务 |
| 参考 RTL directed simulation | passed | Verilator 5.032，结果 55 |
| Functional 性能收益 | observed | 20,000×32 samples，五次原始数据由 benchmark 输出 |
| CIRCT frontend/conversion/emission | blocked | 三个 CIRCT 工具均不在当前 PATH |
| CIRCT 生成 SystemC 编译运行 | blocked | CIRCT 工具未配置 |
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

## CIRCT 实验判定规则

CIRCT 官方的 `convert-hw-to-systemc` 目标是把 HW design 转为 SystemC design，但当前
backend 对不同 dialect 的覆盖必须以目标版本实测。当前源码仍明确拒绝 parameterized
module 和 `inout`；顺序 RTL 经 frontend 产生 `seq.*`，因此 counter/FSM/memory 是必须
单列的风险探针，而不是由组合 adder 的成功外推。

每个用例必须保留 Core MLIR、SystemC MLIR、生成 header 和日志。只有五阶段全部通过
才能写“该用例 SV→SystemC 成功”；若失败，应报告首个非法 operation 和最小复现。

## 下一步执行顺序

1. 团队提供启用 slang frontend 的 CIRCT 工具路径或已构建 artifact，并记录 commit。
2. 当前先固定使用本地 SCC 镜像；需要宿主开发时再导出 SDK artifact。
3. 运行 feature ladder，先获得组合/顺序/参数/inout 的实际矩阵。
4. 提供一个有状态小型真实数据通路及 spec、top、filelist、include、define、reset 和
   完成语义；替换参考模块并建立 RTL trace。
5. 对 CIRCT 生成的 CL SystemC 接入共享 stimulus，再开展真实的 CL→Functional
   抽象和性能比较。
6. 在后续阶段单独验证 CIRCT `systemc.interop.verilated`，评估已抽象模块与未抽象
   Verilated RTL 的混合替换，不与本轮纯转换结论混淆。

## 决策建议

- 继续投入，但把“CIRCT 能自动转换一般 cycle-level RTL”设为待验证假设。
- AI 的主要价值放在语义抽取、functional 分解、adapter/test 生成和失败迭代，而不是
  假设一次 prompt 即可保证等价。
- TLM 保持外层通信抽象，functional core 保持纯 C++；需要周期细节时替换 adapter，
  不修改上层 initiator。
- 下一次向 CIRCT 专家咨询时提交最小 SV、Core MLIR、失败 operation 和完整命令，避免
  只描述“转换失败”。

## 参考资料

- [CIRCT `convert-hw-to-systemc` pass](https://circt.llvm.org/docs/Passes/)
- [CIRCT Verilog frontend](https://circt.llvm.org/docs/Tools/circt-verilog/)
- [CIRCT SystemC dialect](https://circt.llvm.org/docs/Dialects/SystemC/)
- [CIRCT HWToSystemC 当前源码](https://circt.llvm.org/doxygen/HWToSystemC_8cpp_source.html)
- [Verilator SystemC 连接模型](https://verilator.org/guide/latest/connecting.html)
- [SystemC-Components](https://minres.github.io/SystemC-Components/)
