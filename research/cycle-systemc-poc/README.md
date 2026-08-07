# Cycle-Level SystemC 建模工作流 PoC

该 PoC 将研究问题拆成三个可独立验证的层次：

1. `rtl/` 与 `tools/run_feature_ladder.py` 探测 CIRCT 的实际转换边界；
2. `CycleModelAdapter` 与 `FunctionalModel` 使用同一个 `IModel` 事务接口验证抽象；
3. `TlmModelAdapter` 在 functional core 外提供标准 TLM-2.0 target socket。

## 当前机器可运行部分

```bash
cmake -S . -B /tmp/cycle-systemc-build \
  -DBUILD_SYSTEMC_POC=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/cycle-systemc-build --parallel
ctest --test-dir /tmp/cycle-systemc-build --output-on-failure
/tmp/cycle-systemc-build/model_benchmark > /tmp/cycle-systemc-benchmark.csv
```

## 完整 SystemC/TLM 验证

在已配置 `SystemCLanguage` CMake package 的环境运行：

```bash
cmake -S . -B /tmp/cycle-systemc-full-build \
  -DBUILD_SYSTEMC_POC=ON -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/cycle-systemc-full-build --parallel
ctest --test-dir /tmp/cycle-systemc-full-build --output-on-failure
```

当前仓库使用本地 SCC 镜像的验证命令：

```bash
EDA_CONTAINER_ENGINE=podman scripts/eda-run \
  --work "$PWD" \
  --image ghcr.io/trv3wood/eda-scc:main \
  --pull never scc bash -lc '
    set -Eeuo pipefail
    cmake -S /workspace/research/cycle-systemc-poc \
      -B /tmp/cycle-systemc-full-build \
      -DBUILD_SYSTEMC_POC=ON -DCMAKE_BUILD_TYPE=Release
    cmake --build /tmp/cycle-systemc-full-build --parallel
    ctest --test-dir /tmp/cycle-systemc-full-build --output-on-failure
  '
```

2026-08-07 使用 `ghcr.io/trv3wood/eda-scc:main`、image ID
`c4faf6d76632` 验证结果为 2/2 CTest 通过。`--pull never` 保证不会隐式下载或更新镜像。

## CIRCT 特性阶梯

PATH 中必须同时存在启用 slang frontend 的 `circt-verilog`、`circt-opt` 和
`circt-translate`：

```bash
python3 tools/run_feature_ladder.py --work ~/Work/cycle-systemc-poc/circt
```

报告固定写入 `feature-ladder.json`。若还要编译生成的 SystemC header，设置
`SYSTEMC_CXXFLAGS` 为当前 SDK 所需的 include 参数。生成代码的真正链接/运行需要由
后续 testbench 补齐；当前脚本把该阶段准确标记为 compile smoke test。

`rtl/stream_accel.sv` 是方法学参考模块，不是用户真实 RTL。真实模块接入时必须替换
filelist/top，并从原始规格重新确认 reset、完成、背压与溢出语义。
