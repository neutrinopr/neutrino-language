# M5  subproject layout (). Backend/policy/contract modules live in EXPLICIT source-tree
# subprojects so the dependency boundary is visible in the folder layout, not only in CMake target
# names. Dependency direction is strictly downward (nothing lower references something higher):
#
#   lib/spec-contract/               NeutrinoSpecContract   (the frozen capability-spec contract LEAF)
#     ^
#   NeutrinoDialect (here)           (the MLIR dialect/verifiers + scenario + textual emit + metadata)
#     ^
#   NeutrinoAnalysis (here)          (ProcedureView + validation + security analysis)
#     ^
#   lib/backends/{solidity,postgres,oracle}/  NeutrinoBackend{Solidity,Postgres,Oracle}   (leaf-only)
#   lib/slots/                       NeutrinoSlotSpec / NeutrinoSlotCore (public core)
#   lib/coverage/                    NeutrinoCoverageSpec / NeutrinoCoverageCore (public core)
#   lib/security/                    NeutrinoSecurityPolicy / NeutrinoSecurityCore (public core)
#   lib/policy/capability-profile/   NeutrinoCapabilityProfile (leaf-only)
#     ^
#   NeutrinoFrontend / NeutrinoTooling / NeutrinoEmit (here)   (parse / run-tooling / backend entries)
#
# Each subproject owns a local CMakeLists.txt (the target declaration lives next to its sources). The
# leaf-only backend/policy modules (//) link ONLY the contract leaf — no ProcedureView, no
# sibling backend — which the per-module link-smokes + the renderer-include-lock composition gate
# () enforce. PUBLIC HEADERS stay in include/Neutrino/ (the single public-API surface every tool +
# module includes); moving them would only relocate the shared surface, not sharpen the boundary — the
# .cpp OWNERSHIP + the CMake dependency edges are what the folder layout now makes obvious.

if(NEUTRINO_CORE_ONLY)
  add_compile_definitions(NEUTRINO_CORE_ONLY=1)
endif()

# --- the contract leaf (bottom of the graph) ---
add_subdirectory(spec-contract)

# --- the language-neutral code-emitter leaf (): generic block/line/blank mechanics, no target
#     semantics; a sibling leaf (links only llvm Support), so backends depend on it without a
#     backend-to-backend edge. Foundation for the  emitter migrations. ---
if(NOT NEUTRINO_CORE_ONLY)
  add_subdirectory(codetext)
endif()

# --- the generic backend-idiom recipe runtime leaf (/): domain-blind +
#     target-blind recipe schema/validation, FinalizedIdiomKey, provider ABI,
#     exact-key resolution, generic traversal, and stable diagnostics. Links
#     only MLIRSupport (a sibling leaf like codetext); backends depend on it
#     without a backend-to-backend edge. ---
if(NOT NEUTRINO_CORE_ONLY)
  add_subdirectory(recipe)
endif()

# --- core: dialect / analysis / tooling / frontend (link the leaf; consumed by the emit layer) ---
add_mlir_dialect_library(NeutrinoDialect
  NeutrinoDialect.cpp
  ExprAttr.cpp
  LanguageMetadata.cpp
  LanguageVocabulary.cpp
  DiagnosticTaxonomy.cpp
  Emit.cpp
  Scenario.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoOpsIncGen

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
  MLIRIR
  MLIRSupport
)

# --- the generic L2 domain-semantics meta-model dialect (): ODS-declared
#     records + fail-closed verifiers. A STANDALONE dialect — rigid backends
#     never link it (the visible sidecar is not a backend input,  §7). ---
add_mlir_dialect_library(NeutrinoL2
  L2Dialect.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoL2IncGen

  LINK_LIBS PUBLIC
  MLIRIR
  MLIRSupport
)

# --- the visible L2 domain-semantics target entry (): serializes a verified
#     l2.domain to deterministic, hashed JSON. The target entry lives at
#     targets/*Target.cpp per the  convention; it is ISOLATED from the
#     backend emit layer — the sidecar is a sibling, never a backend input
#     ( §7), so it links the L2 dialect + the JSON/hash leaf, NOTHING
#     backend-shaped. ---
add_mlir_library(NeutrinoDomainSemantics
  targets/DomainSemanticsTarget.cpp
  L2Reduction.cpp
  L2Imports.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoL2IncGen

  LINK_LIBS PUBLIC
  NeutrinoL2
  NeutrinoSpecContract
  MLIRIR
)

# Semantic analysis: ProcedureView (the DTO built from MLIR) + the Capability Security Pass / scenario
# validation. The emitters consume ProcedureView, so this is a mid-layer below them. (LifecycleModel
# lives in the NeutrinoSpecContract leaf, ; NeutrinoAnalysis reaches it transitively via the dialect.)
add_mlir_library(NeutrinoAnalysis
  View.cpp
  Validate.cpp
  Analysis.cpp
  LifecycleView.cpp
  CoordinationPlanBuild.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoOpsIncGen

  LINK_LIBS PUBLIC
  NeutrinoDialect
)

