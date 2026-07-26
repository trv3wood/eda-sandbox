# Agent-friendly EDA query layer

`eda-query` is a small, offline read layer over EDA artifacts that were already
produced by the extraction/container workflow. It gives an agent stable
semantic queries without allowing the query process to launch tools, access the
network, or evaluate arbitrary expressions.

## Boundary

The offline reader consumes:

- `BUNDLE/tools/uhdm.json`
- `BUNDLE/tools/yosys.json`
- `BUNDLE/tools/verilator.json`

Surelog logs remain ordinary text evidence. UHDM, Yosys, and Verilator results
are reported independently, so a missing view is visible rather than silently
reconstructed from another backend.

The layer does not replace RTL or specifications as design authority. It makes
elaborated hierarchy, ports, cells, signals, AST nodes, and source locations
cheap to inspect and cite.

`eda-uhdm` is the live companion in the dedicated UHDM image. It restores the
Surelog database through the official Python binding:

```bash
eda-uhdm export tools/surelog-work/slpp_all/surelog.uhdm \
  --output tools/uhdm.json --source-root PROJECT
eda-uhdm query tools/surelog-work/slpp_all/surelog.uhdm \
  --kind ports --module dma
eda-uhdm serve tools/surelog-work/slpp_all/surelog.uhdm
```

`serve` restores once and accepts one JSON request per input line, which avoids
paying deserialization cost on every agent-loop query. `export` remains the
deterministic, hashable cache and benchmark evidence format.

## CLI

```bash
eda-query catalog BUNDLE

eda-query query BUNDLE \
  --backend yosys \
  --kind ports \
  --module TopModule \
  --limit 100 \
  --output ports.json

eda-query query BUNDLE \
  --backend verilator \
  --kind statements \
  --module TopModule

eda-query raw BUNDLE \
  --backend yosys \
  --pointer /modules/TopModule/cells
```

Semantic kinds shared by both backends are `modules`, `ports`, `hierarchy`, and
`source-locations`. Yosys additionally supports `cells` and `signals`;
Verilator supports `signals` and `statements`. Unsupported combinations return
`status: unsupported`. Raw access accepts only RFC 6901-style JSON Pointer.

UHDM is the semantic backend for larger SystemVerilog designs. It supports
`modules`, `packages`, `ports`, `parameters`, `hierarchy`, `types`, `enums`,
`variables`, `processes`, `assignments`, `cases`, `fsm-candidates`, and
`source-locations`. An FSM result is deliberately a candidate: contracts must
still confirm transitions and exceptional behavior against RTL and prose.

Projects with packages and generated dependencies should provide an explicit
compile manifest:

```bash
systemc-tlm-agent init PROJECT --name dma --top dma \
  --rtl rtl/dma.sv \
  --eda-source rtl/top_pkg.sv \
  --eda-source rtl/tlul_pkg.sv \
  --eda-source rtl/dma_pkg.sv \
  --eda-source rtl/dma.sv \
  --eda-include-dir rtl \
  --eda-define SYNTHESIS
```

The source order is preserved. The `eda-uhdm-produce` command invokes Surelog
with full UHDM elaboration and uses the Python binding to create
`tools/uhdm.json`. `eda-rtl-produce` independently runs Verilator and Yosys.
`systemc-tlm-agent tools finalize PROJECT` merges their status records.
Dependency resolution and downloads must happen before extraction.

Every `QueryResult` contains the exact artifact path and SHA-256, stable
content-derived `query_id`, selectors, pagination state, warnings, and item
locators. The packaged schema is
`src/eda_query/query-result.schema.json`. `--output` uses an atomic replacement
so an interrupted query does not leave a partial result.

## Evidence bridge

A query is read-only until an agent explicitly promotes its interpretation:

```bash
systemc-tlm-agent evidence record PROJECT \
  --result ports.json \
  --statement "TopModule exposes the elaborated request and response ports."

systemc-tlm-agent evidence list PROJECT
```

Recording revalidates the QueryResult ID and current source SHA-256. Successful
records are appended idempotently to
`.systemc-agent/query-evidence.jsonl`; extractor-owned
`.systemc-agent/evidence.jsonl` is not rewritten. Contract validation accepts
IDs from both stores. Both stores are included in the approval payload, so
adding or changing query evidence invalidates an earlier architecture approval.

## Python interface

```python
from pathlib import Path
from eda_query import query_bundle, validate_result

result = query_bundle(
    Path(bundle),
    backend="yosys",
    kind="hierarchy",
    selectors={"module": "TopModule"},
)
validate_result(result, verify_source=True)
```

The offline `eda_query` package never invokes subprocesses. Live database
restore is isolated in `eda-uhdm`; producer commands own tool execution.
