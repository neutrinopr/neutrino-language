# Solidity backend (M5  D2, ): the spec -> Solidity/Foundry renderer, an INDEPENDENT backend
# that links ONLY the contract leaf () — no ProcedureView (View.h), no other backend
# (postgres/slot/security/capability-profile/oracle). GenSoliditySpec consumes only the frozen spec JSON
# (Expr/ValueModel from the leaf, the View.h-free Realization value) and renders the contract + the
# spec-sourced Foundry harness () inline. Core has no Solidity registry
# entry; the verified external package protocol owns the projection -> renderer
# process boundary.
# `backend-solidity-smoke` proves it is usable standalone against the leaf alone. Split by concern
# (): GenSoliditySpec = the coordination contract; GenSolidityTest = the Foundry harness;
# GenSolidityQuorumGuard = the reviewed M-of-N acceptance guard (/); SolidityEmit = the shared
# type/escape/operand helpers. Output is byte-identical (the lit Solidity/oracle goldens prove it).
#  A1+B1: the generated Solidity .inc are build products, not committed
# sources. They are produced into ${CMAKE_CURRENT_BINARY_DIR}/generated and the
# consumers include that directory; nothing regenerates into the source tree and
# there is no committed copy left to drift from, so the former byte-compare
# freshness checks are structurally unnecessary rather than merely removed.
set(_solidity_generated_dir ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${_solidity_generated_dir})

set(_solidity_recipes_inc ${CMAKE_CURRENT_BINARY_DIR}/solidity_recipes.inc)
set(_solidity_target_nodes_inc ${_solidity_generated_dir}/SolidityTargetNodes.inc)
set(_solidity_printer_handlers_inc
  ${_solidity_generated_dir}/SolidityPrinterHandlers.inc)
set(_solidity_target_enums_inc ${_solidity_generated_dir}/SolidityTargetEnums.inc)
set(_solidity_recipe_builders_inc
  ${_solidity_generated_dir}/SolidityRecipeBuilders.inc)
set(_solidity_projection_inc ${_solidity_generated_dir}/SolidityProjection.inc)
set(_solidity_emit_builder_decls_inc
  ${_solidity_generated_dir}/SolidityEmitBuilderDecls.inc)
set(_solidity_emit_builders_inc
  ${_solidity_generated_dir}/SolidityEmitBuilders.inc)

