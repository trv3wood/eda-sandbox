#!/usr/bin/env bash
set -Eeuo pipefail

profile="${1:-auto}"
if [[ "${profile}" == "auto" ]]; then
  if [[ -f /etc/rocky-release ]]; then
    profile="enterprise"
  elif command -v surelog >/dev/null && command -v eda-uhdm >/dev/null; then
    profile="uhdm"
  elif command -v verilator >/dev/null && command -v yosys >/dev/null; then
    profile="rtl"
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
printf '  Python:  %s\n' "$(python3 --version 2>&1)"

case "${profile}" in
  agent)
    require_tools python3 systemc-tlm-agent benchmark-systemc-tlm eda-query
    systemc-tlm-agent --help >/dev/null
    ;;
  uhdm)
    require_tools python3 surelog uhdm-export eda-uhdm eda-uhdm-produce
    python3 -c 'import uhdm; print("  UHDM:    Python binding available")'
    uhdm-export --version
    eda-uhdm version
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'module top(input logic clk_i, output logic ready_o);' \
      '  assign ready_o = clk_i;' \
      'endmodule' \
      >"${probe_dir}/top.sv"
    (
      cd "${probe_dir}"
      surelog top.sv -top top -parse -elabuhdm -d uhdm >/dev/null
      eda-uhdm export slpp_all/surelog.uhdm --output uhdm.json
      eda-uhdm query slpp_all/surelog.uhdm \
        --kind modules --module work@top |
        python3 -c \
          'import json,sys; assert json.load(sys.stdin)["status"] == "ok"'
    )
    ;;
  rtl)
    require_tools python3 verilator yosys eda-rtl-produce
    printf '  Verilator: %s\n' "$(verilator --version)"
    printf '  Yosys:     %s\n' "$(yosys -V)"
    ;;
  scc)
    require_tools python3 cmake ninja c++
    test -d /opt/scc/include
    test -d /opt/scc/lib
    printf '  CMake:   %s\n' "$(cmake --version | head -n 1)"
    printf '  Ninja:   %s\n' "$(ninja --version)"
    printf '  SCC:     /opt/scc\n'
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'cmake_minimum_required(VERSION 3.20)' \
      'project(scc_probe LANGUAGES CXX)' \
      'find_package(SystemCLanguage CONFIG REQUIRED)' \
      'add_executable(scc_probe main.cpp)' \
      'target_link_libraries(scc_probe PRIVATE SystemC::systemc)' \
      >"${probe_dir}/CMakeLists.txt"
    printf '%s\n' \
      '#include <systemc>' \
      'int sc_main(int, char**) { return 0; }' \
      >"${probe_dir}/main.cpp"
    cmake -S "${probe_dir}" -B "${probe_dir}/build" -G Ninja >/dev/null
    cmake --build "${probe_dir}/build" >/dev/null
    ;;
  enterprise)
    require_tools \
      bash cmake ninja git python3 surelog uhdm-export verilator yosys
    printf '  CMake:     %s\n' "$(cmake --version | head -n 1)"
    printf '  Ninja:     %s\n' "$(ninja --version)"
    printf '  Verilator: %s\n' "$(verilator --version)"
    printf '  Yosys:     %s\n' "$(yosys -V)"
    uhdm-export --version
    probe_dir="$(mktemp -d)"
    trap 'rm -rf "${probe_dir}"' EXIT
    printf '%s\n' \
      'module top(input logic clk_i, output logic ready_o);' \
      '  assign ready_o = clk_i;' \
      'endmodule' \
      >"${probe_dir}/top.sv"
    (
      cd "${probe_dir}"
      surelog top.sv -top top -parse -elabuhdm -d uhdm >/dev/null
      uhdm-export slpp_all/surelog.uhdm uhdm.json
      python3 -c \
        'import json; data=json.load(open("uhdm.json")); assert data["objects"]'
    )
    ;;
  *)
    printf 'ERROR: expected profile agent, uhdm, rtl, scc, enterprise, or auto\n' >&2
    exit 2
    ;;
esac

printf 'Environment check passed.\n'
