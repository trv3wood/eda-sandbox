# Cycle Harness

Harness Agent 建立并冻结本契约；Model Agent 只读使用；Acceptance Agent 独立执行并追加不可见
的隐藏/metamorphic 用例。三种角色不得复用同一 agent 会话。

`verify-cycle` 使用 `cycle-harness.yaml`，不读取任务或证据文档。配置声明 source manifest、
model sources/binary、时钟复位、observables、定向/随机规模，以及以下六个 argv 命令：

- `reference_build`、`model_build`、`model_test`
- `stimulus`、`reference_run`、`model_run`

命令可使用 `{run_dir}`、`{seed}`、`{cycles}`、`{stimulus}`、`{trace}`。Reference 与 model
读取同一 stimulus，输出 JSONL：

```json
{"sample":0,"phase":"posedge+settle","signals":{"ready_o":"0x1"}}
```

Harness 严格比较 sample、phase、observable 集合、位宽和值，并检查：

- clean build、model unit/elaboration 和最终二进制不依赖 RTL simulator；
- model source 不读取 reference/trace、不调用外部进程；
- stimulus 在运行中不被修改；
- public/fresh 各至少 10×1,000 cycles，且 stimulus hash 唯一率默认不低于 90%。

这些是基础门禁。最终接受还应由协调者使用模型不可见的 generator 执行 payload、地址、
timing、ACK/NACK、stall/stretch、reset 位置扰动，以及插入 idle cycle 的时移/metamorphic
差分。公开回归通过只能称 `regression-passed`；隐藏与 metamorphic 差分也通过后才称
`cycle-equivalent`。
