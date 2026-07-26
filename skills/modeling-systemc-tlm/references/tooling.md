# Tool and Backend Policy

Use local execution when SystemC/minres-SCC and EDA tools are already available. Otherwise use:

```bash
podman compose run --rm eda-agent \
  systemc-tlm-agent status /workspace/PROJECT
```

Structural extraction uses:

- Surelog/UHDM for elaborated SystemVerilog structure when supported.
- Verilator JSON for an independent parsed hierarchy.
- Yosys JSON for synthesizable hierarchy and connectivity.

Regex RTL extraction remains a fallback and evidence locator, not a full SystemVerilog parser.

The `eda-agent` image extends the cached minres-SCC image with document and schema Python packages. Building minres-SCC can take a long time; ask the user to run `podman compose build eda-agent` when the cached minres-SCC stages are unavailable.
