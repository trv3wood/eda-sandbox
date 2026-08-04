# RTL Handoff Contract

Use `schema_version: 1` and `status: complete` before approval.

Required sections:

- `policy`: mode, `1800-2017` or `1800-2023`, and a non-empty unsupported list.
- `target`: canonical top and evidence IDs.
- `module_contracts`: exact source-spelled imports, parameter/port/signal declarations, and optional hierarchy instances.
- `requirements`: stable `RTL-*` IDs, precise statements, evidence IDs, and optional target module.
- `edit_targets`: patch-only mappings from indexed syntax node IDs to requirements.
- `structure_expectations`: default `preserve` for patch or `declared-only` for new scaffolds, plus explicit allowed deltas.
- `acceptance_scenarios`: evidence-backed Given/When/Then records and existing test IDs; the list may be empty, in which case simulation is blocked.
- `verification`: argv arrays for lint/compile and named existing simulation tests. Commands execute without a shell in the isolated worktree.

Declaration records use exact SystemVerilog text:

```yaml
module_contracts:
  - name: image_ctrl
    evidence_ids: [ent-module-or-txt-unit]
    imports: ["import image_pkg::*;"]
    parameters:
      - {declaration: "parameter int DATA_WIDTH = 32"}
    ports:
      - {declaration: "input logic clk_i"}
      - {declaration: "output logic [DATA_WIDTH-1:0] data_o"}
    signals:
      - {declaration: "logic done"}
    instances:
      - module: image_worker
        name: u_worker
        parameter_bindings: [{name: WIDTH, expression: DATA_WIDTH}]
        connections: [{name: done_o, expression: done}]
```

Do not derive source types from elaborated bit widths when typedefs, interfaces, unpacked dimensions, signedness, or parameter expressions are unavailable. Leave the handoff unresolved instead.