# Run tooling: the per-run manifest + diagnostics writers (run context / artifact metadata).
# Used only by the artifact-producing tools (neutrino-gen / -bundle / -equiv).
add_mlir_library(NeutrinoTooling
  Manifest.cpp
  Diagnostics.cpp
  SpecLegality.cpp
  PlanLegality.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoOpsIncGen

  LINK_LIBS PUBLIC
  NeutrinoDialect
)

# Front-end: lexing/parsing/source-mapping (.neu -> MLIR). Depends on the core dialect (+ Expr, in the
# leaf, shared with the emitters). Used only by the .neu-parsing tools (neutrino-translate / -gen / -emit / -equiv).
add_mlir_library(NeutrinoFrontend
  Frontend.cpp
  FrontendDeclarations.cpp
  FrontendEntries.cpp
  FrontendParser.cpp
  FrontendPolicy.cpp
  Lexer.cpp
  ParseUtil.cpp
  SourceLoad.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoOpsIncGen

  LINK_LIBS PUBLIC
  NeutrinoDialect
  MLIRParser
)

# Security is retained public core. Its policy model is target-neutral and its
# adapter is part of the core composition graph.
add_subdirectory(security)
# Coverage is retained public core with the same spec-model/core-adapter split.
add_subdirectory(coverage)
# Slots are retained public core; backend claims remain full-profile-only.
add_subdirectory(slots)
# Views are retained public core; both the participant projection model and
# its target adapter are backend- and domain-neutral.
add_subdirectory(views)
# Target capability models are a backend-neutral projection of verified package
# profiles and remain available in a core-only build.
add_subdirectory(policy/capability-profile)

# --- leaf-only backend/policy subprojects (each links ONLY the contract leaf) ---
if(NOT NEUTRINO_CORE_ONLY)
  add_subdirectory(backends/solidity)
  add_subdirectory(backends/postgres)
  add_subdirectory(backends/oracle)
endif()

# Verified package discovery and the external-only catalog are backend-free.
# The full in-process catalog wrapper remains in TargetRegistry.cpp.
add_mlir_library(NeutrinoTargetCatalog
  emit/TargetCatalog.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoOpsIncGen

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)

# NeutrinoEmit composes the retained core target adapters with optional
# backend/package entries. Public-core target adapters live in their owning
# units and are linked here; optional entries remain source members only in
# full configurations.
add_mlir_library(NeutrinoEmit
  targets/AgreementIdentityTarget.cpp
  targets/CapabilitySpecTarget.cpp
  targets/CoordinationPlanTarget.cpp
  targets/SemanticRequirementsTarget.cpp
  targets/CoordinationTraceTarget.cpp
  targets/TestRealizationTarget.cpp
  emit/TargetRegistry.cpp

  PARTIAL_SOURCES_INTENDED

  DEPENDS
  NeutrinoOpsIncGen

  LINK_LIBS PUBLIC
  NeutrinoAnalysis
  NeutrinoCoverageCore
  NeutrinoCapabilityProfile
  NeutrinoSecurityCore
  NeutrinoSlotCore
  NeutrinoTargetCatalog
  NeutrinoViewsCore
)
if(NOT NEUTRINO_CORE_ONLY)
  target_sources(NeutrinoEmit PRIVATE
    targets/PostgresTarget.cpp)
  target_link_libraries(NeutrinoEmit PUBLIC
    NeutrinoBackendPostgres
    NeutrinoBackendOracle)
endif()
#  R1: targets/PostgresTarget.cpp #includes the moved model/PostgresModel.h,
# whose sibling includes are bare (PgSqlText.h, PostgresTargetEnums.inc,
# PostgresTargetNodes.inc, PostgresRecipeBuilders.decl.inc) — byte-identical to
# the pre- flat header, where they resolved as flat siblings. NeutrinoBackend-
# Postgres carries these package subdirs PRIVATE, so they do not propagate to this
# external consumer; add them to NeutrinoEmit's own include path so the bare
# includes resolve (the  package move otherwise left this TU unable to compile).
if(NOT NEUTRINO_CORE_ONLY)
  target_include_directories(NeutrinoEmit PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/backends/postgres/model
    ${PROJECT_BINARY_DIR}/lib/backends/postgres/generated
    ${CMAKE_CURRENT_SOURCE_DIR}/backends/postgres/provider
    ${CMAKE_CURRENT_SOURCE_DIR}/backends/postgres/leaf)
  add_dependencies(obj.NeutrinoEmit postgres-target-registry-inc
    postgres-recipe-builders-inc)
endif()
