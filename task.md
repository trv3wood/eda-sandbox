# AI 辅助 Cycle-Level SystemC 建模工作流 PoC

## 目标

在五个工作日的研究时间盒内，建立一个可复现的最小闭环：

1. 用 CIRCT 探测 SystemVerilog 到 SystemC 的实际能力边界；
2. 对可用的 cycle-level 模型与 RTL 做逐周期比较；
3. 将 cycle-level 模型抽象为事务级 functional core；
4. 用标准 TLM-2.0 `b_transport` 薄包装 functional core；
5. 用共享 stimulus 验证事务等价并测量性能。

交付物包括可运行 PoC、自动化脚本、原始结果格式、`docs/EVIDENCE.md`、
`docs/MODEL_ARCH.md` 和最终调研报告。代码注释使用中文。

## 输入与范围

- 仓库内提供自包含特性阶梯和一个有状态 valid/ready 数据通路参考模块。
- 真实项目模块尚未提供；PoC 的数据通路只能作为方法验证，不能代表真实项目结论。
- 中间 MLIR、生成代码、构建目录、日志和 benchmark 数据写入仓库外工作目录。
- 不下载大型镜像，不在本机重编 CIRCT/minres-SCC，不启动商业 EDA 作业。
- CIRCT Verilated interop 只记录为后续研究项，本轮不实现。

## 工具后端

### RTL 基准

- 后端：Verilator。
- 能力：SystemVerilog lint、编译和仿真。
- 选择依据：当前环境版本 probe 可用，适合开源 PoC 的行为基准。
- 不可替代项：它不能证明商业 elaboration，也不能替代 CIRCT 转换结果。

### SV 到 SystemC

- 后端：启用 slang frontend 的 `circt-verilog`、`circt-opt`、
  `circt-translate`。
- 能力：SV elaboration、HW/Comb/Seq IR、HW-to-SystemC、SystemC C++ emission。
- 当前状态：本进程 PATH 中不可用，属于 required blocked。
- 不允许降级：Verilator `--sc` 不是人类可维护的纯 SystemC 转换结果。

### SystemC/TLM

- 后端：C++/CMake/CTest + SystemC；SCC 仅作为可选 adapter/日志能力。
- 当前状态：宿主机未配置 SystemC/SCC SDK；本地
  `ghcr.io/trv3wood/eda-scc:main` 镜像已完成真实 configure/build/CTest。
- 复现命令：见 `research/cycle-systemc-poc/README.md` 的 SCC 容器验证章节。
- 核心 functional model 不依赖 SystemC/SCC，可独立编译验证。

## 验收条件

- 特性阶梯逐项记录 frontend、conversion、emission、compile、run 五个阶段。
- 支持的 cycle-level 模型与 Verilator 在每个有效时钟边沿输出一致。
- `CycleModelAdapter` 与 `FunctionalModel` 在事务边界的响应和架构可见状态一致。
- TLM wrapper 覆盖正常请求、非法地址、非法长度和 delay annotation。
- benchmark 使用 Release 构建、固定 seed、预热和至少五次重复，报告原始数据，
  不预设加速倍数。
- 缺少 CIRCT/SystemC 时总体结果为 blocked；已能运行的 host-only 测试仍须通过。
