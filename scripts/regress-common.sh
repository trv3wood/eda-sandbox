#!/usr/bin/env bash
set -Eeuo pipefail

load_toolchain_config() {
  local config="${EDA_HARNESS_TOOLCHAIN_CONFIG:-}"
  local key value line number=0
  [[ -n "${config}" ]] || return 0
  [[ -r "${config}" ]] || {
    printf 'ERROR: toolchain config is not readable: %s\n' "${config}" >&2
    exit 1
  }
  while IFS= read -r line || [[ -n "${line}" ]]; do
    number=$((number + 1))
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    line="${line#export }"
    if [[ ! "${line}" =~ ^([A-Z0-9_]+)=(.+)$ ]]; then
      printf 'ERROR: invalid toolchain config entry at %s:%s\n' \
        "${config}" "${number}" >&2
      exit 1
    fi
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "${key}" in
      EDA_TOOL_CC|EDA_TOOL_CXX|EDA_TOOL_CMAKE|EDA_TOOL_CTEST|EDA_TOOL_NINJA|\
      EDA_TOOL_MAKE|EDA_TOOL_BAZEL|EDA_TOOL_CONAN|EDA_TOOL_PKG_CONFIG|\
      EDA_TOOL_FUSESOC|EDA_TOOL_GIT|EDA_TOOL_UV|EDA_TOOL_VERILATOR|\
      EDA_TOOL_IVERILOG|EDA_TOOL_SLANG|EDA_TOOL_SURELOG|EDA_TOOL_UHDM_LINT|\
      EDA_TOOL_UHDM_HIER|EDA_TOOL_UHDM|EDA_TOOL_VCS|EDA_TOOL_XRUN|\
      EDA_TOOL_IRUN|EDA_TOOL_VSIM|EDA_TOOL_QRUN|EDA_TOOL_RIVIERA|\
      EDA_TOOL_DSIM|EDA_TOOL_YOSYS|EDA_TOOL_SBY|EDA_TOOL_YOSYS_SMTBMC|\
      EDA_TOOL_BOOLECTOR|EDA_TOOL_Z3|EDA_TOOL_DC_SHELL|EDA_TOOL_GENUS|\
      EDA_TOOL_SPYGLASS|EDA_TOOL_JASPERGOLD|EDA_TOOL_VC_FORMAL|\
      EDA_TOOL_VIVADO|EDA_TOOL_QUARTUS|EDA_TOOL_REGTOOL|EDA_TOOL_VERDI|\
      EDA_TOOL_DVE|EDA_TOOL_GTKWAVE|EDA_TOOL_MODULECMD|EDA_TOOL_PODMAN|\
      EDA_TOOL_PODMAN_COMPOSE|EDA_TOOL_DOCKER|EDA_SCC_HOME|EDA_SCC_DEPS|\
      EDA_SYSTEMC_HOME|VCS_HOME|\
      VERDI_HOME|XCELIUM_HOME|CDS_INST_DIR|QUESTA_HOME|MODELSIM_HOME|\
      ALDEC_HOME|XILINX_VIVADO|QUARTUS_ROOTDIR|CMAKE_PREFIX_PATH|\
      CMAKE_MODULE_PATH|LD_LIBRARY_PATH)
        value="${value%\"}"; value="${value#\"}"
        value="${value%\'}"; value="${value#\'}"
        [[ -n "${value}" ]] || {
          printf 'ERROR: empty toolchain config value at %s:%s\n' \
            "${config}" "${number}" >&2
          exit 1
        }
        export "${key}=${value}"
        ;;
      *)
        printf 'ERROR: unsupported toolchain config variable at %s:%s: %s\n' \
          "${config}" "${number}" "${key}" >&2
        exit 1
        ;;
    esac
  done <"${config}"
}

tool_path() {
  local variable="$1"
  local fallback="$2"
  printf '%s' "${!variable:-${fallback}}"
}

require_tools() {
  local missing=()
  local tool
  for tool in "$@"; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
  done
  if ((${#missing[@]})); then
    printf 'ERROR: missing required tools for %s: %s\n' \
      "${EDA_REGRESS_PROFILE:-unknown}" "${missing[*]}" >&2
    exit 1
  fi
}

print_environment() {
  printf 'EDA sandbox image profile: %s\n' "${EDA_REGRESS_PROFILE:-unknown}"
  printf '  OS:      %s\n' "$(. /etc/os-release && printf '%s %s' "$NAME" "$VERSION_ID")"
  if command -v python3 >/dev/null 2>&1; then
    printf '  Python:  %s\n' "$(python3 --version 2>&1)"
  else
    printf '  Python:  unavailable\n'
  fi
}
