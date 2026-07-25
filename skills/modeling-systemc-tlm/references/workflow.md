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
  model/
  verification/report.yaml
```

Initialize:

```bash
systemc-tlm-agent init PROJECT --name NAME --top RTL_TOP \
  --docx spec.docx --xlsx registers.xlsx --rtl rtl
```

The manifest paths are relative to `PROJECT`. RTL entries accept files, glob
patterns, or directories. Directories are searched recursively for `.v` and
`.sv` files. Extraction is deterministic and records source digests and
locators. Re-run extraction whenever an input changes.

Architecture is a human/agent-authored decision artifact. Each complete claim has one or more `evidence_ids`. Use `not_applicable` only with a reason in `summary`.

Generation requires `approval.yaml`. Approval hashes the manifest, extracted facts, architecture, and conflicts. Any subsequent edit makes approval stale.

Verification levels:

1. CMake configure and C++ compile.
2. CTest model smoke/unit tests.
3. Contract-directed transaction tests.
4. RTL differential test using identical stimuli and an explicit normalization/comparison adapter.

Passing a lower level does not imply passing a higher one.
