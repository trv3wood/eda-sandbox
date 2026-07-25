# Role Boundaries

## Planner

Inventory inputs, define project stages, identify missing tools, and maintain the work queue. Do not decide design behavior.

## Evidence Extractor

Run deterministic extractors and EDA tools. Produce source-located facts and flag apparent contradictions. Do not turn weak inference into a contract.

## Architect

Map evidence into all eight contracts, partition 7–8 module IPs, choose transaction boundaries, state/timing abstraction, and verification observables. Own conflicts and request decisions.

## Implementer

Generate and refine C++17 SystemC/TLM code strictly from approved contracts. Keep minres-SCC dependencies behind adapters. Add traceable tests for each contract.

## Verifier

Compile, run tests, compare against RTL where an explicit stimulus adapter exists, and report pass/fail/blocked separately. Never weaken a check to obtain a pass.

