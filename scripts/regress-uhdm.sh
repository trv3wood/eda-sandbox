#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

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

