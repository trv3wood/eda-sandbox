cmake_minimum_required(VERSION 3.20)
project(cycle_systemc_poc LANGUAGES CXX)

option(BUILD_SYSTEMC_POC "构建需要 SystemC 的 TLM PoC" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(model_core src/model.cpp)
target_include_directories(model_core PUBLIC include)
target_compile_options(model_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(model_tests tests/test_models.cpp)
target_link_libraries(model_tests PRIVATE model_core)

add_executable(model_benchmark tests/benchmark.cpp)
target_link_libraries(model_benchmark PRIVATE model_core)

enable_testing()
add_test(NAME model_equivalence COMMAND model_tests)

if(BUILD_SYSTEMC_POC)
  find_package(SystemCLanguage CONFIG QUIET)
  if(NOT TARGET SystemC::systemc)
    find_path(SYSTEMC_INCLUDE_DIR NAMES systemc REQUIRED)
    find_library(SYSTEMC_LIBRARY NAMES systemc REQUIRED)
    add_library(SystemC::systemc UNKNOWN IMPORTED)
    set_target_properties(SystemC::systemc PROPERTIES
      IMPORTED_LOCATION "${SYSTEMC_LIBRARY}"
      INTERFACE_INCLUDE_DIRECTORIES "${SYSTEMC_INCLUDE_DIR}"
    )
  endif()
  add_library(tlm_adapter src/tlm_adapter.cpp)
  target_include_directories(tlm_adapter PUBLIC include)
  target_link_libraries(tlm_adapter PUBLIC model_core SystemC::systemc)
  target_compile_options(tlm_adapter PRIVATE -Wall -Wextra -Wpedantic)

  add_executable(tlm_tests tests/test_tlm.cpp)
  target_link_libraries(tlm_tests PRIVATE tlm_adapter SystemC::systemc)
  add_test(NAME tlm_contract COMMAND tlm_tests)

  add_library(stream_accumulator_sc src/stream_accumulator_sc.cpp)
  target_include_directories(stream_accumulator_sc PUBLIC include)
  target_link_libraries(stream_accumulator_sc PUBLIC SystemC::systemc)
  target_compile_options(stream_accumulator_sc PRIVATE -Wall -Wextra -Wpedantic)
endif()
