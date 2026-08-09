# Cycle-Level SystemC 建模工作流 PoC

本目录是自包含项目，可以直接复制到 `~/Project/cycle-systemc-poc` 后初始化独立仓库。
构建产物、生成代码和 trace 默认写到 `~/Work/cycle-systemc-poc` 或 `/tmp`，不写入源码树。

依赖：Python 3.10+、CMake 3.20+、C++17、Verilator 5、SystemC，以及带 Slang
frontend 的 CIRCT `circt-verilog`。运行混合验证前应把 CIRCT 的 `bin` 加入 `PATH`。

该 PoC 将研究问题拆成四个可独立验证的层次：

1. `rtl/` 与 `tools/run_feature_ladder.py` 探测 CIRCT 的实际转换边界；
2. `CycleModelAdapter` 与 `FunctionalModel` 使用同一个 `IModel` 事务接口验证抽象；
3. `TlmModelAdapter` 在 functional core 外提供标准 TLM-2.0 target socket。
4. CIRCT 提取 `hw.module`/`hw.instance` 层次，生成 SystemC 结构壳；叶分区由
   Verilator `--sc` 或端口兼容的原生 SystemC 模块实现。

## 当前机器可运行部分

```bash
cmake -S . -B /tmp/cycle-systemc-build \
  -DBUILD_SYSTEMC_POC=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/cycle-systemc-build --parallel
ctest --test-dir /tmp/cycle-systemc-build --output-on-failure
/tmp/cycle-systemc-build/model_benchmark > /tmp/cycle-systemc-benchmark.csv
```

## 完整 SystemC/TLM 验证

在已安装 SystemC headers/library 的环境运行。CMake 同时支持 `SystemCLanguage`
package 和 Debian `libsystemc-dev` 的 `find_path`/`find_library` fallback：

```bash
cmake -S . -B /tmp/cycle-systemc-full-build \
  -DBUILD_SYSTEMC_POC=ON -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/cycle-systemc-full-build --parallel
ctest --test-dir /tmp/cycle-systemc-full-build --output-on-failure
```

历史上也曾使用 `ghcr.io/trv3wood/eda-scc:main` 验证 2/2 CTest；独立仓库不依赖
`eda-sandbox` 的容器 wrapper，默认使用宿主机 SystemC。

## CIRCT 引导的混合 SystemC

先只生成 CIRCT Core MLIR、版本化 manifest 和全 Verilated SystemC 结构壳：

```bash
python3 tools/generate_hybrid.py \
  --circt-verilog circt-verilog \
  --filelist rtl/hybrid.f \
  --top hybrid_stream_accel \
  --config config/hybrid.json \
  --work "$HOME/Work/cycle-systemc-poc/hybrid"
```

完整构建并比较以下三种 SystemC 仿真实现：

1. 原始单体 `stream_accel` 由一次 Verilator `--sc` 生成，作为黄金模型；
2. CIRCT 结构壳连接两个独立 Verilator `--sc` 分区；
3. 同一结构壳连接 Verilated `sample_transform` 和原生 `StreamAccumulatorSc`。

```bash
python3 tools/run_hybrid.py \
  --circt-verilog circt-verilog \
  --work "$HOME/Work/cycle-systemc-poc/hybrid-run" \
  --transactions 1000 \
  --seed 20260809
```

脚本将生成三份逐周期 trace，比较顶层 ready/valid/result 和分区边界 `term`，并断言
恰好完成请求数量。首版会主动拒绝非纯结构顶层、超过 64 位的端口、缺失分区配置和
分区反馈环；完整限制见 `task.md`。

## CIRCT 特性阶梯

PATH 中必须同时存在启用 slang frontend 的 `circt-verilog`、`circt-opt` 和
`circt-translate`：

```bash
export CIRCT_HOME="${CIRCT_HOME:-/opt/circt/firtool-1.154.0}"
export PATH="${CIRCT_HOME}/bin:${PATH}"
python3 tools/run_feature_ladder.py \
  --work "$HOME/Work/cycle-systemc-poc/circt-1.154.0"
```

当前使用 CIRCT 官方 `firtool-1.154.0` Linux x64 静态包。下载文件
`firrtl-bin-linux-x64.tar.gz` 的 SHA256 必须为
`11eed2d6487bd547fc024905d9f92b205e5f69d4967668f5eb0ce1a91a91da8b`；归档解压后
已经包含上述三个工具和 slang frontend，不需要在本机重编 CIRCT。工具目录可整体
迁移到 `/opt/circt/firtool-1.154.0`，迁移后只需更新 `CIRCT_HOME`。

报告固定写入 `feature-ladder.json`。若还要编译生成的 SystemC header，设置
`SYSTEMC_CXXFLAGS` 为当前 SDK 所需的 include 参数。生成代码的真正链接/运行需要由
后续 testbench 补齐；当前脚本把该阶段准确标记为 compile smoke test。

2026-08-09 的 1.154.0 实测中，八档 frontend 全部通过，三档 HW-to-SystemC
conversion 通过，但 emission 仍全部失败；详细 operation 和日志位置见
`docs/EVIDENCE.md`。脚本返回非零在当前 backend 能力矩阵下是预期研究结果，不代表
工具未安装。

`rtl/stream_accel.sv` 是方法学参考模块，不是用户真实 RTL。真实模块接入时必须替换
filelist/top，并从原始规格重新确认 reset、完成、背压与溢出语义。

## 完整验收

如果已安装 `eda-harness`，可在仓库根执行：

```bash
eda-harness discover .
eda-harness snapshot . --task task.md --config harness.yaml
eda-harness verify . --task task.md --config harness.yaml
```

不使用 harness 时，`scripts/run_all.sh ~/Work/cycle-systemc-poc` 会执行 CMake/CTest、
混合 SystemC 1000 笔对拍和 CIRCT feature ladder。feature ladder 中 exporter 失败是已知
研究结果，因此脚本最终会如实返回非零。
