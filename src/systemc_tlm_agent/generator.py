from __future__ import annotations

import re
from pathlib import Path

from .io import dump_yaml, load_yaml, project_paths
from .workflow import approval_is_valid


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not normalized or normalized[0].isdigit():
        normalized = "m_" + normalized
    return normalized


def _class_name(value: str) -> str:
    return "".join(part.capitalize() for part in _identifier(value).split("_")) + "Model"


def _module_header(name: str) -> str:
    cls = _class_name(name)
    guard = f"GENERATED_{_identifier(name).upper()}_HPP"
    return f"""#ifndef {guard}
#define {guard}

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace generated {{

class {cls} : public sc_core::sc_module {{
public:
    tlm_utils::simple_target_socket<{cls}> target_socket;

    SC_HAS_PROCESS({cls});
    explicit {cls}(
        sc_core::sc_module_name name,
        sc_core::sc_time latency = sc_core::sc_time(1, sc_core::SC_NS));

private:
    sc_core::sc_time latency_;
    void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay);
}};

}}  // namespace generated

#endif
"""


def _module_source(name: str) -> str:
    cls = _class_name(name)
    return f"""#include "{_identifier(name)}.hpp"
#include "scc_adapter.hpp"

namespace generated {{

{cls}::{cls}(sc_core::sc_module_name name, sc_core::sc_time latency)
    : sc_core::sc_module(name), target_socket("target_socket"), latency_(latency) {{
    target_socket.register_b_transport(this, &{cls}::b_transport);
}}

void {cls}::b_transport(
    tlm::tlm_generic_payload& transaction,
    sc_core::sc_time& delay) {{
    // The per-module latency value comes from architecture.yaml.
    delay += latency_;
    if (transaction.get_data_ptr() == nullptr && transaction.get_data_length() != 0) {{
        transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
        report_warning(name(), "null payload with non-zero length");
        return;
    }}
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
}}

}}  // namespace generated
"""


def _adapter_header() -> str:
    return """#pragma once

#include <systemc>
#include <string>

#if defined(MODEL_HAS_SCC)
#include <scc/report.h>
#endif

namespace generated {

inline void report_info(const char* source, const std::string& message) {
#if defined(MODEL_HAS_SCC)
    SCCINFO(source) << message;
#else
    SC_REPORT_INFO(source, message.c_str());
#endif
}

inline void report_warning(const char* source, const std::string& message) {
    SC_REPORT_WARNING(source, message.c_str());
}

}  // namespace generated
"""


def _top_header(modules: list[dict]) -> str:
    includes = "\n".join(
        f'#include "{_identifier(module["name"])}.hpp"' for module in modules
    )
    declarations = "\n".join(
        f"    {_class_name(module['name'])} {_identifier(module['name'])};"
        for module in modules
    )
    initializers = ",\n        ".join(
        f'{_identifier(module["name"])}("{_identifier(module["name"])}", '
        f'sc_core::sc_time({int(module.get("latency_ns", 1))}, sc_core::SC_NS))'
        for module in modules
    )
    initializers = " : sc_core::sc_module(name)" + (
        ",\n        " + initializers if initializers else ""
    )
    return f"""#pragma once

#include <systemc>
{includes}

namespace generated {{

class ModelTop : public sc_core::sc_module {{
public:
{declarations}

    explicit ModelTop(sc_core::sc_module_name name){initializers} {{}}
}};

}}  // namespace generated
"""


def _cmake(modules: list[dict]) -> str:
    sources = "\n    ".join(
        f"src/{_identifier(module['name'])}.cpp" for module in modules
    )
    return f"""cmake_minimum_required(VERSION 3.24)
project(generated_systemc_model LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(SystemCLanguage CONFIG REQUIRED)
find_package(scc CONFIG QUIET)

add_library(generated_model
    {sources}
)
target_include_directories(generated_model PUBLIC include)
target_link_libraries(generated_model PUBLIC SystemC::systemc)

if(TARGET scc::scc)
    target_link_libraries(generated_model PUBLIC scc::scc)
    target_compile_definitions(generated_model PUBLIC MODEL_HAS_SCC=1)
elseif(TARGET scc)
    target_link_libraries(generated_model PUBLIC scc)
    target_compile_definitions(generated_model PUBLIC MODEL_HAS_SCC=1)
endif()

enable_testing()
add_executable(model_smoke tests/model_smoke.cpp)
target_link_libraries(model_smoke PRIVATE generated_model)
add_test(NAME model_smoke COMMAND model_smoke)
"""


def _smoke_test() -> str:
    return """#include "model_top.hpp"
#include <systemc>

int sc_main(int, char**) {
    generated::ModelTop top("top");
    sc_core::sc_start(sc_core::SC_ZERO_TIME);
    return 0;
}
"""


def generate_model(project_dir: Path) -> dict:
    """Generate a scaffold only when the exact contract set is approved."""
    valid, reason = approval_is_valid(project_dir)
    if not valid:
        raise ValueError(f"model generation blocked: {reason}")
    paths = project_paths(project_dir)
    architecture = load_yaml(paths["contracts"])
    top_name = architecture["top"]
    # The RTL top is a composition boundary, so generate transaction models for
    # its children. A single-module design falls back to modeling the top.
    modules = [
        module
        for module in architecture["model"]["modules"]
        if module["name"] != top_name
    ]
    if not modules:
        modules = architecture["model"]["modules"]

    include_dir = paths["model"] / "include"
    source_dir = paths["model"] / "src"
    test_dir = paths["model"] / "tests"
    for directory in (include_dir, source_dir, test_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (include_dir / "scc_adapter.hpp").write_text(_adapter_header(), encoding="utf-8")
    for module in modules:
        name = module["name"]
        (include_dir / f"{_identifier(name)}.hpp").write_text(
            _module_header(name), encoding="utf-8"
        )
        (source_dir / f"{_identifier(name)}.cpp").write_text(
            _module_source(name), encoding="utf-8"
        )
    (include_dir / "model_top.hpp").write_text(_top_header(modules), encoding="utf-8")
    (test_dir / "model_smoke.cpp").write_text(_smoke_test(), encoding="utf-8")
    (paths["model"] / "CMakeLists.txt").write_text(_cmake(modules), encoding="utf-8")
    dump_yaml(
        paths["model"] / "generation.yaml",
        {
            "schema_version": 1,
            "top": top_name,
            "modules": [module["name"] for module in modules],
            "abstraction": architecture["model"]["abstraction"],
            "approval": reason,
        },
    )
    return {"model_dir": str(paths["model"]), "module_count": len(modules)}
