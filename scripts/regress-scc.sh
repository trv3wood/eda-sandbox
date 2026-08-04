#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

require_tools cmake c++ find
scc_home="${EDA_SCC_HOME:-/opt/scc}"
if [[ -d "${scc_home}/scc" ]]; then
  scc_prefix="${scc_home}/scc"
  scc_deps="${scc_home}/deps"
else
  scc_prefix="${scc_home}"
  scc_deps="${EDA_SCC_DEPS:-/opt/scc-deps}"
fi
test -d "${scc_prefix}/include"
systemc_config="$(find "${scc_deps}" -type f \
  -path '*/cmake/SystemCLanguage/SystemCLanguageConfig.cmake' -print -quit)"
scc_config="$(find "${scc_prefix}" -type f \( \
  -path '*/cmake/scc/scc-config.cmake' -o \
  -path '*/cmake/scc/sccConfig.cmake' \
\) -print -quit)"
printf '  SystemC CMake: %s\n' "${systemc_config}"
printf '  SCC CMake:     %s\n' "${scc_config}"
test -n "${systemc_config}"
test -n "${scc_config}"
printf '  CMake:   %s\n' "$(cmake --version | head -n 1)"
if command -v ninja >/dev/null 2>&1; then
  printf '  Ninja:   %s\n' "$(ninja --version)"
else
  printf '  Ninja:   unavailable; using CMake default generator\n'
fi
printf '  SCC:     %s\n' "${scc_prefix}"
printf '  CMAKE_PREFIX_PATH: %s\n' "${CMAKE_PREFIX_PATH:-<unset>}"
printf '  LD_LIBRARY_PATH:   %s\n' "${LD_LIBRARY_PATH:-<unset>}"
# Rocky SDK 会随包归档 Conan generators；Ubuntu 镜像只部署包本身，
# 两种布局都应由同一个 SCC 探针支持，诊断不能把可选目录当作前置条件。
printf '%s\n' '  Boost CMake package files:'
find "${scc_deps}" -type f \( \
  -iname 'boost*config.cmake' -o \
  -iname 'boost*targets*.cmake' \
\) -print | sort
printf '%s\n' '  Boost date_time/filesystem libraries:'
find "${scc_deps}" -type f \( \
  -name 'libboost_date_time.*' -o -name 'libboost_filesystem.*' \
\) -print | sort
printf '%s\n' '  SCC shared libraries:'
find "${scc_prefix}" -type f \( -name '*.so' -o -name '*.so.*' \) -print | sort
probe_root="$(mktemp -d)"
trap 'rm -rf "${probe_root}"' EXIT
boost_probe_dir="${probe_root}/01-boost-components"
scc_probe_dir="${probe_root}/02-scc-package"
mkdir -p "${boost_probe_dir}" "${scc_probe_dir}"
# Conan 的 CMakeDeps 生成器按 Release 配置随 SDK 一同归档；
# 不设置构建类型会在 find_package(SystemCLanguage) 阶段直接失败。
scc_build_type="${EDA_SCC_BUILD_TYPE:-Release}"
printf '  SCC dependency build type: %s\n' "${scc_build_type}"
cmake_debug_args=()
if [[ -n "${EDA_SCC_CMAKE_DEBUG_PACKAGES:-}" ]]; then
  printf '  CMake find debug packages: %s\n' "${EDA_SCC_CMAKE_DEBUG_PACKAGES}"
  cmake_debug_args+=("--debug-find-pkg=${EDA_SCC_CMAKE_DEBUG_PACKAGES}")
elif [[ "${EDA_SCC_CMAKE_DEBUG:-0}" == "1" ]]; then
  printf '%s\n' '  CMake find debug: all packages (legacy switch)'
  cmake_debug_args+=(-DCMAKE_FIND_DEBUG_MODE=ON)
fi
cmake_generator_args=()
if command -v ninja >/dev/null 2>&1; then
  cmake_generator_args=(-G Ninja)
fi
printf '%s\n' '  === Phase 1/3: verify Boost date_time and filesystem ==='
printf '%s\n' \
  'cmake_minimum_required(VERSION 3.20)' \
  'project(scc_boost_probe LANGUAGES CXX)' \
  'find_package(Boost CONFIG REQUIRED)' \
  'foreach(boost_target IN ITEMS Boost::date_time Boost::filesystem)' \
  '  if(NOT TARGET ${boost_target})' \
  '    message(FATAL_ERROR "Boost package did not export ${boost_target}")' \
  '  endif()' \
  '  get_target_property(boost_type ${boost_target} TYPE)' \
  '  get_target_property(boost_location ${boost_target} IMPORTED_LOCATION_RELEASE)' \
  '  get_target_property(boost_links ${boost_target} INTERFACE_LINK_LIBRARIES)' \
  '  message(STATUS "SDK Boost target ${boost_target}: type=${boost_type}; release=${boost_location}; links=${boost_links}")' \
  'endforeach()' \
  >"${boost_probe_dir}/CMakeLists.txt"
boost_cmake_args=("${cmake_debug_args[@]}" -S "${boost_probe_dir}" -B "${boost_probe_dir}/build" \
  "-DCMAKE_BUILD_TYPE=${scc_build_type}" "${cmake_generator_args[@]}")
printf '  Boost dependency configure command: cmake'
printf ' %q' "${boost_cmake_args[@]}"
printf '\n'
cmake "${boost_cmake_args[@]}"
printf '%s\n' '  === Phase 2/3: configure the SCC consumer ==='
printf '%s\n' \
  'cmake_minimum_required(VERSION 3.20)' \
  'project(scc_probe LANGUAGES CXX)' \
  'find_package(SystemCLanguage CONFIG REQUIRED)' \
  'find_package(scc CONFIG REQUIRED)' \
  'add_executable(scc_probe main.cpp)' \
  'target_link_libraries(scc_probe PRIVATE SystemC::systemc)' \
  'if(TARGET scc::scc)' \
  '  target_link_libraries(scc_probe PRIVATE scc::scc)' \
  'elseif(TARGET scc)' \
  '  target_link_libraries(scc_probe PRIVATE scc)' \
  'else()' \
  '  message(FATAL_ERROR "scc package exports no supported target")' \
  'endif()' \
  >"${scc_probe_dir}/CMakeLists.txt"
printf '%s\n' \
  '#include <systemc>' \
  '#include <scc/report.h>' \
  'int sc_main(int, char**) { return 0; }' \
  >"${scc_probe_dir}/main.cpp"
scc_cmake_args=("${cmake_debug_args[@]}" -S "${scc_probe_dir}" -B "${scc_probe_dir}/build" \
  "-DCMAKE_BUILD_TYPE=${scc_build_type}" "${cmake_generator_args[@]}")
printf '  SCC consumer configure command: cmake'
printf ' %q' "${scc_cmake_args[@]}"
printf '\n'
cmake "${scc_cmake_args[@]}"
printf '%s\n' '  === Phase 3/3: build and link the SCC consumer ==='
printf '  SCC consumer build command: cmake --build %q --parallel\n' \
  "${scc_probe_dir}/build"
cmake --build "${scc_probe_dir}/build" --parallel
