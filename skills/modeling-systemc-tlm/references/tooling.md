# Tool and Backend Policy

Use the local `uv` environment for workflow and Spec production. Route only
EDA and SystemC work through the role-specific images with the repository
wrapper:

Before running the Spec producer, install its local dependencies once:

```bash
uv sync --extra graph
```

```bash
scripts/eda-run --work WORK agent \
  systemc-tlm-agent extract /workspace/PROJECT --skip-tools
scripts/eda-run --work WORK agent eda-spec-produce /workspace/PROJECT
scripts/eda-run --work WORK agent systemc-tlm-agent status /workspace/PROJECT
scripts/eda-run --work WORK uhdm eda-uhdm-produce /workspace/PROJECT
scripts/eda-run --work WORK agent \
  systemc-tlm-agent tools finalize /workspace/PROJECT
scripts/eda-run --work WORK agent \
  systemc-tlm-agent graph build /workspace/PROJECT
scripts/eda-run --work WORK scc \
  systemc-tlm-agent verify /workspace/PROJECT --backend auto
```

`PROJECT` is relative to the mounted `WORK`; the wrapper maps `WORK` to
`/workspace`. The roles are:

- `agent`: local `uv` workflow and graph/spec tooling; it is not a container.
- `uhdm`: Surelog, the UHDM Python binding, and the thin `eda-uhdm` runner.
- `scc`: SystemC/minres-SCC compilation and verification.
- `rocky`: Rocky Linux 8 compatibility checks.

Structural extraction uses:

- Surelog/UHDM as the mandatory source of elaborated SystemVerilog structure.

The UHDM producer always runs this fixed sequence:

1. `surelog ... -parse -elabuhdm`
2. validate the non-empty `surelog.uhdm` and Surelog's zero-error summary
3. `uhdm-lint surelog.uhdm`
4. `uhdm-hier surelog.uhdm --line`
5. the official Python VPI exporter

The Spec producer uses a fixed JSON Schema through an OpenAI-compatible API.
Every entity and relationship must cite an exact span in a known text unit.
Requests are deterministically batched and cached by input, prompt/schema,
model, and parameters.

Do not add Surelog's `-d uhdm` debug dump to the producer invocation: it emits
the complete UHDM tree to stdout and can make logs hundreds of megabytes.
Do not trust exit code alone: UHDM 1.84 command-line tools return success for
some usage and missing-file paths. The producer also requires the documented
zero-error Surelog summary and the requested top in `uhdm-hier` output.

For an existing database or extraction bundle, inspect it before producing new
artifacts:

```bash
scripts/eda-run --work WORK uhdm \
  eda-uhdm run DATABASE QUERY.py --output-dir OUTPUT -- TOP
```

Read `uhdm-python.md` before writing `QUERY.py`. The script imports the
official binding and selects the VPI relations needed by the current modeling
question. `eda-uhdm` only sets `UHDM_DATABASE`, bounds runtime/output, and
preserves raw streams plus provenance. It deliberately has no fixed
export/query/server protocol. Use the thin runner for focused exploratory
questions, then map results back to source-located canonical graph entities.

Do not declare an EDA tool unavailable merely because it is absent on the
host. Check the applicable `eda-run` role first. There is no RTL regex
fallback: a failed or unavailable UHDM gate leaves the graph pending/failed
and blocks architecture approval. Additional UHDM script output is
exploratory; follow its source locations back to canonical RTL graph entities.
DuckDB/Parquet, NetworkX, and FAISS are rebuildable query indexes and never
create facts.

Keep UHDM parser failures visible. Large image pulls/builds and minres-SCC
builds may block for a long time; give the user the exact command to run
instead of launching them automatically.
