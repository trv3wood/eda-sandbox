#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/regress-common.sh"

cmake_tool="$(tool_path EDA_TOOL_CMAKE cmake)"
cxx_tool="$(tool_path EDA_TOOL_CXX c++)"
require_tools "${cmake_tool}" "${cxx_tool}" find
scc_home="${EDA_SCC_HOME:?EDA_SCC_HOME must point to the SCC SDK}"
if [[ -d "${scc_home}/scc" ]]; then
  scc_prefix="${scc_home}/scc"
  scc_deps="${scc_home}/deps"
else
  scc_prefix="${scc_home}"
  scc_deps="${EDA_SCC_DEPS:?EDA_SCC_DEPS must point to SCC dependencies}"
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
printf '  CMake:   %s\n' "${cmake_tool}"
if command -v "$(tool_path EDA_TOOL_NINJA ninja)" >/dev/null 2>&1; then
  ninja_tool="$(tool_path EDA_TOOL_NINJA ninja)"
  printf '  Ninja:   %s\n' "${ninja_tool}"
else
  printf '  Ninja:   unavailable; using CMake default generator\n'
fi
printf '  SCC:     %s\n' "${scc_prefix}"
printf '  CMAKE_PREFIX_PATH: %s\n' "${CMAKE_PREFIX_PATH:-<unset>}"
printf '  LD_LIBRARY_PATH:   %s\n' "${LD_LIBRARY_PATH:-<unset>}"
# Rocky SDK 会随包归档 Conan generators；Ubuntu 镜像使用 CMake 的
# FindBoost module 查找部署后的头文件和库，不能强制要求 Boost Config。
boost_config="$(find "${scc_deps}" -type f \
  \( -iname 'boostconfig.cmake' -o -iname 'boost-config.cmake' \) -print -quit)"
printf '%s\n' '  Boost CMake package files:'
find "${scc_deps}" -type f \( \
  -iname 'boost*config.cmake' -o \
  -iname 'boost*targets*.cmake' \
\) -print | sort
if [[ -n "${boost_config}" ]]; then
  boost_find_package='find_package(Boost CONFIG REQUIRED)'
  printf '  Boost discovery mode: Config (%s)\n' "${boost_config}"
else
  boost_find_package='find_package(Boost REQUIRED COMPONENTS date_time filesystem stacktrace_backtrace)'
  printf '%s\n' '  Boost discovery mode: FindBoost module'
fi
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
# Rocky 的 Conan generators 按 Release 配置归档；Ubuntu 的 module-mode
# Boost 也使用相同构建类型，保持两个 SDK 的探针参数一致。
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
if command -v "$(tool_path EDA_TOOL_NINJA ninja)" >/dev/null 2>&1; then
  cmake_generator_args=(-G Ninja)
fi
printf '%s\n' '  === Phase 1/3: verify Boost date_time and filesystem ==='
printf '%s\n' \
  'cmake_minimum_required(VERSION 3.20)' \
  'project(scc_boost_probe LANGUAGES CXX)' \
  "${boost_find_package}" \
  'foreach(boost_target IN ITEMS Boost::date_time Boost::filesystem Boost::stacktrace_backtrace)' \
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
"${cmake_tool}" "${boost_cmake_args[@]}"
printf '%s\n' '  === Phase 2/3: configure the SCC consumer ==='
printf '%s\n' \
  'cmake_minimum_required(VERSION 3.20)' \
  'project(scc_probe LANGUAGES CXX)' \
  'find_package(lz4 CONFIG REQUIRED)' \
  'find_package(fmt CONFIG REQUIRED)' \
  'find_package(spdlog CONFIG REQUIRED)' \
  'find_package(yaml-cpp CONFIG REQUIRED)' \
  'find_package(BZip2 REQUIRED)' \
  'find_package(libbacktrace CONFIG REQUIRED)' \
  'find_package(zstd CONFIG REQUIRED)' \
  'foreach(dependency_target IN ITEMS LZ4::lz4_static lz4::lz4 fmt::fmt spdlog::spdlog yaml-cpp::yaml-cpp BZip2::BZip2 libbacktrace::libbacktrace zstd::libzstd_static)' \
  '  if(NOT TARGET ${dependency_target})' \
  '    message(FATAL_ERROR "SDK dependency package did not export ${dependency_target}")' \
  '  endif()' \
  '  get_target_property(dependency_location ${dependency_target} IMPORTED_LOCATION)' \
  '  get_target_property(dependency_links ${dependency_target} INTERFACE_LINK_LIBRARIES)' \
  '  message(STATUS "SDK dependency target ${dependency_target}: location=${dependency_location}; links=${dependency_links}")' \
  'endforeach()' \
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
"${cmake_tool}" "${scc_cmake_args[@]}"
printf '%s\n' '  === Phase 3/3: build and link the SCC consumer ==='
printf '  SCC consumer build command: cmake --build %q --parallel\n' \
  "${scc_probe_dir}/build"
"${cmake_tool}" --build "${scc_probe_dir}/build" --parallel
