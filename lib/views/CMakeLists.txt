# Per-participant views rendered FROM the frozen capability-spec (M5  X1, ; Trust lane T5). A
# spec-renderer LEAF: `generateParticipantViewsFromSpec` consumes only the capability-spec JSON (
# contract) — NO ProcedureView, NO View.h/Analysis.h, NO NeutrinoEmit — so it is independently linkable
# and M6-extractable. Links ONLY the contract leaf. The registry ENTRY `ViewsTarget.cpp` stays in
# NeutrinoEmit (it does the pre-waist view->spec production) and links this. `views-spec-smoke` proves it
# renders the views from a committed spec standalone.
add_mlir_library(NeutrinoViewsSpec
  GenViewsSpec.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)

# Public-core adapter: turn the verified in-memory procedure into the canonical
# capability contract, then delegate all participant projection to the
# target-neutral model.
add_mlir_library(NeutrinoViewsCore
  ViewsTarget.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoAnalysis
  NeutrinoViewsSpec
)

# This smoke links only the spec-driven views model. A dependency on the
# adapter, registry, production domains, oracle, or a backend fails at link
# time. Exact fixture bytes bind source labels and capability identity.
add_executable(views-spec-smoke test/views_spec_smoke.cpp)
target_link_libraries(views-spec-smoke PRIVATE NeutrinoViewsSpec)
set(_neutrino_core_views_fixture
  ${PROJECT_SOURCE_DIR}/test/core/views/capability-spec.json)
set(_neutrino_core_views_expected
  ${PROJECT_SOURCE_DIR}/test/core/views/generated)
neutrino_register_test(NAME views-spec-smoke COMMAND views-spec-smoke
  ${_neutrino_core_views_fixture} ${_neutrino_core_views_expected})
if(NEUTRINO_CORE_ONLY)
  neutrino_register_test_properties(views-spec-smoke
    PROPERTIES LABELS "contract;core-only;ctest-native")
else()
  neutrino_register_test_properties(views-spec-smoke
    PROPERTIES LABELS "contract;ctest-native")
endif()
