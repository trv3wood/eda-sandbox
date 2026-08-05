#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

cc_tool="$(tool_path EDA_TOOL_CC cc)"
vcs_tool="$(tool_path EDA_TOOL_VCS vcs)"
require_tools "${cc_tool}" "${vcs_tool}" eda-harness
"${vcs_tool}" -ID >/dev/null
eda-harness --help >/dev/null
