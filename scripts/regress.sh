#!/usr/bin/env bash
set -Eeuo pipefail

required=(bash cmake ninja git python3 surelog verilator yosys)
optional=(flex bison dot systemc-tlm-agent)
missing=()

for tool in "${required[@]}"; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done

if ((${#missing[@]})); then
  printf 'ERROR: missing required tools: %s\n' "${missing[*]}" >&2
  exit 1
fi

printf 'EDA sandbox regression environment\n'
printf '  OS:      %s\n' "$(. /etc/os-release && printf '%s %s' "$NAME" "$VERSION_ID")"
printf '  Kernel:  %s\n' "$(uname -sr)"
printf '  CMake:   %s\n' "$(cmake --version | head -n 1)"
printf '  Ninja:   %s\n' "$(ninja --version)"
printf '  Python:  %s\n' "$(python3 --version 2>&1)"

python3 - <<'PY'
import sys

if sys.version_info[:2] != (3, 10):
    raise SystemExit(f"ERROR: expected Python 3.10, got {sys.version.split()[0]}")
PY

surelog_probe_dir="$(mktemp -d)"
trap 'rm -rf "${surelog_probe_dir}"' EXIT
if ! surelog_output="$(
    cd "${surelog_probe_dir}"
    surelog -version 2>&1
)"; then
    printf 'ERROR: Surelog failed to start:\n%s\n' "${surelog_output}" >&2
    exit 1
fi
surelog_version_line="$(
    sed -n 's/^[[:space:]]*VERSION:[[:space:]]*/VERSION: /p' \
        "${surelog_probe_dir}/slpp_all/surelog.log" |
        head -n 1
)"
if [[ -z "${surelog_version_line}" ]]; then
    printf 'ERROR: Surelog output did not contain a version:\n%s\n' \
        "${surelog_output}" >&2
    exit 1
fi
printf '  Surelog: %s\n' "${surelog_version_line}"

uhdm_library="$(
    find /opt/conda/envs/eda/lib -maxdepth 1 \
        \( -name 'libuhdm.so*' -o -name 'libuhdm.a' \) \
        -print -quit
)"
if [[ -z "${uhdm_library}" ]]; then
    printf 'ERROR: UHDM library not found in the eda environment\n' >&2
    exit 1
fi
printf '  UHDM:    %s\n' "${uhdm_library}"

for tool in "${optional[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  %-8s %s\n' "$tool:" "available"
  else
    printf '  %-8s %s\n' "$tool:" "not installed (optional)"
  fi
done

printf 'Environment check passed. Add project-specific tests under workspace/ or extend this script.\n'
