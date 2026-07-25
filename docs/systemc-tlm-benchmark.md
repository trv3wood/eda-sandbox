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
