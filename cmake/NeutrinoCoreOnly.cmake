neutrino_register_test(NAME core-only-contract-validator
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/scripts/validators/validate_capability_spec.py
    --selftest)
neutrino_register_test_properties(core-only-contract-validator
  PROPERTIES LABELS "core-only")

set(_neutrino_core_export_checker
  ${PROJECT_SOURCE_DIR}/scripts/gates/check_core_only_export.py)
set(_neutrino_core_export_policy
  ${PROJECT_SOURCE_DIR}/docs/m7-core-export-overlays.json)
set(_neutrino_core_export_report
  ${PROJECT_BINARY_DIR}/core-only-export-report.json)

file(READ "${NEUTRINO_CORE_INSTALLED_EXPORT_MANIFEST}"
  _neutrino_core_installed_export)
string(JSON _neutrino_core_export_kind GET
  "${_neutrino_core_installed_export}" kind)
if(NOT _neutrino_core_export_kind STREQUAL
    "neutrino.m7-core-installed-export/1")
  message(FATAL_ERROR "unsupported core installed-export manifest")
endif()

foreach(_key publicTargets publicHeaders cmakeExports)
  string(JSON _count LENGTH "${_neutrino_core_installed_export}" ${_key})
  if(NOT _count EQUAL 0)
    message(FATAL_ERROR
      "signed backend protocol forbids installed C++ ABI surface: ${_key}")
  endif()
endforeach()

neutrino_register_test(NAME core-only-export-selftest
  COMMAND python3 ${_neutrino_core_export_checker} --selftest)
neutrino_register_test_properties(core-only-export-selftest
  PROPERTIES LABELS "core-only")

neutrino_register_test(NAME core-only-runtime
  COMMAND python3 ${_neutrino_core_export_checker}
    --check-runtime
    --source-root ${PROJECT_SOURCE_DIR}
    --build-dir ${PROJECT_BINARY_DIR})
neutrino_register_test_properties(core-only-runtime
  PROPERTIES LABELS "core-only")

# The release receipt carries the artifact identity that cannot live in a tracked
# file (). Emission itself belongs to the release flow, but its refusals and
# its determinism are exercised here so they cannot rot between releases.
set(_neutrino_core_receipt_emitter
  ${PROJECT_SOURCE_DIR}/scripts/release/emit_core_release_receipt.py)
neutrino_register_test(NAME core-only-release-receipt-selftest
  COMMAND python3 ${_neutrino_core_receipt_emitter} --selftest)
neutrino_register_test_properties(core-only-release-receipt-selftest
  PROPERTIES LABELS "core-only")

add_custom_target(core-only-runtime-inputs
  DEPENDS
    ${_neutrino_core_export_checker}
    ${_neutrino_core_export_policy}
    ${NEUTRINO_CORE_INSTALLED_EXPORT_MANIFEST}
    ${PROJECT_SOURCE_DIR}/docs/schemas/m7-core-export-overlays.schema.json
    ${PROJECT_SOURCE_DIR}/docs/schemas/m7-core-export-report.schema.json
    ${PROJECT_SOURCE_DIR}/docs/schemas/m7-core-installed-export.schema.json
    ${PROJECT_SOURCE_DIR}/docs/schemas/m7-core-release-receipt.schema.json
    ${_neutrino_core_receipt_emitter}
    ${PROJECT_SOURCE_DIR}/scripts/validators/validate_capability_spec.py
    ${PROJECT_SOURCE_DIR}/scripts/validators/validate_test_realization.py
    ${PROJECT_SOURCE_DIR}/test/core/coverage/capability-spec.json
    ${PROJECT_SOURCE_DIR}/test/core/security/insecure-capability-spec.json
    ${PROJECT_SOURCE_DIR}/test/core/slots/capability-spec.json
    ${PROJECT_SOURCE_DIR}/test/core/views/capability-spec.json
    ${PROJECT_SOURCE_DIR}/test/core/views/generated/LeftActor.json
    ${PROJECT_SOURCE_DIR}/test/core/views/generated/RightActor.json
    ${PROJECT_SOURCE_DIR}/test/core/views/source.neu
    ${PROJECT_SOURCE_DIR}/test/ir/coordination_trace.neu
    ${PROJECT_SOURCE_DIR}/test/ir/coordination_trace.scn.json)

