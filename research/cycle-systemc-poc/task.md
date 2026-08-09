# CIRCT 引导的混合 SystemC 组合器 PoC

## 目标

在现有研究 PoC 上建立一个可复现的混合仿真闭环：

1. 用 CIRCT/Slang elaboration 提取纯结构顶层的模块、端口、实例和连接；
2. 生成稳定的版本化 hierarchy manifest 和 SystemC 结构壳；
3. 用 Verilator `--sc` 分别实现 RTL 分区内部行为；
4. 在不改变结构壳和 testbench 的情况下，将一个 RTL 分区替换为原生 SystemC；
5. 用共享 stimulus 对单体 RTL、全 Verilated 分区和混合分区做逐周期比较。

交付物包括可运行 PoC、自动化脚本、原始结果格式、`docs/EVIDENCE.md`、
`docs/MODEL_ARCH.md` 和最终调研报告。代码注释使用中文。

## 输入与范围

- 仓库内提供自包含特性阶梯和一个有状态 valid/ready 数据通路参考模块。
- 新增纯结构 `hybrid_stream_accel`，其行为叶节点为组合 sample transform 和时序 accumulator。
- 真实项目模块尚未提供；PoC 的数据通路只能作为方法验证，不能代表真实项目结论。
- 中间 MLIR、生成代码、构建目录、日志和 benchmark 数据写入仓库外工作目录。
- 不下载大型镜像，不在本机重编 CIRCT/minres-SCC，不启动商业 EDA 作业。
- 首版仅接受单时钟/单低有效异步复位、1～64 位二态 packed input/output、无参数覆盖、
  无 interface/modport/数组/inout、纯结构容器且分区间无反馈环。
- CIRCT `systemc.interop.verilated` 只记录为后续研究项，不作为关键路径。

## 工具后端

### RTL 基准

- 后端：Verilator。
- 能力：SystemVerilog lint、编译和仿真。
- 选择依据：当前环境版本 probe 可用，适合开源 PoC 的行为基准。
- 不可替代项：它不能证明商业 elaboration，也不能替代 CIRCT 转换结果。

### SV 到 SystemC

- 后端：启用 slang frontend 的 `circt-verilog`，以及受限 canonical HW MLIR 提取器。
- 能力：SV elaboration、`hw.module`/`hw.instance` 结构提取和 manifest 生成。
- 当前状态：官方 firtool-1.154.0 Linux x64 静态工具链已部署到仓库外；8/8 frontend
  通过，3/8 conversion 通过，但 0/3 conversion 成功用例完成 emission。工具环境可用，
  backend 能力仍不满足完整转换验收。
- 不允许降级：不把 Verilator `--sc` 宣称为人类可维护的纯 SystemC 转换结果；本任务只把
  它作为分区行为后端。

### SystemC/TLM

- 后端：C++/CMake/CTest + Debian `libsystemc-dev` 3.0.2 + Verilator 5.032。
- 当前状态：宿主机 SystemC headers/library 已安装；Debian 包未提供 CMake package config，
  工程通过 `find_path`/`find_library` fallback 导入目标。
- 复现命令：见 `README.md` 的混合 SystemC 章节。
- 核心 functional model 不依赖 SystemC/SCC，可独立编译验证。

## 验收条件

- 特性阶梯逐项记录 frontend、conversion、emission、compile、run 五个阶段。
- hierarchy manifest 对相同输入确定生成，并拒绝首版范围外结构。
- 单体 RTL、全 Verilated 分区、Verilated+原生 SystemC 分区使用同一 stimulus，
  在有效时钟沿和 delta-cycle 收敛后 trace 完全一致。
- 覆盖 length=1/255、累加溢出、输入空洞、输出 backpressure、idle/active reset 和固定
  seed 的至少 1000 笔随机事务。
- 支持的 cycle-level 模型与 Verilator 在每个有效时钟边沿输出一致。
- `CycleModelAdapter` 与 `FunctionalModel` 在事务边界的响应和架构可见状态一致。
- TLM wrapper 覆盖正常请求、非法地址、非法长度和 delay annotation。
- benchmark 使用 Release 构建、固定 seed、预热和至少五次重复，报告原始数据，
  不预设加速倍数。
- 缺少 CIRCT/SystemC/Verilator 时总体结果为 blocked；工具存在但 backend 不支持时记录首个失败
  operation 并标为 failed，不得回退写成环境 blocked；已能运行的 host-only 测试仍须通过。
