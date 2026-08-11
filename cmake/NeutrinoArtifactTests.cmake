# The historical sample-artifact target remains as a developer-facing name, but
# its authority is pack-only after : it validates the frozen corpus and
# resolves every receipted member instead of traversing a core domain tree.
add_custom_target(generate-sample-artifacts
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_m6_curated_example_corpus.py
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/m6_pack_resolver.py
    --repo ${PROJECT_SOURCE_DIR}
    --manifest ${PROJECT_SOURCE_DIR}/docs/m6-curated-example-corpus.json
  COMMENT "Validate and hydrate the receipted curated pack corpus"
  VERBATIM)

# Golden artifact drift tests.
set_property(GLOBAL PROPERTY NEUTRINO_GOLDEN_OUTPUTS "")
function(neutrino_golden)
  cmake_parse_arguments(G "SCENARIO_FREE" "NAME;DOMAIN;PACK_INDEX;TARGET;SUBDIR;FIELDSCRIPT" "FILES" ${ARGN})
  if(NOT DEFINED G_PACK_INDEX OR "${G_PACK_INDEX}" STREQUAL "")
    message(FATAL_ERROR "golden ${G_NAME} must name a receipted curated PACK_INDEX")
  endif()
  neutrino_curated_pack_member(${G_PACK_INDEX} _base)
  file(GLOB _sources CONFIGURE_DEPENDS "${_base}/source/*.neu")
  file(GLOB _scenarios CONFIGURE_DEPENDS "${_base}/scenario/*.json")
  list(LENGTH _sources _source_count)
  list(LENGTH _scenarios _scenario_count)
  if(NOT _source_count EQUAL 1 OR NOT _scenario_count EQUAL 1)
    message(FATAL_ERROR
      "curated pack ${G_PACK_INDEX} must have one source and one scenario")
  endif()
  list(GET _sources 0 _src)
  list(GET _scenarios 0 _scn)
  set(_gold ${_base}/generated/${G_SUBDIR})
  foreach(_f "${_src}" "${_gold}")
    if(NOT EXISTS "${_f}")
      message(FATAL_ERROR "S5e (): missing input/golden for ${G_NAME}: ${_f}")
    endif()
  endforeach()
  set(_out ${CMAKE_BINARY_DIR}/generated-goldens/${G_NAME})
  list(GET G_FILES 0 _first)
  set(_marker ${_out}/${_first})
  # Clean output directories prevent stale byproducts from passing.
  set(_rest ${G_FILES})
  list(REMOVE_AT _rest 0)
  set(_byproducts "")
  foreach(_bf ${_rest})
    list(APPEND _byproducts ${_out}/${_bf})
  endforeach()
  if(G_SCENARIO_FREE)
    add_custom_command(OUTPUT ${_marker} BYPRODUCTS ${_byproducts}
      COMMAND ${CMAKE_COMMAND} -E rm -rf ${_out}
      COMMAND ${CMAKE_COMMAND} -E make_directory ${_out}
      COMMAND $<TARGET_FILE:neutrino-gen> --target=${G_TARGET} ${_src} -o ${_out}
      DEPENDS neutrino-gen ${_src}
      COMMENT "S5e generate ${G_TARGET}: ${G_NAME}" VERBATIM)
  else()
    if(NOT EXISTS "${_scn}")
      message(FATAL_ERROR "S5e (): missing scenario for ${G_NAME}: ${_scn}")
    endif()
    add_custom_command(OUTPUT ${_marker} BYPRODUCTS ${_byproducts}
      COMMAND ${CMAKE_COMMAND} -E rm -rf ${_out}
      COMMAND ${CMAKE_COMMAND} -E make_directory ${_out}
      COMMAND $<TARGET_FILE:neutrino-gen> --target=${G_TARGET} --scenario=${_scn} ${_src} -o ${_out}
      DEPENDS neutrino-gen ${_src} ${_scn}
      COMMENT "S5e generate ${G_TARGET}: ${G_NAME}" VERBATIM)
  endif()
  set_property(GLOBAL APPEND PROPERTY NEUTRINO_GOLDEN_OUTPUTS ${_marker})
  # Keep the file list in one add_test argument.
  string(REPLACE ";" "|" _filesarg "${G_FILES}")
  set(_args -DGEN=${_out} -DGOLD=${_gold} -DFILES=${_filesarg})
  if(G_FIELDSCRIPT)
    list(APPEND _args -DFIELDSCRIPT=${PROJECT_SOURCE_DIR}/test/cmake/${G_FIELDSCRIPT})
  endif()
  neutrino_register_test(NAME ${G_NAME}
    COMMAND ${CMAKE_COMMAND} ${_args} -P ${PROJECT_SOURCE_DIR}/test/cmake/golden_diff.cmake)
  neutrino_register_test_properties(${G_NAME} PROPERTIES FIXTURES_REQUIRED NEUTRINO_GOLDENS LABELS "golden;ctest-native")
