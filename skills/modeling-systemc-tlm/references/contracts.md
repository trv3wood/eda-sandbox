# Eight Modeling Contracts

For every item write a precise `statement`, attach `evidence_ids`, and record assumptions or confidence when useful.

1. `functional_intent`: problem solved, software usage, upstream/downstream expectations.
2. `transaction_entry`: register write, packet arrival, socket call, interrupt, or other operation trigger.
3. `input_domain`: formats, widths, units, legal combinations, alignment, and ranges.
4. `algorithm_transform`: address, length, index, checksum, data conversion, and ordering calculations.
5. `data_flow`: ingress interface, buffers/stages, routing, and egress interface.
6. `state_concurrency`: idle/busy state, channels, queues, arbitration, preemption, backpressure, and shared resources.
7. `boundaries_exceptions`: zero/max length, overflow, out-of-range access, illegal configuration, and downstream failure.
8. `observable_results`: output data, register side effects, interrupts, errors, completion, and latency.

Conflict policy:

- Record source A and source B as evidence IDs.
- Describe the incompatible interpretations and model impact.
- Keep `status: open` until a named decision is recorded.
- Do not silently prefer Spec over RTL or RTL over Spec. The user decides whether the model represents intended behavior, implemented behavior, or both as variants.

