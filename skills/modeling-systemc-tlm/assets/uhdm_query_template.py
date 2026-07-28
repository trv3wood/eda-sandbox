"""Small direct UHDM query; copy and tailor it to one modeling question."""

from __future__ import annotations

import json
import os
import sys

import uhdm


def scan(relation: int, handle: object):
    iterator = uhdm.vpi_iterate(relation, handle)
    while iterator:
        item = uhdm.vpi_scan(iterator)
        if item is None:
            break
        yield item


def string(prop: int, handle: object) -> str | None:
    value = uhdm.vpi_get_str(prop, handle)
    return value if value is not None else None


def location(handle: object) -> dict[str, object]:
    return {
        "file": string(uhdm.vpiFile, handle),
        "line": uhdm.vpi_get(uhdm.vpiLineNo, handle),
    }


serializer = uhdm.Serializer()
roots = serializer.Restore(os.environ["UHDM_DATABASE"])
if not roots:
    raise RuntimeError("UHDM database contains no design root")
design = roots[0]
requested_top = sys.argv[1] if len(sys.argv) > 1 else None

modules = []
for module in scan(uhdm.uhdmtopModules, design):
    name = string(uhdm.vpiName, module)
    definition = string(uhdm.vpiDefName, module)
    aliases = {
        value
        for item in (name, definition)
        if item
        for value in (item, item.rsplit("@", 1)[-1])
    }
    if requested_top and requested_top not in aliases:
        continue
    ports = []
    for port in scan(uhdm.vpiPort, module):
        ports.append(
            {
                "name": string(uhdm.vpiName, port),
                "direction": uhdm.vpi_get(uhdm.vpiDirection, port),
                "size": uhdm.vpi_get(uhdm.vpiSize, port),
                "location": location(port),
            }
        )
    children = []
    for child in scan(uhdm.vpiModule, module):
        children.append(
            {
                "name": string(uhdm.vpiName, child),
                "definition": string(uhdm.vpiDefName, child),
                "location": location(child),
            }
        )
    modules.append(
        {
            "name": name,
            "definition": definition,
            "location": location(module),
            "ports": ports[:256],
            "children": children[:256],
        }
    )

print(json.dumps({"top_modules": modules}, indent=2, sort_keys=True))
