# Capability-profile model construction is a target-neutral projection of the
# frozen capability spec and verified package profiles. The standalone smoke
# keeps this leaf free of ProcedureView and backend renderer dependencies.
add_mlir_library(NeutrinoCapabilityProfile
  GenCapabilityModelSpec.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)

# Link-smoke (M5  D5, ; co-located here : links ONLY NeutrinoCapabilityProfile, so a leaky carve fails to
# LINK (the target graph enforces the D5 boundary). Builds the capability model from a committed spec.)
add_executable(capability-profile-smoke test/capability_profile_smoke.cpp)
target_link_libraries(capability-profile-smoke PRIVATE NeutrinoCapabilityProfile)
neutrino_register_test(NAME capability-profile-smoke COMMAND capability-profile-smoke)
neutrino_register_test_properties(capability-profile-smoke PROPERTIES LABELS "contract;ctest-native")
