#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

require_tools python3 systemc-tlm-agent eda-spec-produce
python3 -c 'import duckdb, networkx, openai'
systemc-tlm-agent --help >/dev/null

