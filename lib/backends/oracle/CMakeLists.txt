# Oracle-consensus OFF-CHAIN observer backend (M5 oracle S4, ): renders the deterministic serverless
# observers + aggregation from the frozen attestation policy () + an observation binding. Leaf-only
# — reads only the spec JSON + binding JSON + the AttestationPolicy leaf contract, no ProcedureView. The
# `oracle-observer` entry that threads the binding in stays in NeutrinoEmit. `oracle-observer-smoke`
# proves it standalone.
add_mlir_library(NeutrinoBackendOracle
  GenOracleObserverSpec.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
  NeutrinoCodeText
)

# Link-smoke (M5 oracle S4, ; co-located here : links ONLY NeutrinoBackendOracle, so a leaky carve fails to
# LINK. Renders observers from an in-memory attestation policy + binding (self-contained — no spec arg).)
add_executable(oracle-observer-smoke test/oracle_observer_smoke.cpp)
target_link_libraries(oracle-observer-smoke PRIVATE NeutrinoBackendOracle)
neutrino_register_test(NAME oracle-observer-smoke COMMAND oracle-observer-smoke)
neutrino_register_test_properties(oracle-observer-smoke PROPERTIES LABELS "contract;ctest-native")
