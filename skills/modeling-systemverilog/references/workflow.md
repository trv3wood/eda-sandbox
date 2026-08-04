# RTL Backend Workflow

The existing project directory and `manifest.yaml` remain the unit of work. TLM artifacts and commands remain compatible.

```text
.systemc-agent/
  graph/
  contracts/
    rtl-handoff.yaml
    rtl-conflicts.yaml
    rtl-approval.yaml
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
scripts/systemverilog-agent approve PROJECT --approver NAME
scripts/systemverilog-agent generate PROJECT
scripts/systemverilog-agent apply-edits PROJECT edits.json
scripts/systemverilog-agent verify PROJECT
```

Approval hashes the project manifest, canonical graph and current inputs, source index and indexed source-file digests, RTL handoff, RTL conflicts, and optional test manifest. A change to any of them blocks generation and edit application.

`generate` refuses to overwrite an existing baseline or worktree. Preserve or explicitly remove the prior generated tree before starting a new approved generation.

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

Edits are byte-range replacements applied from the end of each file toward the beginning. Duplicate targets, overlapping ranges, stale digests, unsafe paths, unknown requirements, or changes outside approved files fail closed.

