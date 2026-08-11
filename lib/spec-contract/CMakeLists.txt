# The frozen capability-spec contract LEAF (M5  D1, ). The BOTTOM of the dependency graph:
# value model (), the typed expr AST + lowerings (), the LifecycleModel (), the
# AttestationPolicy (), JSON + the stable sha256 hash (JsonUtil), and the pure string-case
# utilities (StrCase, moved out of View.cpp in  so a leaf-only renderer can name from the spec).
# Links ONLY MLIRSupport (llvm)
# — NO MLIR dialect, NO View.h, NO renderer/backend policy — so a backend/policy module can depend on
# it WITHOUT the monolithic NeutrinoEmit or the ProcedureView surface. NeutrinoDialect links it PUBLIC
# so its symbols reach all dependents; `spec-contract-smoke` (CTest) proves it is usable standalone.
add_mlir_library(NeutrinoSpecContract
  ValueModel.cpp
  JsonUtil.cpp
  AgreementEnvelope.cpp
  CoordinationEnvelope.cpp
  Expr.cpp
  Lifecycle.cpp
  Attestation.cpp
  CoordinationPlan.cpp
  CanonicalLabels.cpp
  BackendProjection.cpp
  BackendProjectionCodec.cpp
  BackendProtocol.cpp
  BackendStartup.cpp
  BackendPackage.cpp
  BackendInvoker.cpp
  BackendDispatchReceipt.cpp
  ArtifactPublication.cpp
  CoordinationEval.cpp
  BoundedCoordinator.cpp
  SemanticRequirements.cpp
  TraceEquivalence.cpp
  StrCase.cpp
  SelfEmittedSpec.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  MLIRSupport
)

#  Family-D: the finalized-projection schema and the codec ownership map
# are BUILD PRODUCTS, not committed sources.
#
# The generator previously omitted ProjectionGateMode.h from its declared
# inputs, so it could not resolve PlanGateMode and refused -- which read as a
# missing frozen mapping but was a missing INPUT. PlanGateMode already exists in
# the authoritative headers and in the committed codec artifact; naming its
# enum-owner header is what lets the generator reproduce them. Nothing about the
# wire mapping changes.
#
# The schema candidate is byte-compared against the committed installable
# schema, so byte-identical regeneration is the proof that semantics did not
# change.
set(_finalized_projection_generated_dir
  ${CMAKE_CURRENT_BINARY_DIR}/generated)
set(_finalized_projection_schema_candidate
  ${_finalized_projection_generated_dir}/finalized-projection-v1.schema.json)
set(_backend_projection_codec_fields
  ${_finalized_projection_generated_dir}/BackendProjectionCodecFields.inc)
add_custom_command(
  OUTPUT
    ${_finalized_projection_schema_candidate}
    ${_backend_projection_codec_fields}
  COMMAND ${CMAKE_COMMAND} -E make_directory
    ${_finalized_projection_generated_dir}
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/scripts/generators/gen_finalized_projection_schema.py
    --header ${PROJECT_SOURCE_DIR}/include/Neutrino/BackendProjection.h
    --coordination-header
      ${PROJECT_SOURCE_DIR}/include/Neutrino/CoordinationPlan.h
    --gate-mode-header
      ${PROJECT_SOURCE_DIR}/include/Neutrino/ProjectionGateMode.h
    --output ${_finalized_projection_schema_candidate}
    --codec-fields-output ${_backend_projection_codec_fields}
  COMMAND ${CMAKE_COMMAND} -E compare_files
    ${_finalized_projection_schema_candidate}
    ${PROJECT_SOURCE_DIR}/docs/schemas/finalized-projection-v1.schema.json
  DEPENDS
    ${PROJECT_SOURCE_DIR}/include/Neutrino/BackendProjection.h
    ${PROJECT_SOURCE_DIR}/include/Neutrino/CoordinationPlan.h
    ${PROJECT_SOURCE_DIR}/include/Neutrino/ProjectionGateMode.h
    ${PROJECT_SOURCE_DIR}/docs/schemas/finalized-projection-v1.schema.json
    ${PROJECT_SOURCE_DIR}/scripts/generators/gen_finalized_projection_schema.py
  COMMENT "Generating finalized-projection schema and codec fields ( D)"
  VERBATIM)
add_custom_target(finalized-projection-generated
  DEPENDS
    ${_finalized_projection_schema_candidate}
    ${_backend_projection_codec_fields})

add_dependencies(NeutrinoSpecContract finalized-projection-generated)
target_include_directories(NeutrinoSpecContract PRIVATE
  ${_finalized_projection_generated_dir})
set_source_files_properties(BackendProjectionCodec.cpp PROPERTIES
  OBJECT_DEPENDS
    "${_backend_projection_codec_fields};${_finalized_projection_schema_candidate}")
