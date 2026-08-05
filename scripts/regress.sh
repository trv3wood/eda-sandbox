#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"
load_toolchain_config
profile="${1:-auto}"

if [[ "${profile}" == "auto" ]]; then
  if [[ -n "${EDA_SCC_HOME:-}" ]]; then
    profile="scc"
  elif [[ -f /etc/rocky-release ]]; then
    profile="systemc"
  elif command -v "$(tool_path EDA_TOOL_VCS vcs)" >/dev/null; then
    profile="vcs"
  elif command -v "$(tool_path EDA_TOOL_SURELOG surelog)" >/dev/null && command -v "$(tool_path EDA_TOOL_UHDM eda-uhdm)" >/dev/null; then
    profile="uhdm"
  elif [[ -n "${EDA_SYSTEMC_HOME:-}" ]]; then
    profile="systemc"
  else
    profile="agent"
  fi
fi

case "${profile}" in
  agent|vcs|uhdm|scc|systemc) ;;
  *)
    printf 'ERROR: expected profile agent, vcs, uhdm, scc, systemc, or auto\n' >&2
    exit 2
    ;;
esac

export EDA_REGRESS_PROFILE="${profile}"
print_environment
exec bash "${script_dir}/regress-${profile}.sh"
