# Artifact Workflow

The project directory is the unit of work.

```text
manifest.yaml
.systemc-agent/
  facts/{documents,registers,rtl,summary}.json
  evidence.jsonl
  contracts/architecture.yaml
  contracts/conflicts.yaml
  contracts/approval.yaml
  contracts/testbench/{testbench.yaml,include/,tests/}
  model/
  verification/report.yaml
```

Initialize:

```bash
systemc-tlm-agent init PROJECT --name NAME --top RTL_TOP \
  --reference-top GOLDEN_TOP --docx spec.docx --xlsx registers.xlsx \
  [--rtl rtl] [--tb testbench.sv]
```

The manifest paths are relative to `PROJECT`. RTL entries accept files, glob
patterns, or directories. Directories are searched recursively for `.v` and
`.sv` files. `target_top` is the DUT/model to generate; `reference_top` is an
existing golden RTL module used for structural EDA. Testbench inputs are parsed
by Surelog but excluded from Verilator/Yosys synthesis-oriented views. RTL may
be omitted when it is not yet available. Extraction then continues with the
available documents/register maps, records RTL as a missing input, and skips
structural EDA tools. Extraction is deterministic and records source digests
and locators. Re-run extraction whenever an input changes.

With RTL inputs, `extract --skip-tools` creates a pending RTL inventory only.
The standard producer flow must restore and elaborate the UHDM database with
the generated binary `.uhdm`, lint it, verify the requested top through
`uhdm-hier --line`, and export structure through the official UHDM Python
binding. There is no text or regular-expression fallback. Architecture
validation and approval require ready UHDM facts.

Architecture is a human/agent-authored decision artifact. Each complete claim
has one or more `evidence_ids`. Missing RTL is unresolved evidence, not
`not_applicable`; an empty model partition continues to block approval and
generation. Use `not_applicable` only with a reason in `summary`.

Generation requires `approval.yaml`. Approval hashes the manifest, extracted
facts, architecture, conflicts, and every Architect-owned contract-testbench
file. Any subsequent edit makes approval stale.

Verification levels:

1. CMake configure and C++ compile.
2. CTest model smoke/unit tests.
3. Contract-directed transaction tests.
4. RTL differential test using identical stimuli and an explicit normalization/comparison adapter.

Passing a lower level does not imply passing a higher one.
