"""从 CIRCT canonical HW MLIR 提取首版混合 SystemC 结构契约。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    """输入超出首版结构契约。"""


_MODULE_RE = re.compile(
    r"hw\.module(?:\s+private)?\s+@(?P<name>[A-Za-z_.$][\w.$]*)"
    r"\((?P<ports>[^\n]*)\)\s*\{"
)
_PORT_RE = re.compile(
    r"(?P<direction>in|out)\s+%?(?P<name>[A-Za-z_.$][\w.$]*)\s*:\s*"
    r"i(?P<width>\d+)"
)
_INSTANCE_RE = re.compile(
    r"(?P<results>%[\w.$]+(?:\s*,\s*%[\w.$]+)*)\s*=\s*"
    r"hw\.instance\s+\"(?P<name>[^\"]+)\"\s+@(?P<module>[\w.$]+)"
    r"\((?P<inputs>.*?)\)\s*->\s*\((?P<outputs>.*?)\)"
    r"(?:\s*\{[^\n]*\})?",
    re.DOTALL,
)
_INPUT_RE = re.compile(
    r"(?P<name>[\w.$]+)\s*:\s*(?P<source>%[\w.$]+)\s*:\s*i(?P<width>\d+)"
)
_OUTPUT_RE = re.compile(r"(?P<name>[\w.$]+)\s*:\s*i(?P<width>\d+)")
_HW_OUTPUT_RE = re.compile(
    r"hw\.output\s+(?P<sources>%[\w.$]+(?:\s*,\s*%[\w.$]+)*)"
    r"\s*:\s*(?P<types>i\d+(?:\s*,\s*i\d+)*)"
)


def _split_commas(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _parse_width(value: str) -> int:
    width = int(value)
    if width < 1 or width > 64:
        raise ManifestError(f"首版仅支持 1～64 位二态 packed 端口，收到 i{width}")
    return width


@dataclass(frozen=True)
class ModuleText:
    name: str
    ports: list[dict[str, Any]]
    body: str


def _modules(mlir: str) -> dict[str, ModuleText]:
    modules: dict[str, ModuleText] = {}
    for match in _MODULE_RE.finditer(mlir):
        depth = 1
        index = match.end()
        while index < len(mlir) and depth:
            if mlir[index] == "{":
                depth += 1
            elif mlir[index] == "}":
                depth -= 1
            index += 1
        if depth:
            raise ManifestError(f"模块 @{match.group('name')} 的大括号不完整")

        ports: list[dict[str, Any]] = []
        for item in _split_commas(match.group("ports")):
            port_match = _PORT_RE.fullmatch(item)
            if not port_match:
                raise ManifestError(f"不支持的端口声明：{item}")
            ports.append({
                "name": port_match.group("name"),
                "direction": port_match.group("direction"),
                "width": _parse_width(port_match.group("width")),
            })
        name = match.group("name")
        modules[name] = ModuleText(name, ports, mlir[match.end():index - 1])
    if not modules:
        raise ManifestError("未找到 hw.module")
    return modules


def _parse_instance(match: re.Match[str], modules: dict[str, ModuleText]) -> dict[str, Any]:
    module_name = match.group("module")
    if module_name not in modules:
        raise ManifestError(f"实例引用了未知模块 @{module_name}")

    inputs = []
    for item in _split_commas(match.group("inputs")):
        input_match = _INPUT_RE.fullmatch(item)
        if not input_match:
            raise ManifestError(f"不支持的实例输入连接：{item}")
        inputs.append({
            "port": input_match.group("name"),
            "source": input_match.group("source"),
            "width": _parse_width(input_match.group("width")),
        })

    output_specs = []
    for item in _split_commas(match.group("outputs")):
        output_match = _OUTPUT_RE.fullmatch(item)
        if not output_match:
            raise ManifestError(f"不支持的实例输出声明：{item}")
        output_specs.append({
            "port": output_match.group("name"),
            "width": _parse_width(output_match.group("width")),
        })
    results = [item.strip() for item in match.group("results").split(",")]
    if len(results) != len(output_specs):
        raise ManifestError(f"实例 {match.group('name')} 的输出 SSA 数量不匹配")
    for spec, result in zip(output_specs, results, strict=True):
        spec["result"] = result

    declared = {port["name"]: port for port in modules[module_name].ports}
    actual_names = {item["port"] for item in inputs + output_specs}
    if actual_names != set(declared):
        raise ManifestError(
            f"实例 {match.group('name')} 的端口集合与 @{module_name} 声明不一致"
        )
    for item in inputs:
        port = declared[item["port"]]
        if port["direction"] != "in" or port["width"] != item["width"]:
            raise ManifestError(f"实例输入 {match.group('name')}.{item['port']} 类型不匹配")
    for item in output_specs:
        port = declared[item["port"]]
        if port["direction"] != "out" or port["width"] != item["width"]:
            raise ManifestError(f"实例输出 {match.group('name')}.{item['port']} 类型不匹配")
    return {
        "name": match.group("name"),
        "module": module_name,
        "inputs": inputs,
        "outputs": output_specs,
    }


def parse_hw_mlir(mlir: str, top: str) -> dict[str, Any]:
    """解析纯结构顶层，行为叶模块只保留端口签名。"""

    modules = _modules(mlir)
    if top not in modules:
        raise ManifestError(f"未找到顶层模块 @{top}")
    top_module = modules[top]
    instances = [_parse_instance(match, modules) for match in _INSTANCE_RE.finditer(top_module.body)]
    if not instances:
        raise ManifestError("顶层必须至少包含一个 hw.instance")

    output_match = _HW_OUTPUT_RE.search(top_module.body)
    if not output_match:
        raise ManifestError("顶层缺少 hw.output")
    output_ports = [port for port in top_module.ports if port["direction"] == "out"]
    output_sources = _split_commas(output_match.group("sources"))
    output_types = _split_commas(output_match.group("types"))
    if len(output_ports) != len(output_sources) or len(output_ports) != len(output_types):
        raise ManifestError("顶层 hw.output 数量与端口声明不匹配")
    outputs = []
    for port, source, type_name in zip(output_ports, output_sources, output_types, strict=True):
        if type_name != f"i{port['width']}":
            raise ManifestError(f"顶层输出 {port['name']} 类型不匹配")
        outputs.append({"port": port["name"], "source": source, "width": port["width"]})

    remainder = _INSTANCE_RE.sub("", top_module.body)
    remainder = _HW_OUTPUT_RE.sub("", remainder)
    remainder = re.sub(r"//[^\n]*", "", remainder).strip()
    if remainder:
        first_line = remainder.splitlines()[0].strip()
        raise ManifestError(f"顶层不是纯结构模块，发现行为 operation：{first_line}")

    producers: dict[str, str] = {}
    for instance in instances:
        for output in instance["outputs"]:
            producers[output["result"]] = instance["name"]
    top_inputs = {f"%{port['name']}" for port in top_module.ports if port["direction"] == "in"}
    edges: list[tuple[str, str]] = []
    for instance in instances:
        for binding in instance["inputs"]:
            source = binding["source"]
            if source in producers:
                edges.append((producers[source], instance["name"]))
            elif source not in top_inputs:
                raise ManifestError(f"无法解析连接源 {source}")
    _reject_cycles([instance["name"] for instance in instances], edges)
    for output in outputs:
        if output["source"] not in producers and output["source"] not in top_inputs:
            raise ManifestError(f"无法解析顶层输出源 {output['source']}")

    used_modules = {instance["module"] for instance in instances}
    return {
        "schema_version": 1,
        "top": top,
        "ports": top_module.ports,
        "modules": {
            name: {"ports": modules[name].ports}
            for name in sorted(used_modules)
        },
        "instances": instances,
        "outputs": outputs,
    }


def _reject_cycles(nodes: list[str], edges: list[tuple[str, str]]) -> None:
    outgoing = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for source, target in set(edges):
        outgoing[source].append(target)
        indegree[target] += 1
    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        node = ready.pop(0)
        visited += 1
        for target in sorted(outgoing[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if visited != len(nodes):
        raise ManifestError("首版不支持分区之间的反馈环")


def apply_config(manifest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema_version") != 1:
        raise ManifestError("配置 schema_version 必须为 1")
    configured = config.get("partitions")
    if not isinstance(configured, dict):
        raise ManifestError("配置缺少 partitions 对象")
    expected_paths = {f"{manifest['top']}.{item['name']}" for item in manifest["instances"]}
    if set(configured) != expected_paths:
        raise ManifestError("配置的 partition path 必须与顶层实例完整匹配")

    result = json.loads(json.dumps(manifest))
    for instance in result["instances"]:
        path = f"{result['top']}.{instance['name']}"
        partition = configured[path]
        if partition.get("backend") != "verilated_sc":
            raise ManifestError(f"{path} 的默认 backend 必须为 verilated_sc")
        prefix = partition.get("prefix")
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z_]\w*", prefix):
            raise ManifestError(f"{path} 缺少合法 prefix")
        instance["path"] = path
        instance["backend"] = "verilated_sc"
        instance["prefix"] = prefix
        if "replacement" in partition:
            replacement = partition["replacement"]
            if replacement.get("backend") != "native_systemc":
                raise ManifestError(f"{path} replacement backend 不受支持")
            if not replacement.get("class") or not replacement.get("header"):
                raise ManifestError(f"{path} replacement 缺少 class/header")
            instance["replacement"] = replacement
    return result
