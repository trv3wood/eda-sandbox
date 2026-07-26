# SystemC TLM Skill benchmark

This benchmark runs a blinded, matched A/B evaluation of the `gpt-5.6-luna` model.
Baseline and Skill arms receive the same case inputs, seeds, budgets, tools,
stage boundary, and hidden tests. The Skill arm alone may use the repository
modeling Skill. This SystemC extension is not directly comparable with the
ChipBench paper's pass@k.

## Safe preparation

```bash
scripts/benchmark-systemc-tlm prepare --work ~/Work/eda-sandbox
```

Preparation does not download or compile anything. It writes
`sources/FETCH_COMMANDS.txt`; the user runs those potentially long-lived
commands, then pins both repositories:

```bash
scripts/benchmark-systemc-tlm lock --work ~/Work/eda-sandbox
```

The lock records repository URL, license, commit, and a SHA-256 digest of the
complete Git tree listing. Populate each generated `corpus/*/*/case.json` with
its immutable input paths before executing agents.

Generate shared EDA evidence in the existing agent image before either arm:

```bash
scripts/benchmark-systemc-tlm extract --work ~/Work/eda-sandbox \
  --case ctrl --top TopModule --reference-top RefModule \
  --image localhost/eda-agent:local --execute
```

The command runs Surelog/UHDM, Verilator, and Yosys in the container. Each run
receives a neutral bundle containing only parser-native logs, JSON/UHDM output,
and a sanitized status summary. Treatment-generated `facts/`, `evidence.jsonl`,
contracts, manifests, models, and CLI command records are never staged into
either arm. Bubblewrap runs mount the neutral bundle read-only; direct-host runs
rely on the benchmark instruction not to mutate it. The LLM never receives
Podman permissions. Case manifests may list `testbench_paths`; for ChipBench,
files ending in `_test.sv` or `_tb.sv` are recognized as testbenches for
backward compatibility.

## Runs and architecture gate

Without `--execute`, `run` creates an inspectable plan only:

```bash
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --model gpt-5.6-luna --arm baseline --trials 3
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --model gpt-5.6-luna --arm skill --trials 3
```

Add `--execute` to invoke `codex exec`. The architecture phase persists its
prompt, command, timestamps, commit lock, exit status, and JSONL. Before the
implementation phase, put `architecture-review.json` in each run directory:

Claude Code uses the same corpus, evidence, arms, and gate:

```bash
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --runner claude --model sonnet --arm baseline --case ctrl --trials 1
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --runner claude --model sonnet --arm skill --case ctrl --trials 1
```

Add `--execute` after inspecting the plans. Claude stays on the host so its
OAuth session remains usable; only deterministic EDA extraction runs in the
container. Runner isolation defaults to `none` so Claude Code can retain custom
model-provider configuration and host EDA tooling. Such runs are prompt-blinded,
not filesystem-blinded, and `run.json` records that limitation. Use
`--isolation bubblewrap-selective` only when the runner configuration is known
to work inside the restricted filesystem.

Claude baseline runs additionally use safe mode, disable slash commands, omit
`Skill`, `Agent`, and `Task` from the tool set, and load a per-run deny settings
file. This prevents treatment Skill/role invocation even when those
customizations are installed in the host Claude profile. With `--isolation
none`, Bash can still read host-visible files, so this is capability isolation
rather than a filesystem confidentiality boundary.

```json
{
  "reviews": [
    {"reviewer": "blind-A", "decision": "approve"},
    {"reviewer": "blind-B", "decision": "approve"}
  ]
}
```

If the first two reviewers disagree, append the third adjudicator's decision.
Implementation proceeds only if both initial reviewers approve, or if the
third adjudicator resolves a disagreement with `approve`:

```bash
scripts/benchmark-systemc-tlm run --work ~/Work/eda-sandbox \
  --model gpt-5.6-luna --arm skill --trials 3 --stage implement --execute
```

The oracle directory must never appear in an agent prompt or working input.
Reviewers create `score.json` in each run directory with `points` and
`possible` for `evidence`, `architecture`, `implementation`, and `functional`;
efficiency is reported separately. Scores also carry `gate_violations` and
`fabricated_evidence`.

```bash
scripts/benchmark-systemc-tlm score --work ~/Work/eda-sandbox
scripts/benchmark-systemc-tlm report --work ~/Work/eda-sandbox
```

Full ChipBench/OpenTitan downloads, container builds, SCC compilation, and
complete regression remain user-operated long-running commands.

## Architecture smoke result (2026-07-26)

One `ctrl` case was run once per arm through Claude Code using
`deepseek-v4-flash[1M]`. This was a harness and architecture-stage smoke test,
not a completed Pilot or a statistically meaningful Skill score.

Validated harness properties:

- Both arms used the same model and byte-identical neutral Surelog, Verilator,
  Yosys, and status artifacts.
- Baseline started with no custom skills and only the built-in
  `claude`, `Explore`, `general-purpose`, and `Plan` agents. Its tool set
  contained no `Skill`, `Agent`, or `Task`, and its JSONL showed no treatment
  invocation.
- The Skill arm received the repository Skill and role adapters. It produced
  the canonical eight-category architecture YAML, registered 36 evidence
  records with no unknown contract evidence IDs, passed
  `architect --validate`, and stopped at the human approval gate.
- Baseline produced a useful independent architecture, but used a different
  eight-category schema and selected an RTL interpretation for a reported JALR
  ambiguity without human adjudication. Its final `ARCHITECT_COMPLETE` status
  was inconsistent with the unresolved entry in `conflicts.yaml`.

Observed resource use:

| Arm | Wall time | Input tokens | Output tokens | Reported cost |
|---|---:|---:|---:|---:|
| Baseline | about 105 s | 65,810 | 13,393 | USD 0.87 |
| Skill | about 197 s | 81,541 | 23,588 | USD 2.15 |

These efficiency numbers are not accepted benchmark measurements. The two
runs overlapped for about 82 seconds because they were launched from separate
terminals, so provider contention, cache behavior, and local I/O were not
controlled. No identical maximum cost, wall-clock timeout, or turn ceiling was
enforced.

Further limitations:

- This is one case and one trial, with no blind reviewer scores or hidden
  functional oracle.
- Direct-host mode provides capability isolation, not filesystem
  confidentiality; baseline Bash can theoretically read other host-visible
  files even though the run showed no such access.
- The Skill result still contained review findings: claiming complete RV32I
  compatibility was broader than the supplied evidence, JALR's omitted ALUOp
  grouping should be represented as an ambiguity rather than unconditional
  consistency, and X/Z equivalence language was stronger than synthesis
  evidence supports.
- The shared neutral EDA bundle evaluates evidence interpretation and
  architecture construction. It does not measure the Skill's ability to select,
  configure, and execute EDA tools end to end.

Therefore this run supports a preliminary qualitative signal that the Skill
improves contract schema compliance, evidence traceability, and approval-gate
behavior. It does not establish the Pilot's required score improvement.
Before formal trials, both arms must receive the same explicit delivery schema,
run sequentially in randomized order, and share identical enforced cost/time
ceilings. The evidence-extraction and architecture evaluations should be
reported as separate stages.
