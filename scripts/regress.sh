#!/usr/bin/env bash
set -Eeuo pipefail

profile="${1:-auto}"
if [[ "${profile}" == "auto" ]]; then
  if [[ -d /opt/eda-scc-sdk ]]; then
    profile="scc"
  elif [[ -f /etc/rocky-release ]]; then
    profile="systemc"
  elif command -v vcs >/dev/null && command -v eda-rtl-produce >/dev/null; then
    profile="vcs"
  elif command -v surelog >/dev/null && command -v eda-uhdm >/dev/null; then
    profile="uhdm"
  elif [[ -d /opt/systemc ]]; then
    profile="systemc"
  elif [[ -d /opt/scc ]]; then
    profile="scc"
  else
    profile="agent"
  fi
fi

require_tools() {
  local missing=()
  local tool
  for tool in "$@"; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
  done
  if ((${#missing[@]})); then
    printf 'ERROR: missing required tools for %s: %s\n' \
      "${profile}" "${missing[*]}" >&2
    exit 1
  fi
}

printf 'EDA sandbox image profile: %s\n' "${profile}"
printf '  OS:      %s\n' "$(. /etc/os-release && printf '%s %s' "$NAME" "$VERSION_ID")"
if command -v python3 >/dev/null 2>&1; then
  printf '  Python:  %s\n' "$(python3 --version 2>&1)"
else
  printf '  Python:  unavailable\n'
fi

case "${profile}" in
  agent)
    require_tools python3 systemc-tlm-agent eda-spec-produce
    python3 -c 'import duckdb, networkx, openai'
    systemc-tlm-agent --help >/dev/null
    ;;
  vcs)
    require_tools python3 cc vcs systemc-tlm-agent eda-rtl-produce
    vcs -ID
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'package probe_pkg; parameter int WIDTH = 8; endpackage' \
      'module child(input logic clk_i); logic ready; endmodule' \
      'module top(input logic clk_i); import probe_pkg::*;' \
      '  child u_child(.clk_i(clk_i));' \
      'endmodule' \
      >"${probe_dir}/top.sv"
    printf '%s\n' 'top.sv' >"${probe_dir}/rtl.f"
    printf '%s\n' \
      'schema_version: 1' \
      'name: vcs-probe' \
      'target_top: top' \
      'reference_top: top' \
      'rtl: [top.sv]' \
      'eda_compile:' \
      '  working_directory: .' \
      '  filelists: [rtl.f]' \
      '  sources: []' \
      '  include_dirs: []' \
      '  defines: []' \
      'graph:' \
      '  rtl_extraction:' \
      '    backend: vcs-vpi' \
      '    timeout_seconds: 300' \
      '  spec_extraction:' \
      '    enabled: false' \
      >"${probe_dir}/manifest.yaml"
    systemc-tlm-agent extract "${probe_dir}" --skip-tools
    eda-rtl-produce "${probe_dir}"
    systemc-tlm-agent tools finalize "${probe_dir}"
    python3 -c \
      'import json,sys; p=json.load(open(sys.argv[1])); assert p["status"] == "ready"' \
      "${probe_dir}/.systemc-agent/graph/manifest.json"
    python3 -c \
      'import json,sys; e=[json.loads(x) for x in open(sys.argv[1])]; assert any(x["type"] == "Package" and x["name"] == "probe_pkg" for x in e)' \
      "${probe_dir}/.systemc-agent/graph/entities.jsonl"
    python3 -c \
      'import json,sys; r=[json.loads(x) for x in open(sys.argv[1])]; assert any(x["type"] == "IMPORTS" for x in r)' \
      "${probe_dir}/.systemc-agent/graph/relationships.jsonl"
    ;;
  uhdm)
    require_tools \
      python3 surelog uhdm-lint uhdm-hier eda-uhdm eda-uhdm-produce
    python3 -c 'import uhdm; print("  UHDM:    Python binding available")'
    eda-uhdm version
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'module top(input logic clk_i, output logic ready_o);' \
      '  assign ready_o = clk_i;' \
      'endmodule' \
      >"${probe_dir}/top.sv"
    printf '%s\n' \
      'import os' \
      'import uhdm' \
      'serializer = uhdm.Serializer()' \
      'roots = serializer.Restore(os.environ["UHDM_DATABASE"])' \
      'assert roots' \
      'design = roots[0]' \
      'iterator = uhdm.vpi_iterate(uhdm.uhdmtopModules, design)' \
      'module = uhdm.vpi_scan(iterator)' \
      'assert module is not None' \
      'name = uhdm.vpi_get_str(uhdm.vpiName, module)' \
      'assert name and name.endswith("top"), name' \
      'print(name)' \
      >"${probe_dir}/query.py"
    (
      cd "${probe_dir}"
      surelog top.sv -top top -parse -elabuhdm >/dev/null
      uhdm-lint slpp_all/surelog.uhdm >/dev/null
      uhdm-hier slpp_all/surelog.uhdm --line >uhdm-hier.log
      grep -q 'top' uhdm-hier.log
      eda-uhdm run slpp_all/surelog.uhdm query.py \
        --output-dir query-output
    )
    ;;
  scc)
    require_tools cmake c++ find
    scc_home="${EDA_SCC_HOME:-/opt/scc}"
    if [[ -d "${scc_home}/scc" ]]; then
      scc_prefix="${scc_home}/scc"
      scc_deps="${scc_home}/deps"
    else
      scc_prefix="${scc_home}"
      scc_deps="${EDA_SCC_DEPS:-/opt/scc-deps}"
    fi
    test -d "${scc_prefix}/include"
    systemc_config="$(find "${scc_deps}" -type f \
      -path '*/cmake/SystemCLanguage/SystemCLanguageConfig.cmake' -print -quit)"
    scc_config="$(find "${scc_prefix}" -type f \( \
      -path '*/cmake/scc/scc-config.cmake' -o \
      -path '*/cmake/scc/sccConfig.cmake' \
    \) -print -quit)"
    printf '  SystemC CMake: %s\n' "${systemc_config}"
    printf '  SCC CMake:     %s\n' "${scc_config}"
    test -n "${systemc_config}"
    test -n "${scc_config}"
    printf '  CMake:   %s\n' "$(cmake --version | head -n 1)"
    if command -v ninja >/dev/null 2>&1; then
      printf '  Ninja:   %s\n' "$(ninja --version)"
    else
      printf '  Ninja:   unavailable; using CMake default generator\n'
    fi
    printf '  SCC:     %s\n' "${scc_prefix}"
    printf '  CMAKE_PREFIX_PATH: %s\n' "${CMAKE_PREFIX_PATH:-<unset>}"
    printf '  LD_LIBRARY_PATH:   %s\n' "${LD_LIBRARY_PATH:-<unset>}"
    printf '%s\n' '  SCC shared libraries:'
    find "${scc_prefix}" -type f \( -name '*.so' -o -name '*.so.*' \) -print | sort
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'cmake_minimum_required(VERSION 3.20)' \
      'project(scc_probe LANGUAGES CXX)' \
      'find_package(SystemCLanguage CONFIG REQUIRED)' \
      'find_package(scc CONFIG REQUIRED)' \
      'add_executable(scc_probe main.cpp)' \
      'target_link_libraries(scc_probe PRIVATE SystemC::systemc)' \
      'if(TARGET scc::scc)' \
      '  target_link_libraries(scc_probe PRIVATE scc::scc)' \
      'elseif(TARGET scc)' \
      '  target_link_libraries(scc_probe PRIVATE scc)' \
      'else()' \
      '  message(FATAL_ERROR "scc package exports no supported target")' \
      'endif()' \
      >"${probe_dir}/CMakeLists.txt"
    printf '%s\n' \
      '#include <systemc>' \
      '#include <scc/report.h>' \
      'int sc_main(int, char**) { return 0; }' \
      >"${probe_dir}/main.cpp"
    # Conan 的 CMakeDeps 生成器按 Release 配置随 SDK 一同归档；
    # 不设置构建类型会在 find_package(SystemCLanguage) 阶段直接失败。
    scc_build_type="${EDA_SCC_BUILD_TYPE:-Release}"
    printf '  SCC dependency build type: %s\n' "${scc_build_type}"
    cmake_args=(-S "${probe_dir}" -B "${probe_dir}/build" "-DCMAKE_BUILD_TYPE=${scc_build_type}")
    if command -v ninja >/dev/null 2>&1; then
      cmake_args+=(-G Ninja)
    fi
    if [[ "${EDA_SCC_CMAKE_DEBUG:-0}" == "1" ]]; then
      printf '%s\n' '  CMake find debug: enabled'
      cmake_args+=(-DCMAKE_FIND_DEBUG_MODE=ON)
    fi
    printf '  Configure command: cmake'
    printf ' %q' "${cmake_args[@]}"
    printf '\n'
    cmake "${cmake_args[@]}"
    printf '  Build command: cmake --build %q --parallel\n' "${probe_dir}/build"
    cmake --build "${probe_dir}/build" --parallel
    ;;
  systemc)
    require_tools cmake c++
    test -d /opt/systemc/include
    test -n "$(find /opt/systemc -type f \
      -path '*/cmake/SystemCLanguage/SystemCLanguageConfig.cmake' -print -quit)"
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'cmake_minimum_required(VERSION 3.16)' \
      'project(systemc_probe LANGUAGES CXX)' \
      'find_package(SystemCLanguage CONFIG REQUIRED)' \
      'add_executable(systemc_probe main.cpp)' \
      'target_link_libraries(systemc_probe PRIVATE SystemC::systemc)' \
      >"${probe_dir}/CMakeLists.txt"
    printf '%s\n' \
      '#include <systemc>' \
      'int sc_main(int, char**) { return 0; }' \
      >"${probe_dir}/main.cpp"
    cmake -S "${probe_dir}" -B "${probe_dir}/build" >/dev/null
    cmake --build "${probe_dir}/build" >/dev/null
    ;;
  *)
    printf 'ERROR: expected profile agent, vcs, uhdm, scc, systemc, or auto\n' >&2
    exit 2
    ;;
esac

printf 'Environment check passed.\n'
