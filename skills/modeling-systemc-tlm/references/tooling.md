# Tool and Backend Policy

Use local tools when they are available. Otherwise route commands through the
small role-specific images with the repository wrapper:

```bash
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
- `uhdm`: Surelog, the UHDM Python binding, `uhdm-export`, and `eda-uhdm`.
- `rtl`: Verilator and Yosys.
- `scc`: SystemC/minres-SCC compilation and verification.
- `rocky`: Rocky Linux 8 compatibility checks.

Structural extraction uses:

- Surelog/UHDM for elaborated SystemVerilog structure when supported.
- Verilator JSON for an independent parsed hierarchy.
- Yosys JSON for synthesizable hierarchy and connectivity.

For an existing database or extraction bundle, query it before producing new
artifacts:

```bash
scripts/eda-run --work WORK uhdm \
  eda-uhdm query DATABASE --kind ports --module TOP
scripts/eda-run --work WORK agent eda-query catalog BUNDLE
scripts/eda-run --work WORK agent \
  eda-query query BUNDLE --backend uhdm --kind fsm-candidates --module TOP
```

Prefer `eda-uhdm serve DATABASE` for several live queries in one agent loop;
it restores the database once. Prefer `eda-query` for deterministic, cheap,
hashable queries against `BUNDLE/tools/*.json`.

Do not declare an EDA tool unavailable merely because it is absent on the
host. Check the applicable `eda-run` role first. Regex RTL extraction is only
a fallback and evidence locator: do not substitute it for an available UHDM,
Verilator, or Yosys view. Text and Markdown specifications should be read
directly; they do not require an importer.

Keep parser failures visible and continue with the successful independent
views. Never infer that one backend passed because another did. Large image
pulls/builds and minres-SCC builds may block for a long time; give the user the
exact command to run instead of launching them automatically.
