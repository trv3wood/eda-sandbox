# Role Boundaries

## Planner

Inventory inputs, define project stages, identify missing tools, and maintain the work queue. Do not decide design behavior.

## Evidence Extractor

Run deterministic extractors and EDA tools. Produce source-located facts and flag apparent contradictions. Do not turn weak inference into a contract.

## Architect

Map evidence into all eight contracts and a schema-v2 `tlm_handoff`. Partition
functional components rather than mirroring RTL modules; define transaction
types, endpoints, channels, operation rules, state/timing abstraction, and
verification observables. Own conflicts and request decisions.

## Implementer

Generate and refine C++17 SystemC/TLM code strictly from the approved
`model/implementation-handoff.yaml`. Do not use RTL/facts to choose behavior;
request an Architect clarification instead. Keep minres-SCC dependencies behind
adapters and add traceable tests for each acceptance scenario.

## Verifier

Compile, run tests, compare against RTL where an explicit stimulus adapter exists, and report pass/fail/blocked separately. Never weaken a check to obtain a pass.
