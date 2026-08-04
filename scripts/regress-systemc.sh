#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

require_tools cmake c++
test -d /opt/systemc/include
test -n "$(find /opt/systemc -type f \
  -path '*/cmake/SystemCLanguage/SystemCLanguageConfig.cmake' -print -quit)"
probe_dir="$(mktemp -d)"
trap 'rm -rf "${probe_dir}"' EXIT
printf '%s\n' \
  'cmake_minimum_required(VERSION 3.16)' \
  'project(systemc_probe LANGUAGES CXX)' \
  'find_package(SystemCLanguage CONFIG REQUIRED)' \
  'add_executable(systemc_probe main.cpp)' \
  'target_link_libraries(systemc_probe PRIVATE SystemC::systemc)' \
  >"${probe_dir}/CMakeLists.txt"
printf '%s\n' \
  '#include <systemc>' \
  'int sc_main(int, char**) { return 0; }' \
  >"${probe_dir}/main.cpp"
cmake -S "${probe_dir}" -B "${probe_dir}/build" >/dev/null
cmake --build "${probe_dir}/build" >/dev/null
