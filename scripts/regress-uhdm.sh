#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

surelog_tool="$(tool_path EDA_TOOL_SURELOG surelog)"
uhdm_lint_tool="$(tool_path EDA_TOOL_UHDM_LINT uhdm-lint)"
uhdm_hier_tool="$(tool_path EDA_TOOL_UHDM_HIER uhdm-hier)"
uhdm_tool="$(tool_path EDA_TOOL_UHDM eda-uhdm)"
require_tools \
  python3 "${surelog_tool}" "${uhdm_lint_tool}" "${uhdm_hier_tool}" "${uhdm_tool}"
python3 -c 'import uhdm; print("  UHDM:    Python binding available")'
"${uhdm_tool}" version
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
  "${surelog_tool}" top.sv -top top -parse -elabuhdm >/dev/null
  "${uhdm_lint_tool}" slpp_all/surelog.uhdm >/dev/null
  "${uhdm_hier_tool}" slpp_all/surelog.uhdm --line >uhdm-hier.log
  grep -q 'top' uhdm-hier.log
  "${uhdm_tool}" run slpp_all/surelog.uhdm query.py \
    --output-dir query-output
)
