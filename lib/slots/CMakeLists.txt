# Public-core slot model over the frozen capability contract.
add_mlir_library(NeutrinoSlotSpec
  GenSlotSpec.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)

# Public-core registry adapter. Full profiles append bundled backend claims in
# a source file that is not compiled or exported by core-only configurations.
add_mlir_library(NeutrinoSlotCore
  SlotTarget.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoAnalysis
  NeutrinoSlotSpec
)
# Standalone typed-API witness. Its only library dependency is the target-
# neutral slot model.
add_executable(slot-spec-smoke test/slot_spec_smoke.cpp)
target_link_libraries(slot-spec-smoke PRIVATE NeutrinoSlotSpec)
set(_neutrino_core_slot_fixture
  ${PROJECT_SOURCE_DIR}/test/core/slots/capability-spec.json)
neutrino_register_test(NAME slot-spec-smoke COMMAND slot-spec-smoke
  ${_neutrino_core_slot_fixture})
if(NEUTRINO_CORE_ONLY)
  neutrino_register_test_properties(slot-spec-smoke
    PROPERTIES LABELS "contract;core-only;ctest-native")
else()
  neutrino_register_test_properties(slot-spec-smoke
    PROPERTIES LABELS "contract;ctest-native")
endif()
