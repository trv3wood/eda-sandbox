# RTL Backend Workflow

The existing project directory and `manifest.yaml` remain the unit of work. TLM artifacts and commands remain compatible.

```text
.systemc-agent/
  graph/
  contracts/
    rtl-handoff.yaml
    rtl-conflicts.yaml
    rtl-approval.yaml
    rtl-checkpoint.yaml
    rtl-testbench.yaml        # optional existing-test registry
  rtl/
    source-index.jsonl
    baseline/
    worktree/
    generation.yaml
    edits.json
    changes.diff
    verification.json
```

Typical sequence:

```bash
scripts/systemverilog-agent init PROJECT --name NAME --top TOP \
  --docx spec.docx --xlsx registers.xlsx --rtl rtl
scripts/systemverilog-agent extract PROJECT --skip-tools
# Complete the configured canonical RTL producer and graph finalization first.
uv sync --extra rtl
scripts/systemverilog-agent architect PROJECT --mode patch
# Complete rtl-handoff.yaml and resolve rtl-conflicts.yaml.
scripts/systemverilog-agent architect PROJECT --validate
# 可选：正式评审或 review_gate=required 时执行 approve。
# scripts/systemverilog-agent approve PROJECT --approver NAME
scripts/systemverilog-agent generate PROJECT
scripts/systemverilog-agent apply-edits PROJECT edits.json
scripts/systemverilog-agent verify PROJECT
```

默认 `review_gate: optional`。`generate` 自动创建内容 checkpoint，哈希 project manifest、canonical graph/current inputs、source index/current source digests、RTL handoff、conflicts 和 test manifest。后续变化会阻断 edit/verify。设置 `review_gate: required` 时必须先有具名 approval。

`generate` refuses to overwrite an existing baseline or worktree. Preserve or explicitly remove the prior generated tree before starting a new checkpointed generation.

The LLM edit protocol is JSON:

```json
{
  "edits": [
    {
      "target_id": "syn-... or todo-RTL-FUNC-001",
      "base_sha256": "...",
      "replacement_text": "always_comb begin ... end",
      "requirement_ids": ["RTL-FUNC-001"]
    }
  ]
}
```

Edits are byte-range replacements applied from the end of each file toward the beginning. Duplicate targets, overlapping ranges, stale digests, unsafe paths, unknown requirements, or changes outside declared files fail closed.
