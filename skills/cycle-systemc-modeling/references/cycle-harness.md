# Cycle Harness 契约

`verify-cycle` 使用独立的 `cycle-harness.yaml`，不读取 `task.md`。

```yaml
schema_version: 1
workspace: .
top: fifo_top
evidence: cycle-evidence.yaml
source_manifest: rtl/files.f
model_sources: [model/fifo.h, model/fifo.cpp]
model_binary: "{run_dir}/model/fifo-model"
clock: {name: clk_i, edge: rising}
reset: {name: rst_ni, active: low}
sample_phase: posedge+settle
observables:
  - {name: ready_o, width: 1}
  - {name: data_o, width: 8}
directed: {seed: 0, cycles: 64}
random:
  public_seeds: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
  cycles_per_seed: 1000
  fresh_seed_count: 10
commands:
  reference_build:
    command: [./tests/build-reference, --output, "{run_dir}/reference"]
  model_build:
    command: [./tests/build-model, --output, "{run_dir}/model"]
  model_test:
    command: ["{run_dir}/model/fifo-model", --unit]
  stimulus:
    command: [./tests/gen-stimulus, --seed, "{seed}", --cycles, "{cycles}", --output, "{stimulus}"]
  reference_run:
    command: [./tests/run-reference, --build, "{run_dir}/reference", --input, "{stimulus}", --trace, "{trace}"]
  model_run:
    command: ["{run_dir}/model/fifo-model", --run-dir, "{run_dir}", --input, "{stimulus}", --trace, "{trace}"]
```

每个命令是 argv 数组，可选 `cwd` 和 `timeout_seconds`。仅允许 `{run_dir}`、`{seed}`、
`{cycles}`、`{stimulus}`、`{trace}` 占位符，不经过 shell 展开。
`model_test` 与 `model_run` 必须直接执行 `model_binary`，不能通过 simulator 或任意 wrapper。

Trace 是 JSONL；`sample` 必须从 0 连续递增，`phase` 必须匹配配置，`signals` 必须精确
包含全部 observables。值使用按声明位宽补齐的 lowercase hex：

```json
{"sample":0,"phase":"posedge+settle","signals":{"ready_o":"0x1","data_o":"0x2a"}}
```

Harness 依次执行 evidence/audit、三项 build/test、定向用例、至少 10 个公开 seeds 和至少
10 个运行时新 seeds。任一命令、stimulus 哈希或 trace 比较失败即停止。