add_custom_target(core-only
  COMMAND ${CMAKE_CTEST_COMMAND} --output-on-failure -L core-only
  DEPENDS
    neutrino-opt
    neutrino-translate
    neutrino-emit
    neutrino-gen
    neutrino-bundle
    neutrino-equiv
    # The five leaf-module link-smokes. Each links ONLY its own leaf, so a leaky
    # carve fails to LINK and the target graph enforces the boundary.
    # capability-profile-smoke was the one omission, and it is the root of the
    # stale-declaration cluster this entrypoint exposed: because the module was
    # never built here, its sources never entered the core-only build graph, so
    # the derived export never saw NeutrinoCapabilityProfile or
    # GenCapabilityModelSpec.h and both drifted out of the declared closure
    # unnoticed. Including it makes that drift structurally impossible rather
    # than merely corrected.
    capability-profile-smoke
    coverage-spec-smoke
    security-policy-smoke
    slot-spec-smoke
    views-spec-smoke
    core-only-runtime-inputs
  COMMENT "Building and validating the backend-free Neutrino core"
  VERBATIM)

install(TARGETS neutrino-opt neutrino-translate neutrino-emit neutrino-gen
                neutrino-bundle neutrino-equiv
  RUNTIME DESTINATION bin
  COMPONENT NeutrinoCore)
install(FILES
  ${PROJECT_SOURCE_DIR}/docs/process/M7_BACKEND_PACKAGE_BOUNDARY_ADR.md
  DESTINATION share/neutrino/docs
  COMPONENT NeutrinoCore)
# The shape contract travels with the installation it describes, so a consumer
# holding only a prefix can read which paths are declared and that no C++ ABI is
# exported. Installed verbatim: the release receipt's installedExportSha256 is
# taken over this file, and verify_installed_export refuses any drift between
# the source manifest and this copy. Identity stays out of it -- artifact digests
# live in the release receipt, never here (see M7_CORE_RELEASE_RECEIPT.md).
install(FILES
  ${NEUTRINO_CORE_INSTALLED_EXPORT_MANIFEST}
  DESTINATION share/neutrino
  COMPONENT NeutrinoCore)
install(FILES
  ${PROJECT_SOURCE_DIR}/docs/schemas/agreement-identity.schema.json
  ${PROJECT_SOURCE_DIR}/docs/schemas/capability-spec-validation.schema.json
  ${PROJECT_SOURCE_DIR}/docs/schemas/capability-spec.schema.json
  ${PROJECT_SOURCE_DIR}/docs/schemas/finalized-projection-v1.schema.json
  ${PROJECT_SOURCE_DIR}/docs/schemas/semantic-requirements.schema.json
  ${PROJECT_SOURCE_DIR}/docs/schemas/test-realization.schema.json
  DESTINATION share/neutrino/schemas
  COMPONENT NeutrinoCore)

add_custom_target(core-only-export-manifest
  COMMAND python3 ${_neutrino_core_export_checker}
    --derive
    --source-root ${PROJECT_SOURCE_DIR}
    --build-dir ${PROJECT_BINARY_DIR}
    --policy ${_neutrino_core_export_policy}
    --installed-export ${NEUTRINO_CORE_INSTALLED_EXPORT_MANIFEST}
    --output ${_neutrino_core_export_report}
  DEPENDS core-only
  COMMENT "Deriving the exact core export from configured build/install inputs"
  VERBATIM)

add_custom_target(core-only-export-check
  COMMAND python3 ${_neutrino_core_export_checker}
    --check-candidate
    --source-root ${PROJECT_SOURCE_DIR}
    --build-dir ${PROJECT_BINARY_DIR}
    --report ${_neutrino_core_export_report}
  DEPENDS core-only-export-manifest
  COMMENT "Rebuilding from the exact backend-free core candidate"
  VERBATIM)
