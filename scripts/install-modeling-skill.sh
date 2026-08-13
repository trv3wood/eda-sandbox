#!/usr/bin/env bash
set -Eeuo pipefail

target=all
mode=link
force=false

while (($#)); do
  case "$1" in
    --target) target="${2:?missing target}"; shift 2 ;;
    --mode) mode="${2:?missing mode}"; shift 2 ;;
    --force) force=true; shift ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[[ "$target" =~ ^(all|codex|claude)$ ]] || { printf 'Invalid target\n' >&2; exit 2; }
[[ "$mode" =~ ^(link|copy)$ ]] || { printf 'Invalid mode\n' >&2; exit 2; }

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
skill_names=(eda-tool-assistant modeling-systemc-tlm modeling-systemverilog cycle-systemc-modeling)

install_dir() {
  local source="$1" destination="$2"
  mkdir -p "$(dirname -- "$destination")"
  if [[ -e "$destination" || -L "$destination" ]]; then
    $force || { printf 'Refusing to replace %s; pass --force\n' "$destination" >&2; exit 1; }
    if [[ -d "$destination" && ! -L "$destination" ]]; then
      mv "$destination" "${destination}.backup.$(date +%Y%m%d%H%M%S)"
    else
      unlink "$destination"
    fi
  fi
  if [[ "$mode" == link ]]; then
    ln -s "$source" "$destination"
  else
    cp -a "$source" "$destination"
  fi
}

if [[ "$target" == all || "$target" == codex ]]; then
  for skill_name in "${skill_names[@]}"; do
    install_dir "$repo_root/skills/$skill_name" "$HOME/.codex/skills/$skill_name"
  done
fi

if [[ "$target" == all || "$target" == claude ]]; then
  for skill_name in "${skill_names[@]}"; do
    install_dir "$repo_root/skills/$skill_name" "$HOME/.claude/skills/$skill_name"
  done
  mkdir -p "$HOME/.claude/agents"
  for source in "$repo_root"/integrations/claude/agents/*.md; do
    destination="$HOME/.claude/agents/$(basename -- "$source")"
    if [[ -e "$destination" ]] && ! $force; then
      printf 'Refusing to replace %s; pass --force\n' "$destination" >&2
      exit 1
    fi
    cp "$source" "$destination"
  done
fi

printf 'Installed EDA assistant and modeling skills for %s using %s mode.\n' "$target" "$mode"
if [[ "$mode" == copy ]]; then
  printf 'Set EDA_HARNESS_ROOT=%s so copied skill wrappers can locate the CLI.\n' "$repo_root"
fi