endfunction()

set(_slot_files capability.json operations.json compensation.json transcript.json
                envelope.schema.json capability.lock)
# Slot is scenario-free; the remaining generators consume scenarios.
neutrino_golden(NAME golden-slot-soa DOMAIN curated-3 PACK_INDEX 3 TARGET slot SUBDIR slot
  SCENARIO_FREE FILES ${_slot_files})
# The v0.1 static-fact capability goldens were retired by the catalog-derived
# v1 contract. Exact v1 shape, profile binding, and deterministic bytes are
# enforced by capability_claims.test against an independent verified catalog.
neutrino_golden(NAME golden-coverage-soa DOMAIN curated-3 PACK_INDEX 3 TARGET coverage
  SUBDIR coverage FILES coverage.json)
# M5 signature domain ( slice 4): the three cross-border legs surface their oracle trust boundary +
# authority bindings — byte-golden + PER-DOMAIN field-pinned (each pins its OWN observer set + M, and the
# damage leg pins the named Insurer→reserve_debit authority), so a producer+golden co-drift is caught.
# Evidence-only cross-border logistics milestone: an effectless coordination whose security posture is
# the oracle trust boundary alone (no value/settlement leg), pinned to its OWN observer set + M so a
# producer+golden co-drift on the logistics oracle set or threshold is caught.

get_property(_golden_outputs GLOBAL PROPERTY NEUTRINO_GOLDEN_OUTPUTS)
add_custom_target(generate-golden-artifacts DEPENDS ${_golden_outputs})
# Build the shared generation fixture once before drift comparisons.
neutrino_register_test(NAME golden-artifacts-setup
  COMMAND ${CMAKE_COMMAND} --build ${CMAKE_BINARY_DIR} --target generate-golden-artifacts)
neutrino_register_test_properties(golden-artifacts-setup PROPERTIES FIXTURES_SETUP NEUTRINO_GOLDENS LABELS "golden")

# The architect-curated release corpus is a single committed authority shared by
# the per-backend golden slices and the later comprehensive release gate.
neutrino_register_test(NAME curated-solidity-goldens
  COMMAND python3 ${PROJECT_SOURCE_DIR}/test/curated/check_solidity_goldens.py
    --repo ${PROJECT_SOURCE_DIR}
    --gen $<TARGET_FILE:neutrino-gen>
    --profile ${PROJECT_SOURCE_DIR}/examples/target-profiles/solidity.target-profile.json
    --work ${CMAKE_BINARY_DIR}/curated-solidity-goldens
    --selftest)
neutrino_register_test_properties(curated-solidity-goldens PROPERTIES
  LABELS "golden;ctest-native;backend-solidity;contract;completeness")

# The architect-curated PostgreSQL lane consumes the single frozen corpus
# manifest and verifies the production source/spec paths against committed bytes.
neutrino_register_test(NAME curated-postgres-goldens
  COMMAND python3 ${PROJECT_SOURCE_DIR}/test/curated/check_postgres_goldens.py
    --repo ${PROJECT_SOURCE_DIR}
    --gen $<TARGET_FILE:neutrino-gen>
    --profile ${PROJECT_SOURCE_DIR}/examples/target-profiles/postgres.target-profile.json
    --work ${CMAKE_BINARY_DIR}/curated-postgres-goldens)
neutrino_register_test_properties(curated-postgres-goldens PROPERTIES
  LABELS "golden;ctest-native;backend-postgres;contract;completeness")

neutrino_register_test(NAME curated-postgres-goldens-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/test/curated/check_postgres_goldens.py
    --repo ${PROJECT_SOURCE_DIR} --selftest)
neutrino_register_test_properties(curated-postgres-goldens-selftest PROPERTIES
  LABELS "golden;ctest-native;backend-postgres;contract;completeness")

# The positive release gate composes the compiler-owned semantic-requirements
# projection, target-relative profiles, exact curated backend witnesses, and
# canonical sem(plan) pair/mutation proof.
neutrino_register_test(NAME m6-positive-release-gate
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_m6_release_gate.py
    --gen $<TARGET_FILE:neutrino-gen>
    --work ${CMAKE_BINARY_DIR}/m6-positive-release-gate)
neutrino_register_test_properties(m6-positive-release-gate PROPERTIES
  LABELS "release;ctest-native;contract;completeness")

neutrino_register_test(NAME m6-positive-release-gate-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_m6_release_gate.py
    --selftest)
neutrino_register_test_properties(m6-positive-release-gate-selftest PROPERTIES
  LABELS "release;ctest-native;contract;completeness")
