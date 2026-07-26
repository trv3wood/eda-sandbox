---
name: modeling-systemc-tlm
description: Build evidence-grounded, loosely timed SystemC TLM-2.0 IP models from DOCX specifications, XLSX register maps, and SystemVerilog RTL. Use for medium-size IP architecture extraction, eight-category modeling contracts, minres-SCC-oriented model generation, and compile/differential verification.
---

# SystemC TLM Modeling

Use the deterministic CLI for artifact production. Use agent reasoning to interpret evidence, resolve ambiguity with the user, and complete contracts; never invent design facts.

## Workflow

1. Read `references/workflow.md`, then inspect the project manifest and current status.
2. Run `scripts/systemc-tlm-agent extract PROJECT`.
3. Assign evidence IDs to claims. Use Surelog/UHDM, Verilator, and Yosys outputs as supporting structural evidence, not as replacements for the Spec or RTL. For prebuilt JSON views, use the offline query recipes below and explicitly record only the claims used by a contract.
4. Run `scripts/systemc-tlm-agent architect PROJECT`.
5. Complete all eight contract categories according to `references/contracts.md`. Record contradictions in `contracts/conflicts.yaml`.
6. Stop if any category is unresolved or any conflict is open. Ask for a decision with the competing evidence IDs.
7. Validate with `scripts/systemc-tlm-agent architect PROJECT --validate`.
8. Require explicit human approval: `scripts/systemc-tlm-agent approve PROJECT --approver NAME`.
9. Generate only while the approval hash remains valid: `scripts/systemc-tlm-agent generate PROJECT`.
10. Verify locally or in Podman: `scripts/systemc-tlm-agent verify PROJECT --backend auto`.

`run` advances the same pipeline and intentionally stops at architecture and approval gates.

## Agent Roles

Follow `references/roles.md`. Keep Planner, Evidence Extractor, Architect, Implementer, and Verifier outputs separate. The Architect owns contract completeness; the Implementer may not reinterpret unresolved contracts.

## Modeling Policy

- Treat Spec and RTL as ground truth sources. Preserve source location and digest for every extracted claim.
- Model at loosely timed TLM-2.0 transaction granularity unless the approved contract explicitly requires finer timing.
- Isolate minres-SCC usage behind adapters so the functional model remains testable with standard SystemC.
- Represent latency, queues, arbitration, backpressure, errors, register side effects, interrupts, and completion conditions explicitly when supported by evidence.
- A changed input, fact, contract, or conflict file invalidates approval and blocks regeneration.
- Report verification limitations. Do not label a model RTL-equivalent when no shared-stimulus comparator exists.

## Tool Routing

Read `references/tooling.md` before choosing local or container execution. Do not launch large image builds or minres-SCC recompiles automatically; provide the exact command for the user to run.

## Prebuilt EDA Query Recipes

When an extraction or benchmark bundle contains `tools/uhdm.json`,
`tools/yosys.json`, or `tools/verilator.json`, inspect it through `eda-query`;
do not fall back to regular expressions merely because the live parser
executable is absent. Prefer UHDM for types, enums, processes, cases, and FSM
candidates; use Verilator and Yosys as independent structural views.

```bash
eda-query catalog BUNDLE
eda-query query BUNDLE --backend uhdm --kind enums --module TOP
eda-query query BUNDLE --backend uhdm --kind fsm-candidates --module TOP
eda-query query BUNDLE --backend yosys --kind hierarchy --module TOP
eda-query query BUNDLE --backend yosys --kind ports --module TOP
eda-query query BUNDLE --backend verilator --kind statements --module TOP
```

Record a result only after checking that it supports the stated claim:

```bash
systemc-tlm-agent evidence record PROJECT \
  --result RESULT.json \
  --statement "Evidence-grounded claim used by the architecture contract."
```

Treat `empty`, `unsupported`, warnings, and missing backend artifacts as
limitations to report. The query layer never launches an EDA process; use the
normal extraction workflow when artifacts need to be generated.
