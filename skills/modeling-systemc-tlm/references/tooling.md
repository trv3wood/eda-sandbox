# Tool and Backend Policy

Use the local `uv` environment for workflow and Spec production. Route EDA and
SystemC work through the role-specific environments with the repository
wrapper:

Before running the Spec producer, install its local dependencies once:

```bash
uv sync --extra graph
```

```bash
scripts/eda-run --work WORK agent \
  systemc-tlm-agent extract /workspace/PROJECT --skip-tools
# Optional, only when graph.spec_extraction.enabled is true:
scripts/eda-run --work WORK agent eda-spec-produce /workspace/PROJECT
scripts/eda-run --work WORK agent systemc-tlm-agent status /workspace/PROJECT
scripts/eda-run --work WORK vcs eda-rtl-produce /workspace/PROJECT
scripts/eda-run --work WORK rtl verilator --version
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
- `vcs`: local研发网 VCS/VPI graph production; it inherits the active license environment.
- `uhdm`: Surelog, the UHDM Python binding, and the thin `eda-uhdm` runner.
- `rtl`: RTL simulation and differential-test tooling.
- `scc`: SystemC/minres-SCC compilation and verification.
- `rocky`: Rocky Linux 8 compatibility checks.

Structural extraction uses:

- VCS/VPI as the default source of elaborated SystemVerilog structure.
- Surelog/UHDM as an explicit compatibility backend for legacy projects.

The VCS producer always runs this fixed sequence:

1. compile the packaged C/VPI exporter against `$VCS_HOME/include`
2. run VCS compilation/elaboration for `reference_top`
3. run `simv` and export structure from `cbStartOfSimulation`
4. validate the unique top, input and artifact digests, and structure schema

The compatibility UHDM producer always runs this fixed sequence:

1. `surelog ... -parse -elabuhdm`
2. validate the non-empty `surelog.uhdm` and Surelog's zero-error summary
3. `uhdm-lint surelog.uhdm`
4. `uhdm-hier surelog.uhdm --line`
5. the official Python VPI exporter

The optional Spec producer uses a fixed JSON Schema through an OpenAI-compatible API.
Every entity and relationship must cite an exact span in a known text unit.
Requests are deterministically batched and cached by input, prompt/schema,
model, and parameters.

Do not add Surelog's `-d uhdm` debug dump to the compatibility producer: it emits
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
office-network host. Check the applicable研发网 `eda-run` role first. There is
no RTL regex fallback: a failed or unavailable configured EDA gate leaves the graph pending/failed
and blocks architecture approval. Additional UHDM script output is
exploratory; follow its source locations back to canonical RTL graph entities.
DuckDB/Parquet, NetworkX, and FAISS are rebuildable query indexes and never
create facts.

Keep UHDM parser failures visible. Large image pulls/builds and minres-SCC
builds may block for a long time; give the user the exact command to run
instead of launching them automatically.
