#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

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

