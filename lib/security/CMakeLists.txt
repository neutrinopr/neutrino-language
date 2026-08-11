# Public-core security model: builds the security report and dispatch decision
# from the frozen capability-spec. The policy library links only the contract
# leaf; the core adapter links analysis without making the policy model depend
# on ProcedureView or a backend renderer.
add_mlir_library(NeutrinoSecurityPolicy
  GenSecuritySpec.cpp
  SecurityAdmission.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)
target_include_directories(NeutrinoSecurityPolicy PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR})

# The target adapter is a public-core composition layer. It converts the
# verified in-memory view to the frozen spec and delegates every security
# decision to the standalone policy target above.
add_mlir_library(NeutrinoSecurityCore
  SecurityTarget.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoAnalysis
  NeutrinoSecurityPolicy
)

# The smoke links only NeutrinoSecurityPolicy. A dependency on the core adapter,
# emit registry, or a backend therefore fails at link time.
add_executable(security-policy-smoke test/security_policy_smoke.cpp)
target_link_libraries(security-policy-smoke PRIVATE NeutrinoSecurityPolicy)
set(_neutrino_core_security_fixture
  ${PROJECT_SOURCE_DIR}/test/core/security/insecure-capability-spec.json)
neutrino_register_test(NAME security-policy-smoke COMMAND security-policy-smoke
  ${_neutrino_core_security_fixture})
if(NEUTRINO_CORE_ONLY)
  neutrino_register_test_properties(security-policy-smoke
    PROPERTIES LABELS "contract;core-only;ctest-native")
else()
  neutrino_register_test_properties(security-policy-smoke
    PROPERTIES LABELS "contract;ctest-native")
endif()
