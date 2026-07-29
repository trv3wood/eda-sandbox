---
name: modeling-systemc-tlm
description: Build evidence-grounded, loosely timed SystemC TLM-2.0 IP models from DOCX specifications, XLSX register maps, and SystemVerilog RTL. Use for medium-size IP architecture extraction, eight-category modeling contracts, minres-SCC-oriented model generation, and compile/differential verification.
---

# SystemC TLM Modeling

Use the deterministic CLI for artifact production. Use agent reasoning to interpret evidence, resolve ambiguity with the user, and complete contracts; never invent design facts.

## Workflow

1. Read `references/workflow.md`, then inspect the project manifest and current status.
2. Run `scripts/systemc-tlm-agent extract PROJECT --skip-tools`, then run the
   Spec, UHDM, and RTL producers and `tools finalize` as described in
   `references/tooling.md`. The canonical graph remains pending until all
   required producers and graph gates pass.
3. Assign source-backed graph entity IDs to claims. Surelog/UHDM supplies the
   canonical RTL structure; schema-constrained Spec extraction supplies
   exact-span-grounded semantic entities. UHDM is the canonical RTL structure
   source; exploratory queries do not create additional truth stores.
4. Run `scripts/systemc-tlm-agent architect PROJECT`.
5. Complete all eight contract categories according to `references/contracts.md`. Record contradictions in `contracts/conflicts.yaml`.
6. Write executable C++ black-box contract tests under `contracts/testbench/`.
   Give every acceptance scenario a stable ID and exact `test_ids` coverage.
7. Stop if any category is unresolved, any contract test is missing, or any conflict is open. Ask for a decision with the competing evidence IDs.
8. Validate with `scripts/systemc-tlm-agent architect PROJECT --validate`.
9. Require explicit human approval: `scripts/systemc-tlm-agent approve PROJECT --approver NAME`.
10. Generate only while the approval hash remains valid: `scripts/systemc-tlm-agent generate PROJECT`.
11. Verify locally or in Podman: `scripts/systemc-tlm-agent verify PROJECT --backend auto`.

`run` advances the same pipeline and intentionally stops at architecture and approval gates.

## Agent Roles

Follow `references/roles.md`. Keep Planner, Evidence Extractor, Architect, Implementer, and Verifier outputs separate. The Architect owns contract completeness; the Implementer may not reinterpret unresolved contracts.

## Modeling Policy

- Treat Spec and RTL as ground truth sources. Preserve source location, digest,
  and graph entity ID for every extracted claim.
- Do not use regular-expression RTL extraction. With RTL inputs, a validated
  UHDM elaboration and UHDM-derived structure are mandatory.
- Model at loosely timed TLM-2.0 transaction granularity unless the approved contract explicitly requires finer timing.
- Isolate minres-SCC usage behind adapters so the functional model remains testable with standard SystemC.
- Represent latency, queues, arbitration, backpressure, errors, register side effects, interrupts, and completion conditions explicitly when supported by evidence.
- A changed input, fact, contract, contract-testbench file, or conflict file invalidates approval and blocks regeneration.
- Treat Architect-owned contract tests as immutable implementation requirements; never weaken them to make a model pass.
- Report verification limitations. Do not label a model RTL-equivalent when no shared-stimulus comparator exists.

## Reusable SystemC Components

Before writing infrastructure already offered by a maintained library, inspect
[Minres/SystemC-Components](https://github.com/Minres/SystemC-Components).
It provides TLM register/target/router utilities, transaction tracing, and
several bus-protocol components. Reuse such components only after confirming
that their protocol variant and abstraction level match the evidence-backed
contract. In particular, do not equate a listed TileLink-UH adapter with an
OpenTitan TL-UL interface, and do not infer an I2C behavioral component merely
from the repository's general SystemC/TLM support.

## Tool Routing

Read `references/tooling.md` before choosing local or container execution. Do not launch large image builds or minres-SCC recompiles automatically; provide the exact command for the user to run.
An absent host executable is not a tool failure until the corresponding
`scripts/eda-run` role has also been checked. Reuse an existing UHDM database
or JSON bundle before regenerating it.

## EDA Query Recipes

Treat exploratory UHDM query failures and missing artifacts as limitations to
report; the thin runner never defines canonical graph facts.

The fixed producer flow is `surelog -parse -elabuhdm` (which emits the binary
`.uhdm`),
`uhdm-lint`, `uhdm-hier --line`, then the official Python VPI exporter.
Only after those gates pass may `tools finalize` publish RTL graph entities
and relationships.

For an additional question against a validated
`tools/surelog-work/slpp_all/surelog.uhdm`, write a small Python query against
the official `uhdm` binding and execute it with the thin runner:

```bash
mkdir -p WORK/audits/uhdm-query
cp skills/modeling-systemc-tlm/assets/uhdm_query_template.py \
  WORK/audits/uhdm-query/query.py
scripts/eda-run --work WORK uhdm \
  eda-uhdm run \
  /workspace/PROJECT/.systemc-agent/tools/surelog-work/slpp_all/surelog.uhdm \
  /workspace/audits/uhdm-query/query.py \
  --output-dir /workspace/audits/uhdm-query/output -- TOP
```

The runner preserves raw stdout/stderr and provenance; it does not define a
query language or reinterpret UHDM objects. UHDM output is exploratory. Use
its source locations to return to canonical graph entities and cite those
source-backed entity IDs in contracts.
