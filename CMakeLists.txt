cmake_minimum_required(VERSION 3.20)
project(neutrino-mlir LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Required by clang-tidy.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(MLIR REQUIRED CONFIG)

message(STATUS "Using MLIRConfig.cmake in: ${MLIR_DIR}")
message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")

list(APPEND CMAKE_MODULE_PATH "${MLIR_CMAKE_DIR}")
list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")

include(TableGen)
include(AddLLVM)
include(AddMLIR)
include(HandleLLVMOptions)

# LLVM defaults RTTI and exceptions off.
add_compile_options(-fexceptions -frtti)

# Developer instrumentation is opt-in and uses isolated build trees.
option(NEUTRINO_ENABLE_ASAN "Build our targets with AddressSanitizer (developer lane)" OFF)
option(NEUTRINO_ENABLE_UBSAN "Build our targets with UndefinedBehaviorSanitizer (developer lane)" OFF)
option(NEUTRINO_ENABLE_COVERAGE "Build our targets with clang source-based coverage (developer lane)" OFF)
option(NEUTRINO_CORE_ONLY
  "Configure the backend- and production-domain-free public core graph" OFF)

set(_neutrino_instrument_flags "")
if(NEUTRINO_ENABLE_ASAN)
  # Recovery lets sanitizer suites report beyond the first finding.
  list(APPEND _neutrino_instrument_flags
    -fsanitize=address -fsanitize-recover=address -fno-omit-frame-pointer)
endif()
if(NEUTRINO_ENABLE_UBSAN)
  # Recovery lets sanitizer suites report beyond the first finding.
  list(APPEND _neutrino_instrument_flags
    -fsanitize=undefined -fsanitize-recover=undefined -fno-omit-frame-pointer)
endif()
if(NEUTRINO_ENABLE_COVERAGE)
  list(APPEND _neutrino_instrument_flags -fprofile-instr-generate -fcoverage-mapping)
endif()
if(_neutrino_instrument_flags)
  message(STATUS "Neutrino developer instrumentation: ${_neutrino_instrument_flags}")
  add_compile_options(${_neutrino_instrument_flags})
  add_link_options(${_neutrino_instrument_flags})
endif()

include_directories(${LLVM_INCLUDE_DIRS})
include_directories(${MLIR_INCLUDE_DIRS})
include_directories(${PROJECT_SOURCE_DIR}/include)
include_directories(${PROJECT_BINARY_DIR}/include)

# Generate the build identity header.
find_package(Git QUIET)
set(NEUTRINO_GIT_SHA "unknown")
if(Git_FOUND)
  execute_process(
    COMMAND ${GIT_EXECUTABLE} rev-parse --short=12 HEAD
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
    OUTPUT_VARIABLE _neutrino_git_sha
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET)
  if(_neutrino_git_sha)
    set(NEUTRINO_GIT_SHA "${_neutrino_git_sha}")
  endif()
endif()
set(NEUTRINO_BUILD_TARGET "${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}")
configure_file(
  ${PROJECT_SOURCE_DIR}/include/Neutrino/BuildInfo.h.in
  ${PROJECT_BINARY_DIR}/include/Neutrino/BuildInfo.h
  @ONLY)
link_directories(${LLVM_BUILD_LIBRARY_DIR})
add_definitions(${LLVM_DEFINITIONS})

# lib/ subdirectories register tests, so enable testing first.
enable_testing()

# The publication snapshot exposes one closed, source-complete test surface.
set(NEUTRINO_PUBLIC_TESTS
  public-pack-receipts
  public-pack-receipts-selftest
  public-pack-resolver
  spec-contract-smoke
  lines-fixture-render
  lines-fixture-td-mutation
  framed-lines-fixture-render
  framed-lines-fixture-td-mutation-header
  framed-lines-fixture-td-mutation-item
  framed-lines-fixture-td-mutation-footer
  framed-lines-fixture-td-mutation-placeholder
  security-policy-smoke
  coverage-spec-smoke
  slot-spec-smoke
  views-spec-smoke
  capability-profile-smoke
  solidity-recipe-provider-test
  solidity-recipe-render-referee
  solidity-optional-extent-test
  solidity-localdecl-golden
  solidity-localdecl-td-mutation
  solidity-import-golden
  solidity-import-td-mutation
  solidity-raw-seam-sealed.PROBE_AGGREGATE
  solidity-raw-seam-sealed.PROBE_MUTATION
  solidity-raw-seam-sealed.PROBE_CTOR_PROBE_COMPLETION)

function(neutrino_register_test)
  cmake_parse_arguments(PUBLIC "" "NAME" "" ${ARGN})
  if(NOT PUBLIC_NAME)
    message(FATAL_ERROR "publication test registration requires NAME")
  endif()
  list(FIND NEUTRINO_PUBLIC_TESTS "${PUBLIC_NAME}" _public_test_index)
  if(NOT _public_test_index EQUAL -1)
    add_test(${ARGV})
  endif()
endfunction()

function(neutrino_register_test_properties)
  # Publication validation is intentionally unfiltered.  The retained tests do
  # not require per-test environment or fixture state, so legacy labels and
  # scheduling metadata are outside this snapshot's executable contract.
endfunction()

# Resolve an architect-curated release member from the pack-only corpus manifest.
# Callers use the frozen member ordinal; external identities remain confined to
# the manifest/registry authorities rather than backend or test configuration.
function(neutrino_curated_pack_member index out_var)
  file(READ "${PROJECT_SOURCE_DIR}/docs/m6-curated-example-corpus.json" _corpus)
  string(JSON _member GET "${_corpus}" examples ${index})
  string(JSON _pack_path GET "${_corpus}" packs "${_member}" packPath)
  if(IS_ABSOLUTE "${_pack_path}")
    set(_root "${_pack_path}")
  else()
    set(_root "${PROJECT_SOURCE_DIR}/${_pack_path}")
  endif()
  if(NOT EXISTS "${_root}/pack.json")
    message(FATAL_ERROR
      "curated pack ${index} is not hydrated at ${_root}; "
      "checkout the manifest-pinned pack repository first")
  endif()
  set(${out_var} "${_root}" PARENT_SCOPE)
endfunction()

add_subdirectory(include/Neutrino)
add_subdirectory(lib)
add_subdirectory(tools/neutrino-opt)
add_subdirectory(tools/neutrino-translate)
add_subdirectory(tools/neutrino-emit)
add_subdirectory(tools/neutrino-gen)
add_subdirectory(tools/neutrino-bundle)
add_subdirectory(tools/neutrino-equiv)
if(NOT NEUTRINO_CORE_ONLY)
  add_dependencies(neutrino-gen neutrino-solidity-repository-package)
  add_dependencies(neutrino-bundle neutrino-solidity-repository-package)
  add_dependencies(neutrino-equiv neutrino-solidity-repository-package)
endif()

# : reconcile the real configured PostgreSQL mutation-copy inputs after
# package moves.  This reads the generated Ninja graph, so it checks the paths
# the build will execute rather than maintaining a parallel source-path ledger.
if(NOT NEUTRINO_CORE_ONLY)
  add_custom_target(postgres-mutation-input-reconciliation
    COMMAND python3
      ${PROJECT_SOURCE_DIR}/scripts/gates/check_postgres_mutation_inputs.py
      --selftest
    COMMAND python3
      ${PROJECT_SOURCE_DIR}/scripts/gates/check_postgres_mutation_inputs.py
      --build-dir ${CMAKE_BINARY_DIR}
      --source-root ${PROJECT_SOURCE_DIR}
    DEPENDS ${PROJECT_SOURCE_DIR}/scripts/gates/check_postgres_mutation_inputs.py
    COMMENT "Reconciling configured PostgreSQL mutation inputs ()"
    VERBATIM)
endif()

# Test orchestration lives in focused modules.
if(NEUTRINO_CORE_ONLY)
  set(NEUTRINO_CORE_INSTALLED_EXPORT_MANIFEST
    "${PROJECT_SOURCE_DIR}/docs/m7-core-installed-export.json")
  include(cmake/NeutrinoCoreOnly.cmake)
else()
  include(cmake/NeutrinoTests.cmake)
endif()

include(cmake/NeutrinoPublicationTests.cmake)
