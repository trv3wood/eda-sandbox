# Tool and Backend Policy

Use local tools when they are available. Otherwise route commands through the
small role-specific images with the repository wrapper:

```bash
scripts/eda-run --work WORK agent \
  systemc-tlm-agent extract /workspace/PROJECT --skip-tools
scripts/eda-run --work WORK agent systemc-tlm-agent status /workspace/PROJECT
scripts/eda-run --work WORK uhdm eda-uhdm-produce /workspace/PROJECT
scripts/eda-run --work WORK rtl eda-rtl-produce /workspace/PROJECT
scripts/eda-run --work WORK agent \
  systemc-tlm-agent tools finalize /workspace/PROJECT
scripts/eda-run --work WORK scc \
  systemc-tlm-agent verify /workspace/PROJECT --backend auto
```

`PROJECT` is relative to the mounted `WORK`; the wrapper maps `WORK` to
`/workspace`. The roles are:

- `agent`: workflow CLI and offline `eda-query`.
- `uhdm`: Surelog, the UHDM Python binding, and the thin `eda-uhdm` runner.
- `rtl`: Verilator and Yosys.
- `scc`: SystemC/minres-SCC compilation and verification.
- `rocky`: Rocky Linux 8 compatibility checks.

Structural extraction uses:

- Surelog/UHDM as the mandatory source of elaborated SystemVerilog structure.
- Verilator JSON for an independent parsed hierarchy.
- Yosys JSON for synthesizable hierarchy and connectivity.

The UHDM producer always runs this fixed sequence:

1. `surelog ... -parse -elabuhdm -d uhdm`
2. `uhdm-dump --elab surelog.uhdm`
3. `uhdm-lint surelog.uhdm`
4. `uhdm-hier surelog.uhdm --line`
5. the official Python VPI exporter

Do not trust exit code alone: UHDM 1.84 command-line tools return success for
some usage and missing-file paths. The producer also requires the documented
restore/elaboration markers and the requested top in the hierarchy output.

For an existing database or extraction bundle, inspect it before producing new
artifacts:

```bash
scripts/eda-run --work WORK uhdm \
  eda-uhdm run DATABASE QUERY.py --output-dir OUTPUT -- TOP
scripts/eda-run --work WORK agent eda-query catalog BUNDLE
scripts/eda-run --work WORK agent \
  eda-query query BUNDLE --backend yosys --kind hierarchy --module TOP
```

Read `uhdm-python.md` before writing `QUERY.py`. The script imports the
official binding and selects the VPI relations needed by the current modeling
question. `eda-uhdm` only sets `UHDM_DATABASE`, bounds runtime/output, and
preserves raw streams plus provenance. It deliberately has no fixed
export/query/server protocol. Prefer `eda-query` for deterministic, cheap,
hashable queries against Yosys and Verilator JSON.

Do not declare an EDA tool unavailable merely because it is absent on the
host. Check the applicable `eda-run` role first. There is no RTL regex
fallback: a failed or unavailable UHDM gate leaves RTL facts pending/failed
and blocks architecture approval. Additional UHDM script output is
exploratory; follow its source locations back to RTL evidence. Text and
Markdown specifications should be read directly; they do not require an
importer.

Keep parser failures visible and continue with the successful independent
views. Never infer that one backend passed because another did. Large image
pulls/builds and minres-SCC builds may block for a long time; give the user the
exact command to run instead of launching them automatically.
