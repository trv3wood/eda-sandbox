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

printf '  Surelog: %s\n' "$(surelog -version 2>&1 | head -n 1)"

python3 - <<'PY'
from uhdm import uhdm

print(f"  UHDM:    Python wrapper loaded ({uhdm.__name__})")
PY

for tool in "${optional[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  %-8s %s\n' "$tool:" "available"
  else
    printf '  %-8s %s\n' "$tool:" "not installed (optional)"
  fi
done

printf 'Environment check passed. Add project-specific tests under workspace/ or extend this script.\n'
