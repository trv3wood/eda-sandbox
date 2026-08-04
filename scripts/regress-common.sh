#!/usr/bin/env bash
set -Eeuo pipefail

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
