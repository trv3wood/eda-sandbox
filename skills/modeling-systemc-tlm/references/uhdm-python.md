# Direct UHDM Python Queries

The standard producer uses the official UHDM Python binding only after
Surelog binary-database validation, `uhdm-lint`, and `uhdm-hier --line` pass. For additional
questions, use the binding only against that validated
`tools/surelog-work/slpp_all/surelog.uhdm`. Write the smallest script that
answers the current modeling question. Do not build a second generic object
model, query DSL, or regex reconstruction.

The current image pins UHDM v1.84. Use capability checks for optional
relations rather than depending on a newer release or emulating a missing
relation.

## Restore and scan

Keep the serializer alive for the entire traversal. `Restore` owns the loaded
handles.

```python
import os
import uhdm

serializer = uhdm.Serializer()
roots = serializer.Restore(os.environ["UHDM_DATABASE"])
if not roots:
    raise RuntimeError("UHDM database contains no design root")
design = roots[0]

def scan(relation, handle):
    iterator = uhdm.vpi_iterate(relation, handle)
    while iterator:
        item = uhdm.vpi_scan(iterator)
        if item is None:
            break
        yield item

def text(prop, handle):
    value = uhdm.vpi_get_str(prop, handle)
    return value if value is not None else None
```

`Restore` returns a `vpiHandleVector`, not the design handle itself; pass
`roots[0]` to `vpi_iterate`. Start with both views:

- `uhdmtopModules`: elaborated top instances, resolved parameters, generated
  hierarchy, and connectivity.
- `uhdmallModules`: module definitions and folded source structure.
- `uhdmallPackages`: package declarations, typedefs, enums, and parameters.

For child objects, prefer standard VPI relations such as `vpiPort`,
`vpiModule`, `vpiParameter`, `vpiProcess`, `vpiContAssign`, `vpiNet`, and
`vpiReg`. UHDM releases and object classes expose different optional
relations, so check them with `getattr(uhdm, "vpiVariables", None)` and report
an unavailable relation rather than silently substituting text matching.

Use standard properties directly:

```python
name = uhdm.vpi_get_str(uhdm.vpiName, handle)
definition = uhdm.vpi_get_str(uhdm.vpiDefName, handle)
file_name = uhdm.vpi_get_str(uhdm.vpiFile, handle)
line = uhdm.vpi_get(uhdm.vpiLineNo, handle)
object_type = uhdm.vpi_get(uhdm.vpiType, handle)
```

Surelog commonly prefixes names with a library, for example `work@dma` in
both `vpiName` and `vpiDefName`. When accepting a user-supplied top, compare
both the full name and the suffix after the final `@`; do not assume the
unqualified RTL name is returned.

Treat a zero or missing `vpiSize` as unavailable until ranges/types confirm
the width; it is not sufficient evidence that a packed or aggregate port is a
scalar.

Avoid an unbounded recursive walk. Select a top/module first, inspect one or
two relations at a time, cap printed objects, and print explicit `null` or
diagnostics for unavailable properties.

## Questions useful for TLM modeling

- Transaction boundary: top ports, directions, widths, interfaces, clock and
  reset inputs.
- Partitioning: elaborated child modules, instance names, definition names,
  and parameter overrides.
- State/concurrency: processes, sequential variables, event controls, and
  continuous assignments.
- Data flow: nets, variables, assignments, drivers, and connected endpoints.
- Algorithms and control: case statements, operations, conditions, enums, and
  package constants.
- Boundaries/exceptions: error/status signals, assertions, default branches,
  FIFO-full/empty paths, abort, timeout, and interrupt logic.
- Observables: output ports, registers, state/status variables, and interrupt
  assignments.

Use the elaborated view for actual instantiated structure and the definition
view for source-level process/case/type detail. A missing object in one view is
not evidence that the behavior is absent.

## Execute

Copy and edit the provided template, then run it in the UHDM role:

```bash
mkdir -p WORK/audits/uhdm-query
cp skills/modeling-systemc-tlm/assets/uhdm_query_template.py \
  WORK/audits/uhdm-query/query.py
scripts/eda-run --work WORK uhdm \
  eda-uhdm run DATABASE /workspace/audits/uhdm-query/query.py \
  --output-dir /workspace/audits/uhdm-query/output -- TOP
```

`stdout.log` is the script's bytes unchanged. `stderr.log` contains its
diagnostics. `run.json` records database/script hashes, binding information,
limits, return code, and stream hashes.

These outputs are exploratory. Use them to navigate back to the relevant Spec
or RTL source, and record the query command as a harness check when it is part
of task verification.
Use reported `vpiFile`/`vpiLineNo` locations to inspect the actual RTL and cite
the extractor-owned evidence IDs. Report unsupported relations, incomplete
elaboration, and parser diagnostics as limitations.

## Upstream references

- [UHDM Python API](https://github.com/chipsalliance/UHDM#python-api)
- [UHDM model concepts](https://github.com/chipsalliance/UHDM#model-concepts)
- [UHDM build and installation](https://github.com/chipsalliance/UHDM/blob/master/INSTALL.md)
