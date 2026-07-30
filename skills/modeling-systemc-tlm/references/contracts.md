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

## Implementer TLM Handoff (schema version 3)

The approved `tlm_handoff` is the Implementer's behavioral input. Facts and RTL
remain traceability material for the Architect; the Implementer must request a
clarification rather than use them to select behavior.

`policy` is fixed to `loosely-timed-tlm-2.0` and blocking `b_transport`. It
must forbid clock-edge, RTL signal/handshake, pipeline-register, and
cycle-by-cycle modeling. Define named `transaction_types` with fields, types,
optional widths/units/constraints, and success/error response semantics.

Define `functional_modules` by responsibility, not RTL hierarchy. Each module
requires evidence IDs, named inbound/outbound endpoints, operation rules
(`trigger_endpoint`, effect, completion), state/concurrency, service latency,
error behavior, and observables. `channels` connect endpoints and define the
transaction type, ordering, ownership, backpressure, and completion semantics.
`acceptance_scenarios` provide evidence-backed Given/When/Then transaction
tests. Each scenario has a stable `id` and non-empty `test_ids`. The Architect
owns `contracts/testbench/testbench.yaml`, public headers, and executable
SystemC/TLM black-box tests. The manifest uses `schema_version: 2` and
`kind: systemc_tlm`; every source must contain an `sc_main`, TLM initiator
socket and binding, `tlm_generic_payload`, and `b_transport`. Manifest coverage
and scenario `test_ids` must match exactly.
All of these files are part of the approval hash. `rtl_traceability` is optional evidence navigation only and must not
set TLM component boundaries.

Minimal handoff shape:

```yaml
tlm_handoff:
  policy:
    abstraction: loosely-timed-tlm-2.0
    transport: b_transport
    forbidden_detail: [clock edges, RTL signals and handshakes]
  transaction_types:
    - name: packet_request
      fields: [{name: length, type: unsigned, width_bits: 16}]
      response: {success: completion, errors: [invalid_length]}
  functional_modules:
    - name: packet_service
      responsibility: Validate and complete packet requests.
      evidence_ids: [ev-spec-0001]
      endpoints: [{name: submit, direction: inbound, transaction: packet_request}]
      operations:
        - {name: process, trigger_endpoint: submit, effect: Validate and route, completion: Return completion, evidence_ids: [ev-spec-0001]}
      state: {states: [idle, active], initial: idle, concurrency: One request at a time.}
      timing: {service_latency_ns: 10}
      error_behavior: Return an error response for invalid length.
      observables: [completion response]
  channels: []
  acceptance_scenarios:
    - {name: valid request, given: A valid request, when: submit receives it, then: A completion is returned, evidence_ids: [ev-spec-0001]}
```
