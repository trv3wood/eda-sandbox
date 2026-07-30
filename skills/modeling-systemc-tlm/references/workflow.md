# Artifact Workflow

The project directory is the unit of work.

```text
manifest.yaml
.systemc-agent/
  graph/
    manifest.json
    document_tree.json
    text_units.jsonl
    spec_{entities,relationships}.jsonl
    rtl_{entities,relationships}.jsonl
    cross_source_relationships.jsonl
    {entities,relationships}.jsonl
    store/{entities,relationships,text_units}.parquet
    index/{entities,chunks}.faiss
  contracts/architecture.yaml
  contracts/conflicts.yaml
  contracts/approval.yaml
  contracts/testbench/{testbench.yaml,include/,tests/}
  model/
  verification/report.json
```

Initialize:

```bash
systemc-tlm-agent init PROJECT --name NAME --top RTL_TOP \
  --reference-top GOLDEN_TOP --docx spec.docx --xlsx registers.xlsx \
  [--rtl rtl] [--tb testbench.sv]
```

The manifest paths are relative to `PROJECT`. RTL entries accept files, glob
patterns, or directories. Directories are searched recursively for `.v`,
`.sv`, and `.svp` files. `target_top` is the DUT/model to generate;
`reference_top` is an
existing golden RTL module used for structural EDA. Testbench inputs are parsed
by the configured EDA backend. RTL may
be omitted when it is not yet available. Extraction then continues with the
available documents/register maps, records RTL as a missing input, and skips
structural EDA tools. Extraction is deterministic and records source digests
and locators. Re-run extraction whenever an input changes.

With RTL inputs, `extract --skip-tools` creates source-located document units
and a pending graph manifest. Text-unit IDs are valid contract evidence.
The standard producer flow uses VCS elaboration and the packaged zero-time VPI
exporter, then verifies the requested top, source locations and artifact
digests. Legacy manifests may explicitly select the validated Surelog/UHDM
flow. The Spec producer is optional and runs only when
`graph.spec_extraction.enabled` is true. When enabled, it uses a fixed JSON
Schema and rejects output without exact source spans. There is no RTL text or
regular-expression fallback.
Architecture validation and approval require a ready canonical graph.

For industrial compile flows, prefer ordered `eda_compile.filelists`. Top-level
filelists are passed verbatim to the EDA backend with `-f`; recursively parsed
filelist and RTL dependencies are used only for digests and source mapping.
Additional `eda_compile.sources` are appended after all top-level filelists.
The backend runs from `eda_compile.working_directory` (the project root by
default), preserving native `-f` versus `-F` relative-path semantics.

Architecture is a human/agent-authored decision artifact. Each complete claim
has one or more `evidence_ids` resolving to source-backed graph entities or
deterministic text units.
Missing RTL is unresolved evidence, not
`not_applicable`; an empty model partition continues to block approval and
generation. Use `not_applicable` only with a reason in `summary`.

Generation requires `approval.yaml`. Approval hashes the manifest, canonical
graph JSON/JSONL, current input digests, architecture, conflicts, and every
Architect-owned contract-testbench file. Parquet and FAISS indexes are
rebuildable and are not approval inputs.

Verification levels:

1. CMake configure and C++ compile.
2. CTest model smoke/unit tests.
3. Contract-directed transaction tests.
4. RTL differential test using identical stimuli and an explicit normalization/comparison adapter.

Passing a lower level does not imply passing a higher one.
