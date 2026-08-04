---
name: modeling-systemverilog
description: Build evidence-backed SystemVerilog interface, hierarchy, and bounded patch scaffolds from specifications, register maps, existing RTL, a canonical graph, and an approved RTL handoff. Use when creating a new RTL module contract, reconstructing hierarchy wiring, preparing an existing .v/.sv design for a controlled LLM modification, or verifying that an RTL edit stayed within approved syntax nodes and structural deltas.
---

# SystemVerilog Modeling

Use the deterministic CLI for graph, approval, generation, edit application, and verification. Use agent reasoning only to complete evidence-backed contracts and replacement text; never invent missing interface or behavior.

## Workflow

1. Read `references/workflow.md` and `references/rtl-handoff.md`.
2. Initialize/extract with `scripts/systemverilog-agent`. With RTL inputs, build the pyslang source index; never replace a failed AST frontend with regex extraction.
3. Run `architect PROJECT --mode interface|hierarchy|patch` and complete `.systemc-agent/contracts/rtl-handoff.yaml`.
4. Resolve all RTL conflicts. Validate, then require explicit approval with `approve PROJECT --approver NAME`.
5. Run `generate PROJECT`. Work only in `.systemc-agent/rtl/worktree/`; never edit the original source tree.
6. For each generated or source edit target, produce `edits.json` with the exact target ID, base digest, replacement text, and requirement IDs. Apply it only through `apply-edits`.
7. Run `verify PROJECT`. Report parse/elaboration, structural delta, lint, compile, and existing simulation tests separately. A missing tool or test is `blocked`, not passed.

## Mode Policy

- `interface`: emit only exact imports, parameters, ports, and evidence-marked TODO regions from the approved handoff.
- `hierarchy`: additionally emit declarations, named parameter bindings, named port connections, and child instances. Do not infer connections from similar names.
- `patch`: copy the project into the isolated worktree and edit only approved process, continuous-assignment, or instance CST nodes.
- Keep complete-project reverse printing, macro-body edits without a single source span, and package/class/interface/function/task/generate rewrites unsupported in v1.

## Evidence and Role Boundaries

- Treat Spec, register maps, and RTL as ground-truth evidence. Cite canonical graph entity IDs or deterministic text-unit IDs for every target and requirement.
- Treat pyslang CST/source spans as source-navigation facts. UHDM/VPI is an optional elaborated-identity and structure cross-check, not a source-code generator.
- The Architect owns `rtl-handoff.yaml`, conflicts, structure expectations, and acceptance scenarios.
- The Implementer consumes only the approved handoff and bounded edit context. Return gaps to the Architect; do not inspect unrelated RTL to choose behavior.
- The Verifier must not weaken lint, compile, structural, or simulation checks to make an implementation pass.

## Tool Policy

Install the local RTL extra for pyslang. Use configured project commands for lint, compile, and simulation. Do not launch large container builds or long commercial EDA jobs automatically; provide the exact command for the user to run.

