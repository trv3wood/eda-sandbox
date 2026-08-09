"""从 hierarchy manifest 生成只含结构连接的 SystemC 顶层。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hybrid_manifest import ManifestError


def _cpp_type(width: int) -> str:
    return "bool" if width == 1 else f"sc_dt::sc_uint<{width}>"


def _class_name(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", name) if part)


def generate_wrapper(
    manifest: dict[str, Any],
    output: Path,
    replacements: bool = False,
) -> str:
    """生成结构壳；replacements=True 时启用 manifest 中的原生替代模块。"""

    includes = {"systemc"}
    classes: dict[str, str] = {}
    for instance in manifest["instances"]:
        if replacements and "replacement" in instance:
            replacement = instance["replacement"]
            includes.add(replacement["header"])
            classes[instance["name"]] = replacement["class"]
        else:
            includes.add(f"{instance['prefix']}.h")
            classes[instance["name"]] = instance["prefix"]

    class_name = _class_name(manifest["top"])
    lines = ["#pragma once", ""]
    for header in sorted(includes):
        lines.append(f"#include <{header}>" if header == "systemc" else f'#include "{header}"')
    lines.extend(["", f"class {class_name} final : public sc_core::sc_module {{", "public:"])
    for port in manifest["ports"]:
        direction = "sc_in" if port["direction"] == "in" else "sc_out"
        lines.append(
            f'    sc_core::{direction}<{_cpp_type(port["width"])}> '
            f'{port["name"]}{{"{port["name"]}"}};'
        )

    lines.append("")
    result_signals: dict[str, str] = {}
    for instance in manifest["instances"]:
        for item in instance["outputs"]:
            signal = f"sig_{instance['name']}_{item['port']}"
            result_signals[item["result"]] = signal
            lines.append(
                f'    sc_core::sc_signal<{_cpp_type(item["width"])}> '
                f'{signal}{{"{signal}"}};'
            )
    lines.append("")
    for instance in manifest["instances"]:
        lines.append(
            f'    {classes[instance["name"]]} {instance["name"]}'
            f'{{"{instance["name"]}"}};'
        )

    lines.extend([
        "",
        f"    SC_HAS_PROCESS({class_name});",
        f"    explicit {class_name}(sc_core::sc_module_name name)",
        "        : sc_core::sc_module(name) {",
    ])
    for instance in manifest["instances"]:
        for item in instance["inputs"]:
            source = item["source"]
            if source.startswith("%") and source[1:] in {
                port["name"] for port in manifest["ports"] if port["direction"] == "in"
            }:
                target = source[1:]
            elif source in result_signals:
                target = result_signals[source]
            else:
                raise ManifestError(f"生成结构壳时无法解析 {source}")
            lines.append(f"        {instance['name']}.{item['port']}({target});")
        for item in instance["outputs"]:
            lines.append(
                f"        {instance['name']}.{item['port']}({result_signals[item['result']]});"
            )
    lines.append("        SC_METHOD(forward_outputs);")
    for item in manifest["outputs"]:
        lines.append(f"        sensitive << {result_signals[item['source']]};")
    lines.extend(["    }", "", "private:", "    void forward_outputs() {"])
    for item in manifest["outputs"]:
        lines.append(
            f"        {item['port']}.write({result_signals[item['source']]}.read());"
        )
    lines.extend(["    }", "};", ""])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return class_name
