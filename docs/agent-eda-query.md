# Agent-friendly EDA access

The repository exposes two deliberately different paths:

- `eda-query` reads existing Yosys and Verilator JSON offline and returns a
  stable `QueryResult`.
- `eda-uhdm run` executes an agent-written Python script against an existing
  Surelog UHDM database using the official `uhdm` binding.

Neither path replaces RTL or specifications as the design authority.

## Offline Yosys/Verilator queries

`eda-query` consumes:

- `BUNDLE/tools/yosys.json`
- `BUNDLE/tools/verilator.json`

It never launches an EDA process, evaluates arbitrary expressions, or accesses
the network.

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

Semantic kinds shared by both backends are `modules`, `ports`, `hierarchy`,
and `source-locations`. Yosys additionally supports `cells` and `signals`;
Verilator supports `signals` and `statements`. Unsupported combinations return
`status: unsupported`. Raw access accepts only RFC 6901-style JSON Pointer.

Every `QueryResult` contains the artifact path and SHA-256, stable
content-derived `query_id`, selectors, pagination state, warnings, and item
locators. The schema is `src/eda_query/query-result.schema.json`.

## Direct UHDM Python access

Surelog extraction preserves the native database at:

```text
PROJECT/.systemc-agent/tools/surelog-work/slpp_all/surelog.uhdm
```

`eda-uhdm` does not export this database to a repository-specific object model
and does not implement fixed `query` or `serve` commands. An agent writes the
smallest Python script needed for the current question and imports `uhdm`
directly:

```python
import os
import uhdm

serializer = uhdm.Serializer()
roots = serializer.Restore(os.environ["UHDM_DATABASE"])
if not roots:
    raise RuntimeError("UHDM database contains no design root")
design = roots[0]
iterator = uhdm.vpi_iterate(uhdm.uhdmtopModules, design)
while iterator:
    module = uhdm.vpi_scan(iterator)
    if module is None:
        break
    print(uhdm.vpi_get_str(uhdm.vpiName, module))
```

Run it in the UHDM image. Both the script and output directory must be below
the directory mounted by `--work`:

```bash
scripts/eda-run --work WORK uhdm \
  eda-uhdm run \
  /workspace/PROJECT/.systemc-agent/tools/surelog-work/slpp_all/surelog.uhdm \
  /workspace/audits/query.py \
  --output-dir /workspace/audits/query-output -- TopModule
```

The runner:

- sets `UHDM_DATABASE` to an absolute database path;
- uses the image's Python interpreter and official binding;
- enforces a timeout and a combined stdout/stderr byte limit;
- preserves raw `stdout.log` and `stderr.log` without transforming objects;
- records database/script/stream hashes, binding information, limits, timing,
  and return code in `run.json`.

Defaults are 120 seconds and 4 MiB. Override them with `--timeout` and
`--max-output-bytes`.

The copyable starter is
`skills/modeling-systemc-tlm/assets/uhdm_query_template.py`; the API usage
guide is `skills/modeling-systemc-tlm/references/uhdm-python.md`. Scripts
should inspect both `uhdmtopModules` (elaborated instances) and
`uhdmallModules` (definitions) when the question spans connectivity and
source-level behavior.

Raw UHDM output is exploration, not extractor-owned evidence. It may locate a
process, enum, assignment, or source line, but the agent must confirm the
claim against extractor-owned RTL/specification evidence. This avoids making
arbitrary script output a self-certifying evidence source.

## Production outputs

Projects with packages and generated dependencies should provide source order,
include directories, and defines in `eda_compile`. `eda-uhdm-produce` invokes
Surelog with full elaboration and leaves `surelog.uhdm` intact;
`eda-rtl-produce` independently runs Verilator and Yosys.

## Evidence bridge

Only successful, non-empty Yosys/Verilator `QueryResult` files can be promoted:

```bash
systemc-tlm-agent evidence record PROJECT \
  --result ports.json \
  --statement "TopModule exposes the elaborated request and response ports."
```

Recording revalidates the result ID and source SHA-256. Records are appended
idempotently to `.systemc-agent/query-evidence.jsonl` and participate in the
approval hash. UHDM runner logs are intentionally rejected by this bridge.

## Limits

- UHDM relations vary by object class and binding release; scripts must test
  optional constants with `getattr` and report unsupported views explicitly.
- Do not perform an unbounded whole-database recursive dump. Select a
  top/module and cap each relation.
- Parser failures and missing relations are limitations, not negative design
  evidence.
- Large image pulls/builds remain user-operated.
