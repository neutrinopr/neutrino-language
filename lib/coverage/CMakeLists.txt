# Public-core coverage model. The report renderer consumes only the frozen
# capability-spec and the shared value-model contract.
add_mlir_library(NeutrinoCoverageSpec
  GenCoverageSpec.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)

# The target adapter is public-core composition: it turns the verified view into
# the frozen spec before delegating to the standalone coverage model.
add_mlir_library(NeutrinoCoverageCore
  CoverageTarget.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoAnalysis
  NeutrinoCoverageSpec
)
if(NOT NEUTRINO_CORE_ONLY)
  target_sources(NeutrinoCoverageCore PRIVATE
    full/CoverageBackendMaturity.cpp)
  target_include_directories(NeutrinoCoverageCore PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/full)
endif()

# This smoke links only the spec-driven coverage model. A dependency on the
# adapter, emit registry, production domains, or a backend therefore fails at
# link time.
add_executable(coverage-spec-smoke test/coverage_spec_smoke.cpp)
target_link_libraries(coverage-spec-smoke PRIVATE NeutrinoCoverageSpec)
set(_neutrino_core_coverage_fixture
  ${PROJECT_SOURCE_DIR}/test/core/coverage/capability-spec.json)
neutrino_register_test(NAME coverage-spec-smoke COMMAND coverage-spec-smoke
  ${_neutrino_core_coverage_fixture})
if(NEUTRINO_CORE_ONLY)
  neutrino_register_test_properties(coverage-spec-smoke
    PROPERTIES LABELS "contract;core-only;ctest-native")
else()
  neutrino_register_test_properties(coverage-spec-smoke
    PROPERTIES LABELS "contract;ctest-native")
endif()
