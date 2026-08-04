#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
profile="${1:-auto}"

if [[ "${profile}" == "auto" ]]; then
  if [[ -d /opt/eda-scc-sdk ]]; then
    profile="scc"
  elif [[ -f /etc/rocky-release ]]; then
    profile="systemc"
  elif command -v vcs >/dev/null && command -v eda-rtl-produce >/dev/null; then
    profile="vcs"
  elif command -v surelog >/dev/null && command -v eda-uhdm >/dev/null; then
    profile="uhdm"
  elif [[ -d /opt/systemc ]]; then
    profile="systemc"
  elif [[ -d /opt/scc ]]; then
    profile="scc"
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

source "${script_dir}/regress-common.sh"
export EDA_REGRESS_PROFILE="${profile}"
print_environment
exec bash "${script_dir}/regress-${profile}.sh"
