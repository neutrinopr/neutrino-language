# Heavy provisioning / e2e acceptance tests (, residual of ).
#
# These need external toolchains (solc, forge, a Postgres via docker) that a
# per-PR build box need not have, so they are REGISTERED here with ownership +
# heaviness labels and SKIP (exit 77) at run time when their tool is absent —
# they are never silently dropped. The recipe lives once in test/acceptance/run.sh;
# the Makefile targets are thin `ctest -R …` wrappers over these tests.
#
# Selecting them:
#   ctest -L acceptance                      # every heavy test (skips what it can't provision)
#   ctest -L e2e                             # the cross-backend / full-pipeline subset
#   ctest -L backend-solidity -LE requires-solc   # the light Solidity surface only
#   ctest -LE 'requires-solc|requires-forge|requires-postgres|requires-docker'   # bare box
#
# Label vocabulary (enforced by scripts/gates/check_ctest_labels.py):
#   ownership : backend-solidity | backend-postgres | slot | policy
#   heaviness : acceptance (needs provisioning) | e2e (spans >1 backend / full loop)
#   provision : requires-solc | requires-forge | requires-postgres | requires-docker
set(NEUTRINO_ACCEPTANCE_DIR "${CMAKE_BINARY_DIR}/acceptance")

# neutrino_acceptance(NAME <ctest-name> KIND <run.sh-kind>
#   [PACK_RESOLVER <receipt-verified resolver>] LABELS <labels>)
#
# A `requires-forge` row additionally carries the DECLARED Forge tool identity () as a CTest
# ENVIRONMENT property, so `ctest -L acceptance` on a bare shell drives exactly the configured
# forge/solc with the configured native-library prefix — the identity is not an ambient export
# and every launch route (direct forge, the goldens checker, neutrino-equiv) inherits the same one.
function(neutrino_acceptance)
  cmake_parse_arguments(A "" "NAME;KIND;PACK_RESOLVER" "LABELS" ${ARGN})
  neutrino_register_test(NAME ${A_NAME}
    COMMAND bash ${PROJECT_SOURCE_DIR}/test/acceptance/run.sh
      ${A_KIND} $<TARGET_FILE:neutrino-gen> ${NEUTRINO_ACCEPTANCE_DIR}
      ${A_PACK_RESOLVER})
  # 77 = tool absent -> reported SKIPPED, not passed or failed.
  neutrino_register_test_properties(${A_NAME} PROPERTIES LABELS "${A_LABELS}" SKIP_RETURN_CODE 77)
  if("requires-forge" IN_LIST A_LABELS)
    neutrino_register_test_properties(${A_NAME} PROPERTIES
      ENVIRONMENT "${NEUTRINO_FORGE_TEST_ENVIRONMENT}")
  endif()
endfunction()

neutrino_acceptance(NAME acceptance-solidity KIND solidity
  LABELS "backend-solidity;requires-solc;requires-forge;acceptance")
neutrino_acceptance(NAME acceptance-solidity-explicit-time KIND solidity-explicit-time
  LABELS "backend-solidity;requires-solc;requires-forge;acceptance")
neutrino_acceptance(NAME acceptance-solidity-reference KIND solidity-reference
  LABELS "backend-solidity;requires-solc;requires-forge;acceptance")
neutrino_acceptance(NAME acceptance-oracle-coordination KIND oracle-coordination
  LABELS "backend-solidity;requires-solc;requires-forge;acceptance")
neutrino_acceptance(NAME acceptance-oracle-temporal KIND oracle-temporal
  LABELS "backend-solidity;requires-solc;requires-forge;acceptance")
neutrino_acceptance(NAME acceptance-curated-solidity KIND curated-solidity
  LABELS "backend-solidity;requires-solc;requires-forge;acceptance")
# The run.sh KIND was renamed compliant-transfer -> core-compliance-guard when the domain was
# externalized (029579fa); this registration kept the old KIND and the row failed with
# `unknown kind` — a broken launch route, not a conformance result (). The ctest NAME is the
# frozen row identity (Makefile target, CI selections), so only the KIND is corrected.
neutrino_acceptance(NAME acceptance-compliant-transfer KIND core-compliance-guard
  LABELS "backend-solidity;backend-postgres;requires-solc;requires-forge;requires-postgres;requires-docker;acceptance;e2e")
neutrino_acceptance(NAME acceptance-postgres-quorum-guard KIND postgres-quorum-guard
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-postgres-temporal-migration KIND postgres-temporal-migration
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-postgres-temporal KIND postgres-temporal
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-curated-postgres KIND curated-postgres
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-cross-border KIND cross-border
  PACK_RESOLVER ${PROJECT_SOURCE_DIR}/test/acceptance/resolve_cross_border_packs.py
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-db KIND db
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-postgres-balance-scope KIND postgres-balance-scope
  LABELS "backend-postgres;requires-postgres;requires-docker;acceptance")
neutrino_acceptance(NAME acceptance-equivalence KIND equivalence
  LABELS "backend-solidity;backend-postgres;requires-solc;requires-forge;acceptance;e2e")
neutrino_acceptance(NAME acceptance-equivalence-scheme KIND equivalence-scheme
  LABELS "backend-solidity;backend-postgres;requires-solc;requires-forge;acceptance;e2e")
