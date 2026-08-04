#!/usr/bin/env bash
set -Eeuo pipefail

load_toolchain_config() {
  local config="${SYSTEMC_TLM_TOOLCHAIN_CONFIG:-}"
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
      EDA_TOOL_SURELOG|EDA_TOOL_UHDM_LINT|EDA_TOOL_UHDM_HIER|EDA_TOOL_UHDM|\
      EDA_TOOL_VCS|EDA_TOOL_CC|EDA_TOOL_CMAKE|EDA_TOOL_CXX|EDA_TOOL_CTEST|\
      EDA_TOOL_NINJA|EDA_TOOL_PODMAN|EDA_TOOL_PODMAN_COMPOSE|EDA_TOOL_DOCKER|\
      EDA_TOOL_UV|EDA_SCC_HOME|\
      EDA_SCC_DEPS|EDA_SYSTEMC_HOME|VCS_HOME|CMAKE_PREFIX_PATH|\
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