# A1: the X-macro registry trio. One generator run emits all three, so they share
# a single command with all three listed as OUTPUT.
add_custom_command(
  OUTPUT ${_solidity_target_nodes_inc}
         ${_solidity_printer_handlers_inc}
         ${_solidity_target_enums_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    --td ${CMAKE_CURRENT_SOURCE_DIR}/model/SolidityTargetNodes.td
    --out ${_solidity_target_nodes_inc}
    --printer-out ${_solidity_printer_handlers_inc}
    --enums-out ${_solidity_target_enums_inc}
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
  DEPENDS model/SolidityTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
  COMMENT "Generating Solidity target-node registry ( A1)")
add_custom_target(solidity-target-registry-inc
  DEPENDS ${_solidity_target_nodes_inc}
          ${_solidity_printer_handlers_inc}
          ${_solidity_target_enums_inc})
add_custom_command(OUTPUT ${_solidity_recipes_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/SolidityIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --symbol solidity
    -o ${_solidity_recipes_inc}
  DEPENDS recipes/SolidityIdiomRecipes.td
          recipes/SolidityEvidenceIdiomRecipes.td
          recipes/SolidityTemporalIdiomRecipes.td
          recipes/SolidityEffectfulIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
  COMMENT "Generating Solidity recipe module ()")
add_custom_target(solidity-recipes-inc DEPENDS ${_solidity_recipes_inc})
add_custom_command(OUTPUT ${_solidity_recipe_builders_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile solidity-recipe-adapter
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/SolidityIdiomRecipes.td
    --target-td ${CMAKE_CURRENT_SOURCE_DIR}/model/SolidityTargetNodes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    -o ${_solidity_recipe_builders_inc}
  DEPENDS recipes/SolidityIdiomRecipes.td recipes/SolidityEvidenceIdiomRecipes.td
          recipes/SolidityTemporalIdiomRecipes.td
          recipes/SolidityEffectfulIdiomRecipes.td
          model/SolidityTargetNodes.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
  COMMENT "Generating Solidity recipe builders (,  B1)")
add_custom_target(solidity-recipe-builders-inc
  DEPENDS ${_solidity_recipe_builders_inc})
#  R5b A.2: the generated finalized-view dispatch resolver
# (SolidityProjection.inc), produced from the Solidity-local projection schema +
# target model. Since  B1 it is a build product with no committed copy, so
# freshness is a build dependency rather than a byte-compare.
add_custom_command(OUTPUT ${_solidity_projection_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile solidity-projection
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/SolidityProjectionSchema.td
    --target-td ${CMAKE_CURRENT_SOURCE_DIR}/model/SolidityTargetNodes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    -o ${_solidity_projection_inc}
  DEPENDS recipes/SolidityProjectionSchema.td
          model/SolidityTargetNodes.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
  COMMENT "Generating Solidity projection resolver ( R5b,  B1)")
add_custom_target(solidity-projection-inc
  DEPENDS ${_solidity_projection_inc})
add_custom_command(
  OUTPUT ${_solidity_emit_builder_decls_inc}
         ${_solidity_emit_builders_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile solidity-emit-builders
    --td ${CMAKE_CURRENT_SOURCE_DIR}/model/SolidityTargetNodes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --decls ${_solidity_emit_builder_decls_inc}
    --defs ${_solidity_emit_builders_inc}
  DEPENDS model/SolidityTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
  COMMENT "Generating Solidity Emit builders (,  B1)")
add_custom_target(solidity-emit-builders-inc
  DEPENDS ${_solidity_emit_builder_decls_inc}
          ${_solidity_emit_builders_inc})
# The render-pair harness is compiled by many targets. Make the canonical
# handler an object dependency once so none of those targets can race the
# registry producer.
set_source_files_properties(test/solidity_stmt_shell_render_harness.cpp
  PROPERTIES OBJECT_DEPENDS ${_solidity_printer_handlers_inc})
neutrino_register_test(NAME solidity-emit-builder-schema
  COMMAND python3
    ${CMAKE_CURRENT_SOURCE_DIR}/test/solidity_emit_builder_schema_test.py
    --repo ${PROJECT_SOURCE_DIR}
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen)
neutrino_register_test_properties(solidity-emit-builder-schema PROPERTIES
  LABELS "contract;fast")
neutrino_register_test(NAME solidity-clean-clone-manifest
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/packaging/solidity/scripts/check_clean_clone.py
    --selftest)
neutrino_register_test_properties(solidity-clean-clone-manifest PROPERTIES
  LABELS "contract;fast")
set_source_files_properties(provider/SolidityRecipeProvider.cpp PROPERTIES
  OBJECT_DEPENDS "${_solidity_recipes_inc};${_solidity_projection_inc}")

add_mlir_library(NeutrinoBackendSolidity
  provider/GenSoliditySpec.cpp
  provider/SolidityTargetValidation.cpp
  provider/SolidityTargetAdapter.cpp
  provider/SolidityRenderer.cpp
  provider/SolidityRecipeProvider.cpp
  harness/GenSolidityTest.cpp
  #  security carve-out consumer: stays at the backend root (flat) so the
  #  registry's allowedConsumers path is untouched by this structural move.
  GenSolidityQuorumGuard.cpp
  provider/SolidityEmit.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
  NeutrinoCodeText
  NeutrinoRecipe
)
add_dependencies(NeutrinoBackendSolidity solidity-recipes-inc
  solidity-target-registry-inc solidity-recipe-builders-inc
  solidity-projection-inc solidity-emit-builders-inc)
# Structural subdirs ( R1): the generated .inc live under generated/, the
# provider/harness .cpp/.h under provider/ and harness/, and the two
# carve-out .sol.inc stay at the backend root. Put all of them plus the build
# dir (for the generated solidity_recipes.inc) on the include path so the bare
# `#include "..."` directives in the moved sources still resolve unchanged.
target_include_directories(NeutrinoBackendSolidity PRIVATE
  ${CMAKE_CURRENT_BINARY_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${_solidity_generated_dir}
  ${CMAKE_CURRENT_SOURCE_DIR}/provider)

# : materialize the separately linked Solidity package into the build
# tree's installed-layout discovery root. Ordinary build-tree consumers then
# traverse the same verified descriptor/startup/protocol seam as installed
# packages; the core target registry and emit library retain no Solidity edge.
add_executable(neutrino-solidity-repository-backend
  ${PROJECT_SOURCE_DIR}/packaging/solidity/src/SolidityBackendMain.cpp)
set_target_properties(neutrino-solidity-repository-backend PROPERTIES
  OUTPUT_NAME neutrino-solidity-backend)
target_include_directories(neutrino-solidity-repository-backend PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${_solidity_generated_dir}
  ${CMAKE_CURRENT_SOURCE_DIR}/provider)
target_link_libraries(neutrino-solidity-repository-backend PRIVATE
  NeutrinoBackendSolidity NeutrinoSpecContract)

set(NEUTRINO_SOLIDITY_REPOSITORY_PACKAGE_DIR
  "${CMAKE_BINARY_DIR}/tools/lib/neutrino/backend-packages/solidity"
  CACHE INTERNAL "Verified build-tree Solidity backend package")
set(_solidity_repository_descriptor
  "${NEUTRINO_SOLIDITY_REPOSITORY_PACKAGE_DIR}/backend-package.json")
set(_solidity_repository_entry
  "${NEUTRINO_SOLIDITY_REPOSITORY_PACKAGE_DIR}/bin/neutrino-solidity-backend")
add_custom_command(
  OUTPUT ${_solidity_repository_descriptor} ${_solidity_repository_entry}
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/packaging/solidity/scripts/check_clean_clone.py
    --materialize-package
    --binary $<TARGET_FILE:neutrino-solidity-repository-backend>
    --package-dir ${NEUTRINO_SOLIDITY_REPOSITORY_PACKAGE_DIR}
  DEPENDS
    neutrino-solidity-repository-backend
    ${PROJECT_SOURCE_DIR}/packaging/solidity/scripts/check_clean_clone.py
    ${PROJECT_SOURCE_DIR}/packaging/solidity/extraction-manifest.json
    finalized-projection-generated
    ${PROJECT_SOURCE_DIR}/examples/target-profiles/solidity.target-profile.json
  VERBATIM)
add_custom_target(neutrino-solidity-repository-package ALL
  DEPENDS ${_solidity_repository_descriptor} ${_solidity_repository_entry})
set_source_files_properties(harness/GenSolidityTest.cpp PROPERTIES
  NEUTRINO_SEMANTIC_AUTHORITY_ROLE scenario-harness)
set_source_files_properties(provider/SolidityRecipeProvider.cpp PROPERTIES
  NEUTRINO_SEMANTIC_AUTHORITY_ROLE recipe-provider-plumbing)
neutrino_curated_pack_member(0 _curated_supply_issue)
neutrino_curated_pack_member(5 _curated_contested)
neutrino_curated_pack_member(6 _curated_deadline)

# Link-smoke (M5  D2, ; co-located here ): proves NeutrinoBackendSolidity is usable
# STANDALONE — this executable links ONLY that backend (not NeutrinoEmit / NeutrinoAnalysis / other
# backends). A leaky carve (the Solidity renderer reaching a ProcedureView / spec-producer / other-backend
# symbol) would fail to LINK, so the target graph enforces the D2 boundary. Renders the contract from a
# committed capability-spec through the backend's public spec->Solidity entry point.
add_executable(backend-solidity-smoke test/backend_solidity_smoke.cpp)
target_link_libraries(backend-solidity-smoke PRIVATE NeutrinoBackendSolidity)
neutrino_register_test(NAME backend-solidity-smoke COMMAND backend-solidity-smoke
  ${_curated_contested}/generated/capability-spec/capability-spec.json
  ${_curated_contested}/generated/solidity/src/CoreContestedResolution.sol)
neutrino_register_test_properties(backend-solidity-smoke PROPERTIES LABELS "contract;ctest-native")

# : target-model unit test — asserts on the graph-derived target structure (attestation gating,
# replay, balanced obligation, terminal transition, nested  guard), not on printed bytes (the goldens
# pin those). Links only NeutrinoBackendSolidity, so it also proves the model TU stays leaf-only.
add_executable(solidity-model-test test/solidity_model_test.cpp)
target_include_directories(solidity-model-test PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/provider ${_solidity_generated_dir})
target_link_libraries(solidity-model-test PRIVATE NeutrinoBackendSolidity)
neutrino_register_test(NAME solidity-model-test COMMAND solidity-model-test
  ${_curated_contested}/generated/capability-spec/capability-spec.json
  ${PROJECT_SOURCE_DIR}/test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json
  ${_curated_deadline}/generated/capability-spec/capability-spec.json)
neutrino_register_test_properties(solidity-model-test PROPERTIES LABELS "contract;ctest-native")

#  Batch B: the real generated package resolves all three exact guard
# consumer keys through one registered provider and yields the five typed roots.
add_executable(solidity-recipe-provider-test
  test/solidity_recipe_provider_test.cpp)
target_include_directories(solidity-recipe-provider-test PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/provider ${_solidity_generated_dir})
target_link_libraries(solidity-recipe-provider-test PRIVATE
  NeutrinoBackendSolidity NeutrinoRecipe)
neutrino_register_test(NAME solidity-recipe-provider-test
  COMMAND solidity-recipe-provider-test)
neutrino_register_test_properties(solidity-recipe-provider-test PROPERTIES
  LABELS "contract;ctest-native;fast")

#  R5b A.1: a dialect-free REFEREE that drives the REAL Solidity recipe
# provider's finalized-view trio (project/slotExtent/slotItemOrder) through the
# shared RecipeInterpreter and pins the rendered bytes. Hand-built
# CoordinationPlans -> projectBackendGraph -> consumeFinalizedProjectionSequence
# -> materialize*ContractRecipe (the exposed entry points that run
# materializeRecipe over the generated module) -> renderSolidityProjection,
# compared against a committed deterministic golden. This is the byte-render
# baseline A.2 (the trio retirement) will byte-prove against. Links only
# NeutrinoBackendSolidity (+ its transitive NeutrinoSpecContract/NeutrinoRecipe)
# — no neutrino-gen / NeutrinoAnalysis / NeutrinoDialect.
add_executable(solidity-recipe-render-referee
  test/solidity_recipe_render_referee.cpp)
target_include_directories(solidity-recipe-render-referee PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/provider ${_solidity_generated_dir})
target_link_libraries(solidity-recipe-render-referee PRIVATE
  NeutrinoBackendSolidity NeutrinoRecipe)
neutrino_register_test(NAME solidity-recipe-render-referee
  COMMAND solidity-recipe-render-referee
    ${CMAKE_CURRENT_SOURCE_DIR}/test/solidity_recipe_render_referee_golden.txt)
neutrino_register_test_properties(solidity-recipe-render-referee PROPERTIES
  LABELS "contract;ctest-native;fast")

#  item 3: the generated optional-slot extent resolver maps each presence
# ordinal to the correct 0/1 extent from present/absent finalized fields.
add_executable(solidity-optional-extent-test
  test/solidity_optional_extent_test.cpp)
add_dependencies(solidity-optional-extent-test solidity-recipes-inc)
target_include_directories(solidity-optional-extent-test PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/provider ${_solidity_generated_dir}
  ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(solidity-optional-extent-test PRIVATE
  NeutrinoBackendSolidity NeutrinoRecipe)
neutrino_register_test(NAME solidity-optional-extent-test
  COMMAND solidity-optional-extent-test)
neutrino_register_test_properties(solidity-optional-extent-test PROPERTIES
  LABELS "contract;ctest-native;fast")

# Delete one of the two generated interface signatures.  The real generator
# must reject the nested many(2,2) result before C++ compilation.
neutrino_register_test(NAME solidity-recipe-signature-cardinality
  COMMAND python3
    ${CMAKE_CURRENT_SOURCE_DIR}/test/solidity_recipe_cardinality_test.py
    --repo ${PROJECT_SOURCE_DIR}
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen)
neutrino_register_test_properties(solidity-recipe-signature-cardinality PROPERTIES
  LABELS "contract;fast")

# /: END-TO-END proof that a GENERATED shell handler drives production
# rendering. One render harness (a minimal SolStmt shim + the generated printer
# include, linking only NeutrinoCodeText — no backend link) is compiled against TWO
# includes per node:
#   * the COMMITTED SolidityPrinterHandlers.inc -> must reproduce the golden line;
#   * a .td-MUTATED regenerated include (the node's syntax record mutated, produced
#     by the real generator under pinned llvm-tblgen) -> must render the mutated
#     form and FAIL the golden. So mutating the node's syntax record changes
#     production output.
# Parameterized over the node (LocalDecl 2a, Assign 2b, CompoundAssign 2c,
# DocComment ): the harness selects operands/expected via the _define
# (-DNODE_ASSIGN / -DNODE_COMPOUND / -DNODE_DOCCOMMENT); the drivers switch on
# -DNODE for the node-specific committed/mutated template + expected render.
function(add_stmt_shell_proof _node _lc _define _golden)
  set(_work ${CMAKE_CURRENT_BINARY_DIR}/${_lc}_mutation)
  set(_mut_inc ${_work}/mutated_printer.inc)

  # Committed-include harness: consumes the checked-in generated handler.
  # (The source path is spelled literally in both add_executable() calls so the
  # extraction-manifest gate's textual scan sees it compiled.)
  add_executable(solidity-${_lc}-render-committed test/solidity_stmt_shell_render_harness.cpp)
  target_compile_definitions(solidity-${_lc}-render-committed PRIVATE
    "NODE_INC=\"${_solidity_generated_dir}/SolidityPrinterHandlers.inc\"" ${_define})
  target_link_libraries(solidity-${_lc}-render-committed PRIVATE NeutrinoCodeText)
  neutrino_register_test(NAME solidity-${_lc}-golden
    COMMAND solidity-${_lc}-render-committed ${_golden})
  neutrino_register_test_properties(solidity-${_lc}-golden PROPERTIES LABELS "contract;ctest-native")

  # Regenerate the printer include from a .td whose node syntax record is mutated.
  add_custom_command(OUTPUT ${_mut_inc}
    COMMAND ${CMAKE_COMMAND}
      -DNODE=${_node}
      -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
      -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/SolidityTargetNodes.td
      -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
      -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
      -DWORK=${_work}
      -DOUT=${_mut_inc}
      -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_stmt_shell_inc.cmake
    DEPENDS model/SolidityTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
            ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
            ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_stmt_shell_inc.cmake
    COMMENT "Regenerating a .td-mutated ${_node} printer include ()")
  add_custom_target(solidity-${_lc}-mutated-inc DEPENDS ${_mut_inc})

  # Mutated-include harness: same source, compiled against the regenerated include.
  add_executable(solidity-${_lc}-render-mutated test/solidity_stmt_shell_render_harness.cpp)
  add_dependencies(solidity-${_lc}-render-mutated solidity-${_lc}-mutated-inc)
  target_compile_definitions(solidity-${_lc}-render-mutated PRIVATE
    "NODE_INC=\"${_mut_inc}\"" ${_define})
  target_link_libraries(solidity-${_lc}-render-mutated PRIVATE NeutrinoCodeText)

  # The pair driver: committed render must match the golden, mutated must fail it.
  neutrino_register_test(NAME solidity-${_lc}-td-mutation COMMAND ${CMAKE_COMMAND}
    -DNODE=${_node}
    -DCOMMITTED=$<TARGET_FILE:solidity-${_lc}-render-committed>
    -DMUTATED=$<TARGET_FILE:solidity-${_lc}-render-mutated>
    -DGOLDEN=${_golden}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_stmt_shell_render_pair.cmake)
  neutrino_register_test_properties(solidity-${_lc}-td-mutation PROPERTIES LABELS "contract;ctest-native")
endfunction()

add_stmt_shell_proof(LocalDecl localdecl ""
  ${PROJECT_SOURCE_DIR}/test/ir/evidence/golden/solidity/src/ShipmentEvidenceAnchor.sol)
add_stmt_shell_proof(Assign assign "NODE_ASSIGN"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(CompoundAssign compound "NODE_COMPOUND"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(DocComment doccomment "NODE_DOCCOMMENT"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(SpdxLicense spdx "NODE_SPDX"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(Pragma pragma "NODE_PRAGMA"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
# The temporal `import "./CoordinationEnvelope.sol";` directive is not carried by any
# committed src golden (the temporal contract is generated on the fly by the
# oracle lit tests), so this proof pins the exact production import line via a
# byte-faithful source-unit-header golden fixture.
add_stmt_shell_proof(Import import "NODE_IMPORT"
  ${PROJECT_SOURCE_DIR}/lib/backends/solidity/test/import_source_unit_golden.sol)
add_stmt_shell_proof(EnumDecl enum "NODE_ENUM"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(StorageDecl storage "NODE_STORAGE"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(EventDecl event "NODE_EVENT"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(FunctionSig functionsig "NODE_FUNCTIONSIG"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(ContractShell contractshell "NODE_CONTRACTSHELL"
  ${_curated_supply_issue}/generated/solidity/src/CoreSupplyIssue.sol)
add_stmt_shell_proof(InterfaceSignature interfacesig "NODE_INTERFACESIG"
  ${_curated_contested}/generated/solidity/src/CoreContestedResolution.sol)
add_stmt_shell_proof(InterfaceShell interfaceshell "NODE_INTERFACESHELL"
  ${_curated_contested}/generated/solidity/src/CoreContestedResolution.sol)

#  compile-NEGATIVE boundary: an external TU must NOT be able to forge a raw
# Solidity Line/Block through SolStmt. The RawCap/rawLine/rawBlock seam was
# DELETED at the  zero endpoint, so the capability-mint probes are gone; what
# remains sealed is the SolStmt encapsulation — a private constructor (no
# aggregate-init, no ctor call from a non-friend) and const fields (no mutation).
# Each PROBE isolates one bypass and is compiled INDEPENDENTLY; the test passes
# iff that probe fails to compile with its expected diagnostic. A structural
# boundary the type system holds, proven at build time, complementing the scanner
# gate's textual prohibition.
# Join include dirs with `|` (not `;`, which CTest would split into separate args).
set(_seal_incs
  "${LLVM_INCLUDE_DIRS};${MLIR_INCLUDE_DIRS};${PROJECT_SOURCE_DIR}/include;${PROJECT_BINARY_DIR}/include;${CMAKE_CURRENT_SOURCE_DIR};${CMAKE_CURRENT_SOURCE_DIR}/provider;${_solidity_generated_dir}")
string(REPLACE ";" "|" _seal_incs "${_seal_incs}")
# probe=EXPECT diagnostic substring (regex).
set(_seal_probes
  "PROBE_AGGREGATE=calling a private constructor"
  "PROBE_MUTATION=const-qualified"
  "PROBE_CTOR_PROBE_COMPLETION=calling a private constructor")
foreach(_probe IN LISTS _seal_probes)
  string(REPLACE "=" ";" _pp "${_probe}")
  list(GET _pp 0 _pdef)
  list(GET _pp 1 _pexpect)
  neutrino_register_test(NAME solidity-raw-seam-sealed.${_pdef} COMMAND ${CMAKE_COMMAND}
    -DCXX=${CMAKE_CXX_COMPILER} -DSTD=gnu++17
    "-DSYSROOT=${CMAKE_OSX_SYSROOT}"
    -DSRC=${PROJECT_SOURCE_DIR}/test/cmake/raw_seam_sealed.cpp
    "-DINCS=${_seal_incs}"
    -DDEFINE=${_pdef} "-DEXPECT=${_pexpect}"
    -P ${PROJECT_SOURCE_DIR}/test/cmake/compile_should_fail.cmake)
  neutrino_register_test_properties(solidity-raw-seam-sealed.${_pdef}
    PROPERTIES LABELS "contract;ctest-native")
endforeach()

#  review compile-NEGATIVE: the callable enums are GENERATED from the `.td`
# (SolidityTargetEnums.inc), and the coverage position-drift assertion catches an
# ALIAS member (one reusing an existing ordinal) — the bypass a terminal `Count`
# sentinel cannot see. Each probe injects an alias into a temp copy of the
# generated enum X-macro and proves the probe TU fails to compile on that assert.
foreach(_enum IN ITEMS CallableKind CallableModifier)
  neutrino_register_test(NAME solidity-callable-enum-alias.${_enum} COMMAND ${CMAKE_COMMAND}
    -DCXX=${CMAKE_CXX_COMPILER} -DSTD=gnu++17
    "-DSYSROOT=${CMAKE_OSX_SYSROOT}"
    -DSOLDIR=${CMAKE_CURRENT_SOURCE_DIR}
    -DPROBE=${PROJECT_SOURCE_DIR}/test/cmake/callable_enum_coverage_probe.cpp
    "-DINCS=${_seal_incs}"
    -DENUM=${_enum}
    -DWORK=${CMAKE_CURRENT_BINARY_DIR}/callable_enum_alias_${_enum}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/callable_enum_alias_probe.cmake)
  neutrino_register_test_properties(solidity-callable-enum-alias.${_enum}
    PROPERTIES LABELS "contract;ctest-native")
endforeach()
