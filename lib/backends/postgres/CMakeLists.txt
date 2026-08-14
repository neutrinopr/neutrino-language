# Postgres backend (M5  D3, ): the spec -> SQL/PLpgSQL renderer, an INDEPENDENT backend that
# links ONLY the contract leaf () — no ProcedureView (View.h), no other backend. GenPostgresSpec
# consumes only the frozen spec JSON (Expr/ValueModel from the leaf, the View.h-free Realization).
# : the legacy sql:: structured target-text emitter ( /  E1) is retired — output is on
# the generated PgStmt -> generated_printer -> codetext pipeline. The thin registry ENTRY
# (PostgresTarget.cpp) stays in NeutrinoEmit and links this. `backend-postgres-smoke` proves it standalone.
# : the first REAL PostgreSQL resolver-reachable recipe package. The recipe
# MODULE (postgres_recipes.inc) is generated at build time from the package .td
# by the shared recipe generator; the concrete node-construction ADAPTER
# (PostgresRecipeAdapter.inc) is a committed artifact regenerated + byte-compared
# so the checked-in construction dispatch cannot drift from the schema. The
# provider TU (PostgresRecipeProvider.cpp) includes PostgresRecipePackage.inc,
# which pulls both in order. Mirrors lib/backends/solidity/CMakeLists.txt ().
set(_postgres_recipes_inc ${CMAKE_CURRENT_BINARY_DIR}/postgres_recipes.inc)
# : the generated .inc are BUILD PRODUCTS, not committed sources. They are
# produced into ${CMAKE_CURRENT_BINARY_DIR}/generated, which is on the private
# include path, so the in-package #includes resolve unchanged. The former
# `*.check` + compare_files pattern is inverted: the command that used to
# regenerate-and-compare now simply PRODUCES the artifact, because there is no
# longer a committed copy to drift from.
set(_postgres_generated_dir ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${_postgres_generated_dir})
set(_postgres_recipe_adapter_inc
  ${_postgres_generated_dir}/PostgresRecipeAdapter.inc)

#  A1 (mirror of the Solidity rule): a NET-NEW producing rule for the
# registry trio. The main tree had none -- only check_target_node_registry.py
# regenerated these, so the committed copies were the only build inputs and
# nothing in the build graph could reproduce them.
set(_postgres_target_nodes_inc ${_postgres_generated_dir}/PostgresTargetNodes.inc)
set(_postgres_target_enums_inc ${_postgres_generated_dir}/PostgresTargetEnums.inc)
set(_postgres_printer_handlers_inc
  ${_postgres_generated_dir}/PostgresPrinterHandlers.inc)
add_custom_command(
  OUTPUT ${_postgres_target_nodes_inc}
         ${_postgres_target_enums_inc}
         ${_postgres_printer_handlers_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    --td ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    --out ${_postgres_target_nodes_inc}
    --printer-out ${_postgres_printer_handlers_inc}
    --enums-out ${_postgres_target_enums_inc}
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
  DEPENDS model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
  COMMENT "Generating PostgreSQL target-node registry ( A1)")
add_custom_target(postgres-target-registry-inc
  DEPENDS ${_postgres_target_nodes_inc}
          ${_postgres_target_enums_inc}
          ${_postgres_printer_handlers_inc})
add_custom_command(OUTPUT ${_postgres_recipes_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/PostgresIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --symbol postgres
    -o ${_postgres_recipes_inc}
  DEPENDS recipes/PostgresIdiomRecipes.td
          recipes/PostgresEvidenceIdiomRecipes.td
          recipes/PostgresTemporalIdiomRecipes.td
          recipes/PostgresSchemaIdiomRecipes.td
          recipes/PostgresEffectfulIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
  COMMENT "Generating PostgreSQL recipe module ()")
add_custom_target(postgres-recipes-inc DEPENDS ${_postgres_recipes_inc})
add_custom_command(OUTPUT ${_postgres_recipe_adapter_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile postgres-recipe-adapter
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/PostgresIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    -o ${_postgres_recipe_adapter_inc}
  DEPENDS recipes/PostgresIdiomRecipes.td recipes/PostgresEvidenceIdiomRecipes.td
          recipes/PostgresTemporalIdiomRecipes.td
          recipes/PostgresSchemaIdiomRecipes.td
          recipes/PostgresEffectfulIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
  COMMENT "Generating PostgreSQL recipe adapter ()")
add_custom_target(postgres-recipe-adapter-inc
  DEPENDS ${_postgres_recipe_adapter_inc})

# : byte-fresh generated finalized-view dispatch.  The PostgreSQL-local
# projection schema owns the complete project/slotExtent/slotItemOrder mapping;
# the provider contains only three typed forwarding calls.
set(_postgres_projection_inc ${_postgres_generated_dir}/PostgresProjection.inc)
add_custom_command(OUTPUT ${_postgres_projection_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile postgres-projection
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/PostgresProjectionSchema.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    -o ${_postgres_projection_inc}
  DEPENDS recipes/PostgresProjectionSchema.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
  COMMENT "Generating PostgreSQL projection resolver ()")
add_custom_target(postgres-projection-inc
  DEPENDS ${_postgres_projection_inc})

#  (Group C): byte-fresh generated raw-DDL carrier construction. The closed
# PostgresDdlCarrier.td descriptor owns the carrier/cap/byte-field/minter/forge
# names; the generator emits their construction bodies so no handwritten
# construction survives in leaf/PgSqlText.cpp (which #includes this artifact).
set(_postgres_ddl_builders_inc ${_postgres_generated_dir}/PgDdlBuilders.inc)
add_custom_command(OUTPUT ${_postgres_ddl_builders_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile postgres-ddl-builders
    --td ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresDdlCarrier.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    -o ${_postgres_ddl_builders_inc}
  DEPENDS model/PostgresDdlCarrier.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
  COMMENT "Generating PostgreSQL raw-DDL carrier construction ()")
add_custom_target(postgres-ddl-builders-inc
  DEPENDS ${_postgres_ddl_builders_inc})

# The recipe-builder pair previously had only a Python freshness test and no
# producing CMake edge. Both outputs now have one build-tree owner.
set(_postgres_recipe_builders_decl_inc
  ${_postgres_generated_dir}/PostgresRecipeBuilders.decl.inc)
set(_postgres_recipe_builders_inc
  ${_postgres_generated_dir}/PostgresRecipeBuilders.inc)
add_custom_command(
  OUTPUT ${_postgres_recipe_builders_decl_inc}
         ${_postgres_recipe_builders_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
    --profile postgres-recipe-builders
    --td ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --decl-out ${_postgres_recipe_builders_decl_inc}
    --def-out ${_postgres_recipe_builders_inc}
  DEPENDS model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/backend_recipe_gen.py
  COMMENT "Generating PostgreSQL recipe builders ( B2)"
  VERBATIM)
add_custom_target(postgres-recipe-builders-inc
  DEPENDS ${_postgres_recipe_builders_decl_inc}
          ${_postgres_recipe_builders_inc})

# R4a (): sources organized into package-role subdirs (recipes/ model/
# generated/ provider/ leaf/ harness/). The role subdirs are added to the
# private include path so the moved in-package #includes resolve unchanged.
add_mlir_library(NeutrinoBackendPostgres
  GenPostgresSpec.cpp
  provider/PostgresSpecModel.cpp
  model/PostgresModel.cpp
  provider/PostgresRecipeProvider.cpp
  leaf/PgSqlText.cpp
  leaf/PgSqlSyntax.cpp
  harness/PostgresDbTest.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  NeutrinoSpecContract
  NeutrinoCodeText
  NeutrinoRecipe
)
add_dependencies(NeutrinoBackendPostgres postgres-recipes-inc
  postgres-target-registry-inc
  postgres-recipe-adapter-inc postgres-projection-inc
  postgres-ddl-builders-inc postgres-recipe-builders-inc)
# add_mlir_library compiles through its object target. The declaration include
# is transitively read by several sources through PostgresModel.h, so the
# object graph itself must wait for the paired generator rather than relying on
# the archive target's later dependency edge.
add_dependencies(obj.NeutrinoBackendPostgres postgres-recipes-inc postgres-target-registry-inc postgres-recipe-adapter-inc postgres-projection-inc postgres-ddl-builders-inc postgres-recipe-builders-inc)
target_include_directories(NeutrinoBackendPostgres PRIVATE
  ${CMAKE_CURRENT_BINARY_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/recipes
  ${CMAKE_CURRENT_SOURCE_DIR}/model
  # : generated artifacts resolve from the BUILD tree. The source-tree
  # generated/ directory is gone, so an include that used to find a committed
  # copy now finds the build product or fails -- there is no silent fallback.
  ${_postgres_generated_dir}
  ${CMAKE_CURRENT_SOURCE_DIR}/provider
  ${CMAKE_CURRENT_SOURCE_DIR}/leaf
  ${CMAKE_CURRENT_SOURCE_DIR}/harness)
set_source_files_properties(provider/PostgresRecipeProvider.cpp PROPERTIES
  OBJECT_DEPENDS ${_postgres_recipes_inc})
# Every committed-side render harness is compiled from this source; bind its
# object edge to the generated handler so Ninja cannot race compilation against
# the registry producer. Mutated harnesses may also wait for the canonical
# handler, which keeps one deterministic dependency shape.
set_source_files_properties(test/postgres_stmt_shell_render_harness.cpp
  PROPERTIES OBJECT_DEPENDS ${_postgres_printer_handlers_inc})
set_source_files_properties(provider/PostgresRecipeProvider.cpp PROPERTIES
  NEUTRINO_SEMANTIC_AUTHORITY_ROLE recipe-provider-plumbing)
neutrino_curated_pack_member(3 _curated_sponsored)
neutrino_curated_pack_member(5 _curated_contested)
neutrino_curated_pack_member(6 _curated_deadline)
set_source_files_properties(harness/PostgresDbTest.cpp PROPERTIES
  NEUTRINO_SEMANTIC_AUTHORITY_ROLE scenario-harness)

# : the evidence rail is lowered by the declarative recipe through the
# registered PostgreSQL provider; postgres-model-test renders the full evidence
# procedure through that production path and pins it byte-identical. This focused
# witness adds resolver totality/uniqueness + the fail-closed missing-key path,
# resolving against the generated package recipe module.
set(_postgres_package_recipes_inc
  ${CMAKE_CURRENT_BINARY_DIR}/postgres_package_recipes.inc)
add_custom_command(OUTPUT ${_postgres_package_recipes_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
    --td ${CMAKE_CURRENT_SOURCE_DIR}/recipes/PostgresIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --symbol postgresPackage
    -o ${_postgres_package_recipes_inc}
  DEPENDS recipes/PostgresIdiomRecipes.td recipes/PostgresEvidenceIdiomRecipes.td
          recipes/PostgresTemporalIdiomRecipes.td
          recipes/PostgresSchemaIdiomRecipes.td
          recipes/PostgresEffectfulIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
  COMMENT "Generating PostgreSQL package recipe module for the resolver witness ()")
add_custom_target(postgres-package-recipes-inc
  DEPENDS ${_postgres_package_recipes_inc})
add_executable(postgres-recipe-resolution-test
  test/postgres_recipe_resolution_test.cpp)
add_dependencies(postgres-recipe-resolution-test postgres-package-recipes-inc)
target_include_directories(postgres-recipe-resolution-test PRIVATE
  ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(postgres-recipe-resolution-test PRIVATE NeutrinoRecipe)
neutrino_register_test(NAME postgres-recipe-resolution-test
  COMMAND postgres-recipe-resolution-test)
neutrino_register_test_properties(postgres-recipe-resolution-test PROPERTIES
  LABELS "contract;ctest-native;fast")

# Link-smoke (M5  D3, ; co-located here : NeutrinoBackendPostgres usable STANDALONE — a leaky carve (the
# SQL renderer reaching a ProcedureView / spec-producer / other-backend symbol) fails to LINK. Renders
# procedure.sql from a committed capability-spec through the backend's public spec->SQL entry point.)
add_executable(backend-postgres-smoke test/backend_postgres_smoke.cpp)
target_link_libraries(backend-postgres-smoke PRIVATE NeutrinoBackendPostgres)
neutrino_register_test(NAME backend-postgres-smoke COMMAND backend-postgres-smoke
  ${_curated_sponsored}/generated/capability-spec/capability-spec.json)
neutrino_register_test_properties(backend-postgres-smoke PROPERTIES LABELS "contract;ctest-native")

#  PR2: target-model unit test — asserts on the graph-derived target structure (quorum gating,
# replay/quorum RAISE guards, balanced obligation, reconciled StatusWrite, typed params, nested
# guard), not on printed bytes (the goldens pin those). Links only NeutrinoBackendPostgres, so it also
# proves the model TU stays leaf-only.
#
# The third fixture ( non-vacuity witness) is the  temporal multi-policy spec — the ONLY shape
# that reaches legalizePostgresTemporal, where the migrated typed ProgressFlag node is CONSTRUCTED. The
# test asserts the legalized model carries BOTH closed ProgressFlag operand values ("false"/"true"), so
# deleting either PgStmt::progressFlag(...) production call fails this test. The fixture is the exact
# capability-spec neutrino-gen emits from test/ir/oracle/accepted_multi_policy.neu (the same sample the
# temporal_coordination_guard_parity lit test renders); regenerate with
# `neutrino-gen --target=capability-spec test/ir/oracle/accepted_multi_policy.neu`.
add_executable(postgres-model-test test/postgres_model_test.cpp)
target_include_directories(postgres-model-test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/provider ${CMAKE_CURRENT_SOURCE_DIR}/model
  ${_postgres_generated_dir} ${CMAKE_CURRENT_SOURCE_DIR}/leaf)
target_link_libraries(postgres-model-test PRIVATE NeutrinoBackendPostgres)
neutrino_register_test(NAME postgres-model-test COMMAND postgres-model-test
  ${_curated_contested}/generated/capability-spec/capability-spec.json
  ${PROJECT_SOURCE_DIR}/test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json
  ${CMAKE_CURRENT_SOURCE_DIR}/test/temporal_multi_policy_spec.json
  ${_curated_deadline}/generated/capability-spec/capability-spec.json)
neutrino_register_test_properties(postgres-model-test PROPERTIES LABELS "contract;ctest-native")

# [977] R5b render referee: a dialect-free, in-process oracle for the
# finalized-view trio (project/slotExtent/slotItemOrder). It drives hermetic
# synthetic capability-specs through the recipe/provider path and (1) pins the
# memo/gated witness's rendered procedure bytes, and (2) proves the two
# sequence-level selections (postingsSchemaKind + the  attestation extent)
# FLIP between the witness (WithMemo + gated) and the plain/ungated variant, so
# the R5b trio retirement is byte- and selection-proven under make unittest (no
# neutrino-gen).
add_executable(postgres-projection-referee-test
  test/postgres_projection_referee_test.cpp)
target_include_directories(postgres-projection-referee-test PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/provider
  ${CMAKE_CURRENT_SOURCE_DIR}/model ${_postgres_generated_dir}
  ${CMAKE_CURRENT_SOURCE_DIR}/leaf)
target_link_libraries(postgres-projection-referee-test PRIVATE
  NeutrinoBackendPostgres)
neutrino_register_test(NAME postgres-projection-referee-test
  COMMAND postgres-projection-referee-test
  ${PROJECT_SOURCE_DIR}/test/ir/backend/Inputs/r5b_effect_memo_witness/generated/capability-spec/capability-spec.json
  ${PROJECT_SOURCE_DIR}/test/ir/backend/Inputs/r5b_effect_memo_witness/generated/postgres/procedure.sql)
neutrino_register_test_properties(postgres-projection-referee-test
  PROPERTIES LABELS "contract;ctest-native")

#  END-TO-END proof that a GENERATED shell handler drives PostgreSQL production
# rendering (the parallel of the Solidity add_stmt_shell_proof). One render harness
# (a minimal PgStmt shim + the generated printer include, linking only NeutrinoCodeText
# — no backend link) is compiled against TWO includes for the migrated ProgressFlag
# node:
#   * the COMMITTED PostgresPrinterHandlers.inc -> must reproduce the golden line;
#   * a .td-MUTATED regenerated include (the ProgressFlag `:=` record mutated to
#     `::=`, produced by the real generator under pinned llvm-tblgen) -> must render
#     the mutated form and FAIL the golden. So mutating the node's syntax record
#     changes production output. The golden is a byte-faithful fixture because the
#     temporal contract that carries `v_progress := …;` is oracle-generated on the fly.
set(_pg_shell_work ${CMAKE_CURRENT_BINARY_DIR}/progressflag_mutation)
set(_pg_shell_mut_inc ${_pg_shell_work}/mutated_printer.inc)
set(_pg_shell_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/progress_flag_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-progressflag-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-progressflag-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\"")
target_link_libraries(postgres-progressflag-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-progressflag-golden
  COMMAND postgres-progressflag-render-committed ${_pg_shell_golden})
neutrino_register_test_properties(postgres-progressflag-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose ProgressFlag syntax record is mutated.
add_custom_command(OUTPUT ${_pg_shell_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_shell_work}
    -DOUT=${_pg_shell_mut_inc}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated ProgressFlag printer include ()")
add_custom_target(postgres-progressflag-mutated-inc DEPENDS ${_pg_shell_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-progressflag-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-progressflag-render-mutated postgres-progressflag-mutated-inc)
target_compile_definitions(postgres-progressflag-render-mutated PRIVATE
  "NODE_INC=\"${_pg_shell_mut_inc}\"")
target_link_libraries(postgres-progressflag-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-progressflag-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-progressflag-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-progressflag-render-mutated>
  -DGOLDEN=${_pg_shell_golden}
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-progressflag-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated PostingIdempotency
# node — the fixed three-line `posting_idempotency` INSERT rendered by the `lines`
# LineGroup handler. The harness runs under -DHARNESS_POSTING_IDEMPOTENCY, and the
# mutation flips `ON CONFLICT DO NOTHING;` -> `ON CONFLICT DO NOTHINGX;` in the
# node's Syntax record, proving the record drives production output.
set(_pg_pi_work ${CMAKE_CURRENT_BINARY_DIR}/posting_idempotency_mutation)
set(_pg_pi_mut_inc ${_pg_pi_work}/mutated_printer.inc)
set(_pg_pi_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/posting_idempotency_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-postingidempotency-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-postingidempotency-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_POSTING_IDEMPOTENCY)
target_link_libraries(postgres-postingidempotency-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-postingidempotency-golden
  COMMAND postgres-postingidempotency-render-committed ${_pg_pi_golden})
neutrino_register_test_properties(postgres-postingidempotency-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose PostingIdempotency syntax record
# is mutated (NODE=posting_idempotency selects that node's token pair).
add_custom_command(OUTPUT ${_pg_pi_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_pi_work}
    -DOUT=${_pg_pi_mut_inc}
    -DNODE=posting_idempotency
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated PostingIdempotency printer include ()")
add_custom_target(postgres-postingidempotency-mutated-inc DEPENDS ${_pg_pi_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-postingidempotency-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-postingidempotency-render-mutated postgres-postingidempotency-mutated-inc)
target_compile_definitions(postgres-postingidempotency-render-mutated PRIVATE
  "NODE_INC=\"${_pg_pi_mut_inc}\""
  HARNESS_POSTING_IDEMPOTENCY)
target_link_libraries(postgres-postingidempotency-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-postingidempotency-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-postingidempotency-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-postingidempotency-render-mutated>
  -DGOLDEN=${_pg_pi_golden}
  "-DMUTATED_EXPECT=ON CONFLICT DO NOTHINGX;"
  -DNODE_LABEL=PostingIdempotency
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-postingidempotency-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated KeyClaimInsert node
# — the fixed two-line `key_claim` INSERT rendered by the `lines` LineGroup
# handler. The harness runs under -DHARNESS_KEY_CLAIM, and the mutation flips
# `v_claim);` -> `v_claimX);` in the node's Syntax record, proving the record
# drives production output.
set(_pg_kc_work ${CMAKE_CURRENT_BINARY_DIR}/key_claim_mutation)
set(_pg_kc_mut_inc ${_pg_kc_work}/mutated_printer.inc)
set(_pg_kc_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/key_claim_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-keyclaiminsert-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-keyclaiminsert-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_KEY_CLAIM)
target_link_libraries(postgres-keyclaiminsert-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-keyclaiminsert-golden
  COMMAND postgres-keyclaiminsert-render-committed ${_pg_kc_golden})
neutrino_register_test_properties(postgres-keyclaiminsert-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose KeyClaimInsert syntax record
# is mutated (NODE=key_claim selects that node's token pair).
add_custom_command(OUTPUT ${_pg_kc_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_kc_work}
    -DOUT=${_pg_kc_mut_inc}
    -DNODE=key_claim
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated KeyClaimInsert printer include ()")
add_custom_target(postgres-keyclaiminsert-mutated-inc DEPENDS ${_pg_kc_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-keyclaiminsert-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-keyclaiminsert-render-mutated postgres-keyclaiminsert-mutated-inc)
target_compile_definitions(postgres-keyclaiminsert-render-mutated PRIVATE
  "NODE_INC=\"${_pg_kc_mut_inc}\""
  HARNESS_KEY_CLAIM)
target_link_libraries(postgres-keyclaiminsert-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-keyclaiminsert-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-keyclaiminsert-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-keyclaiminsert-render-mutated>
  -DGOLDEN=${_pg_kc_golden}
  "-DMUTATED_EXPECT=v_claimX);"
  -DNODE_LABEL=KeyClaimInsert
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-keyclaiminsert-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated CommittedGroupInsert
# node — the fixed two-line `committed_group` INSERT rendered by the `lines`
# LineGroup handler. The harness runs under -DHARNESS_COMMITTED_GROUP, and the
# mutation flips `${ordinal});` -> `${ordinal}X);` in the node's Syntax record,
# proving the record drives production output.
set(_pg_cg_work ${CMAKE_CURRENT_BINARY_DIR}/committed_group_mutation)
set(_pg_cg_mut_inc ${_pg_cg_work}/mutated_printer.inc)
set(_pg_cg_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/committed_group_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-committedgroupinsert-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-committedgroupinsert-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_COMMITTED_GROUP)
target_link_libraries(postgres-committedgroupinsert-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-committedgroupinsert-golden
  COMMAND postgres-committedgroupinsert-render-committed ${_pg_cg_golden})
neutrino_register_test_properties(postgres-committedgroupinsert-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose CommittedGroupInsert syntax
# record is mutated (NODE=committed_group selects that node's token pair).
add_custom_command(OUTPUT ${_pg_cg_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_cg_work}
    -DOUT=${_pg_cg_mut_inc}
    -DNODE=committed_group
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated CommittedGroupInsert printer include ()")
add_custom_target(postgres-committedgroupinsert-mutated-inc DEPENDS ${_pg_cg_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-committedgroupinsert-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-committedgroupinsert-render-mutated postgres-committedgroupinsert-mutated-inc)
target_compile_definitions(postgres-committedgroupinsert-render-mutated PRIVATE
  "NODE_INC=\"${_pg_cg_mut_inc}\""
  HARNESS_COMMITTED_GROUP)
target_link_libraries(postgres-committedgroupinsert-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-committedgroupinsert-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-committedgroupinsert-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-committedgroupinsert-render-mutated>
  -DGOLDEN=${_pg_cg_golden}
  "-DMUTATED_EXPECT=0X);"
  -DNODE_LABEL=CommittedGroupInsert
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-committedgroupinsert-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated QuorumAcceptInsert
# node — the fixed two-line `quorum_acceptance` INSERT (incl. the nested
# observer-count subquery in the VALUES tail) rendered by the `lines` LineGroup
# handler. The harness runs under -DHARNESS_QUORUM_ACCEPT, and the mutation flips
# `observer_count)` -> `observer_countX)` in the node's Syntax record, proving
# the record drives production output.
set(_pg_qa_work ${CMAKE_CURRENT_BINARY_DIR}/quorum_accept_mutation)
set(_pg_qa_mut_inc ${_pg_qa_work}/mutated_printer.inc)
set(_pg_qa_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/quorum_accept_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-quorumacceptinsert-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-quorumacceptinsert-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_QUORUM_ACCEPT)
target_link_libraries(postgres-quorumacceptinsert-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-quorumacceptinsert-golden
  COMMAND postgres-quorumacceptinsert-render-committed ${_pg_qa_golden})
neutrino_register_test_properties(postgres-quorumacceptinsert-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose QuorumAcceptInsert syntax
# record is mutated (NODE=quorum_accept selects that node's token pair).
add_custom_command(OUTPUT ${_pg_qa_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_qa_work}
    -DOUT=${_pg_qa_mut_inc}
    -DNODE=quorum_accept
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated QuorumAcceptInsert printer include ()")
add_custom_target(postgres-quorumacceptinsert-mutated-inc DEPENDS ${_pg_qa_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-quorumacceptinsert-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-quorumacceptinsert-render-mutated postgres-quorumacceptinsert-mutated-inc)
target_compile_definitions(postgres-quorumacceptinsert-render-mutated PRIVATE
  "NODE_INC=\"${_pg_qa_mut_inc}\""
  HARNESS_QUORUM_ACCEPT)
target_link_libraries(postgres-quorumacceptinsert-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-quorumacceptinsert-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-quorumacceptinsert-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-quorumacceptinsert-render-mutated>
  -DGOLDEN=${_pg_qa_golden}
  "-DMUTATED_EXPECT=observer_countX)"
  -DNODE_LABEL=QuorumAcceptInsert
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-quorumacceptinsert-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated TemporalAcceptInsert
# node — the temporal-rail sibling of QuorumAcceptInsert: the fixed two-line
# temporal `quorum_acceptance` INSERT (incl. the policy/execution_claim columns
# and the nested observer-count subquery in the VALUES tail) rendered by the
# `lines` LineGroup handler. The harness runs under -DHARNESS_TEMPORAL_ACCEPT,
# and the mutation flips the UNIQUE `execution_claim, observer_count)` ->
# `execution_claim, observer_countX)` in the node's Syntax record (a token that
# does not occur in the sibling QuorumAcceptInsert record), proving the record
# drives production output.
set(_pg_ta_work ${CMAKE_CURRENT_BINARY_DIR}/temporal_accept_mutation)
set(_pg_ta_mut_inc ${_pg_ta_work}/mutated_printer.inc)
set(_pg_ta_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/temporal_accept_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-temporalacceptinsert-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-temporalacceptinsert-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_TEMPORAL_ACCEPT)
target_link_libraries(postgres-temporalacceptinsert-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-temporalacceptinsert-golden
  COMMAND postgres-temporalacceptinsert-render-committed ${_pg_ta_golden})
neutrino_register_test_properties(postgres-temporalacceptinsert-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose TemporalAcceptInsert syntax
# record is mutated (NODE=temporal_accept selects that node's token pair).
add_custom_command(OUTPUT ${_pg_ta_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_ta_work}
    -DOUT=${_pg_ta_mut_inc}
    -DNODE=temporal_accept
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated TemporalAcceptInsert printer include ()")
add_custom_target(postgres-temporalacceptinsert-mutated-inc DEPENDS ${_pg_ta_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-temporalacceptinsert-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-temporalacceptinsert-render-mutated postgres-temporalacceptinsert-mutated-inc)
target_compile_definitions(postgres-temporalacceptinsert-render-mutated PRIVATE
  "NODE_INC=\"${_pg_ta_mut_inc}\""
  HARNESS_TEMPORAL_ACCEPT)
target_link_libraries(postgres-temporalacceptinsert-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-temporalacceptinsert-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-temporalacceptinsert-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-temporalacceptinsert-render-mutated>
  -DGOLDEN=${_pg_ta_golden}
  "-DMUTATED_EXPECT=observer_countX)"
  -DNODE_LABEL=TemporalAcceptInsert
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-temporalacceptinsert-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated IdempotentReturn
# node — a 0-OPERAND CONSTANT `line`: the fixed idempotency-guard early return
# `RETURN;  -- already processed; no double posting` rendered by the generic
# `line`/codetext::Line handler (no projected operands, no ${...} placeholders).
# The harness runs under -DHARNESS_IDEMPOTENT_RETURN, and the mutation flips the
# UNIQUE `no double posting` -> `no double postinX` in the node's Syntax record
# (a trailing-char substitution, not an append — the token is the syntax tail so
# an append would leave the committed token as a substring), proving the record
# drives production output.
set(_pg_ir_work ${CMAKE_CURRENT_BINARY_DIR}/idempotent_return_mutation)
set(_pg_ir_mut_inc ${_pg_ir_work}/mutated_printer.inc)
set(_pg_ir_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/idempotent_return_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-idempotentreturn-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-idempotentreturn-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_IDEMPOTENT_RETURN)
target_link_libraries(postgres-idempotentreturn-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-idempotentreturn-golden
  COMMAND postgres-idempotentreturn-render-committed ${_pg_ir_golden})
neutrino_register_test_properties(postgres-idempotentreturn-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose IdempotentReturn syntax
# record is mutated (NODE=idempotent_return selects that node's token pair).
add_custom_command(OUTPUT ${_pg_ir_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_ir_work}
    -DOUT=${_pg_ir_mut_inc}
    -DNODE=idempotent_return
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated IdempotentReturn printer include ()")
add_custom_target(postgres-idempotentreturn-mutated-inc DEPENDS ${_pg_ir_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-idempotentreturn-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-idempotentreturn-render-mutated postgres-idempotentreturn-mutated-inc)
target_compile_definitions(postgres-idempotentreturn-render-mutated PRIVATE
  "NODE_INC=\"${_pg_ir_mut_inc}\""
  HARNESS_IDEMPOTENT_RETURN)
target_link_libraries(postgres-idempotentreturn-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-idempotentreturn-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-idempotentreturn-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-idempotentreturn-render-mutated>
  -DGOLDEN=${_pg_ir_golden}
  "-DMUTATED_EXPECT=no double postinX"
  -DNODE_LABEL=IdempotentReturn
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-idempotentreturn-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated EvidenceClaimComment
# node — a 0-OPERAND CONSTANT `line`: the fixed evidence-only claim comment
# `-- Evidence-only: atomically CLAIM the accepted terminal; move NO ledger value.`
# rendered by the generic `line`/codetext::Line handler (no projected operands, no
# ${...} placeholders). The harness runs under -DHARNESS_EVIDENCE_CLAIM_COMMENT,
# and the mutation flips the UNIQUE `move NO ledger value.` -> `move NO ledger
# valueX.` in the node's Syntax record (an X inserted before the trailing `.`, so
# the committed token is not a substring of the mutated one), proving the record
# drives production output.
set(_pg_ec_work ${CMAKE_CURRENT_BINARY_DIR}/evidence_claim_comment_mutation)
set(_pg_ec_mut_inc ${_pg_ec_work}/mutated_printer.inc)
set(_pg_ec_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/evidence_claim_comment_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-evidenceclaimcomment-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-evidenceclaimcomment-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_EVIDENCE_CLAIM_COMMENT)
target_link_libraries(postgres-evidenceclaimcomment-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-evidenceclaimcomment-golden
  COMMAND postgres-evidenceclaimcomment-render-committed ${_pg_ec_golden})
neutrino_register_test_properties(postgres-evidenceclaimcomment-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose EvidenceClaimComment syntax
# record is mutated (NODE=evidence_claim_comment selects that node's token pair).
add_custom_command(OUTPUT ${_pg_ec_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_ec_work}
    -DOUT=${_pg_ec_mut_inc}
    -DNODE=evidence_claim_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated EvidenceClaimComment printer include ()")
add_custom_target(postgres-evidenceclaimcomment-mutated-inc DEPENDS ${_pg_ec_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-evidenceclaimcomment-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-evidenceclaimcomment-render-mutated postgres-evidenceclaimcomment-mutated-inc)
target_compile_definitions(postgres-evidenceclaimcomment-render-mutated PRIVATE
  "NODE_INC=\"${_pg_ec_mut_inc}\""
  HARNESS_EVIDENCE_CLAIM_COMMENT)
target_link_libraries(postgres-evidenceclaimcomment-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-evidenceclaimcomment-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-evidenceclaimcomment-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-evidenceclaimcomment-render-mutated>
  -DGOLDEN=${_pg_ec_golden}
  "-DMUTATED_EXPECT=move NO ledger valueX."
  -DNODE_LABEL=EvidenceClaimComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-evidenceclaimcomment-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  the same END-TO-END render-pair proof for the migrated PolicyCaseSelect
# node — the temporal accept_ gate's per-policy resolver: the fixed
# `CASE p_policy` header + one `WHEN … THEN v_set := …; v_m := …;` item line per
# declared attestation policy + the fixed `ELSE RAISE …` / `END CASE;` footer,
# rendered by the shared `framed-lines` LineGroup handler (the FIRST production
# framed-lines node). The harness runs under -DHARNESS_POLICY_CASE feeding two
# per-policy tuples via the model group; the mutation flips the UNIQUE item
# operator `THEN v_set := ${observerSet}` -> `THEN v_set ::= ${observerSet}` in
# the node's ItemSyntax record, proving the record drives production output.
set(_pg_pc_work ${CMAKE_CURRENT_BINARY_DIR}/policy_case_mutation)
set(_pg_pc_mut_inc ${_pg_pc_work}/mutated_printer.inc)
set(_pg_pc_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/policy_case_golden.sql)

# Committed-include harness: consumes the checked-in generated handler.
add_executable(postgres-policycaseselect-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-policycaseselect-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_POLICY_CASE)
target_link_libraries(postgres-policycaseselect-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-policycaseselect-golden
  COMMAND postgres-policycaseselect-render-committed ${_pg_pc_golden})
neutrino_register_test_properties(postgres-policycaseselect-golden PROPERTIES LABELS "contract;ctest-native")

# Regenerate the printer include from a .td whose PolicyCaseSelect ItemSyntax
# record is mutated (NODE=policy_case selects that node's token pair).
add_custom_command(OUTPUT ${_pg_pc_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_pc_work}
    -DOUT=${_pg_pc_mut_inc}
    -DNODE=policy_case
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated PolicyCaseSelect printer include ()")
add_custom_target(postgres-policycaseselect-mutated-inc DEPENDS ${_pg_pc_mut_inc})

# Mutated-include harness: same source, compiled against the regenerated include.
add_executable(postgres-policycaseselect-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-policycaseselect-render-mutated postgres-policycaseselect-mutated-inc)
target_compile_definitions(postgres-policycaseselect-render-mutated PRIVATE
  "NODE_INC=\"${_pg_pc_mut_inc}\""
  HARNESS_POLICY_CASE)
target_link_libraries(postgres-policycaseselect-render-mutated PRIVATE NeutrinoCodeText)

# The pair driver: committed render must match the golden, mutated must fail it.
neutrino_register_test(NAME postgres-policycaseselect-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-policycaseselect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-policycaseselect-render-mutated>
  -DGOLDEN=${_pg_pc_golden}
  "-DMUTATED_EXPECT=v_set ::="
  -DNODE_LABEL=PolicyCaseSelect
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-policycaseselect-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  C1: the same END-TO-END render-pair proof for the migrated
# EffectLedgerComment node — the per-effect ledger comment header (the SOLE
# remaining executable pgLine site, now retired). A projected `line`
# `-- <kind> <name> (<ledger>)<suffix>` rendered by the shared Line handler. The
# harness runs under -DHARNESS_EFFECT_LEDGER_COMMENT feeding the four dense
# operands (incl. the already-decided guard suffix); the mutation flips the fixed
# ledger-paren shape `(${ledger})` -> `{${ledger}}` in the node's Syntax record,
# proving the record drives the production comment bytes.
set(_pg_ec2_work ${CMAKE_CURRENT_BINARY_DIR}/effect_ledger_comment_mutation)
set(_pg_ec2_mut_inc ${_pg_ec2_work}/mutated_printer.inc)
set(_pg_ec2_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/effect_ledger_comment_golden.sql)

add_executable(postgres-effectledgercomment-render-committed test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-effectledgercomment-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_EFFECT_LEDGER_COMMENT)
target_link_libraries(postgres-effectledgercomment-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-effectledgercomment-golden
  COMMAND postgres-effectledgercomment-render-committed ${_pg_ec2_golden})
neutrino_register_test_properties(postgres-effectledgercomment-golden PROPERTIES LABELS "contract;ctest-native")

add_custom_command(OUTPUT ${_pg_ec2_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_ec2_work}
    -DOUT=${_pg_ec2_mut_inc}
    -DNODE=effect_ledger_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated EffectLedgerComment printer include ()")
add_custom_target(postgres-effectledgercomment-mutated-inc DEPENDS ${_pg_ec2_mut_inc})

add_executable(postgres-effectledgercomment-render-mutated test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-effectledgercomment-render-mutated postgres-effectledgercomment-mutated-inc)
target_compile_definitions(postgres-effectledgercomment-render-mutated PRIVATE
  "NODE_INC=\"${_pg_ec2_mut_inc}\""
  HARNESS_EFFECT_LEDGER_COMMENT)
target_link_libraries(postgres-effectledgercomment-render-mutated PRIVATE NeutrinoCodeText)

neutrino_register_test(NAME postgres-effectledgercomment-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effectledgercomment-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-effectledgercomment-render-mutated>
  -DGOLDEN=${_pg_ec2_golden}
  "-DMUTATED_EXPECT={escrow}"
  -DNODE_LABEL=EffectLedgerComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-effectledgercomment-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  C2 handler-level render pair for the fixed, zero-operand
# IdempotencyGuardComment. The committed handler must reproduce the exact
# production banner; a real tblgen regeneration with the .td syntax mutated
# must change it.
set(_pg_igc_work ${CMAKE_CURRENT_BINARY_DIR}/idempotency_guard_comment_mutation)
set(_pg_igc_mut_inc ${_pg_igc_work}/mutated_printer.inc)
set(_pg_igc_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/idempotency_guard_comment_golden.sql)

add_executable(postgres-idempotencyguardcomment-render-committed
  test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-idempotencyguardcomment-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_IDEMPOTENCY_GUARD_COMMENT)
target_link_libraries(postgres-idempotencyguardcomment-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-idempotencyguardcomment-golden
  COMMAND postgres-idempotencyguardcomment-render-committed ${_pg_igc_golden})
neutrino_register_test_properties(postgres-idempotencyguardcomment-golden PROPERTIES LABELS "contract;ctest-native")

add_custom_command(OUTPUT ${_pg_igc_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_igc_work}
    -DOUT=${_pg_igc_mut_inc}
    -DNODE=idempotency_guard_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated IdempotencyGuardComment printer include ( C2)")
add_custom_target(postgres-idempotencyguardcomment-mutated-inc DEPENDS ${_pg_igc_mut_inc})

add_executable(postgres-idempotencyguardcomment-render-mutated
  test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-idempotencyguardcomment-render-mutated
  postgres-idempotencyguardcomment-mutated-inc)
target_compile_definitions(postgres-idempotencyguardcomment-render-mutated PRIVATE
  "NODE_INC=\"${_pg_igc_mut_inc}\""
  HARNESS_IDEMPOTENCY_GUARD_COMMENT)
target_link_libraries(postgres-idempotencyguardcomment-render-mutated PRIVATE NeutrinoCodeText)

neutrino_register_test(NAME postgres-idempotencyguardcomment-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-idempotencyguardcomment-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-idempotencyguardcomment-render-mutated>
  -DGOLDEN=${_pg_igc_golden}
  "-DMUTATED_EXPECT=one row per workflow keX"
  -DNODE_LABEL=IdempotencyGuardComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-idempotencyguardcomment-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  C3 handler-level render pair for the fixed, zero-operand balanced
# invariant banner.
set(_pg_bic_work ${CMAKE_CURRENT_BINARY_DIR}/balanced_invariant_comment_mutation)
set(_pg_bic_mut_inc ${_pg_bic_work}/mutated_printer.inc)
set(_pg_bic_golden ${CMAKE_CURRENT_SOURCE_DIR}/test/balanced_invariant_comment_golden.sql)

add_executable(postgres-balancedinvariantcomment-render-committed
  test/postgres_stmt_shell_render_harness.cpp)
target_compile_definitions(postgres-balancedinvariantcomment-render-committed PRIVATE
  "NODE_INC=\"${_postgres_generated_dir}/PostgresPrinterHandlers.inc\""
  HARNESS_BALANCED_INVARIANT_COMMENT)
target_link_libraries(postgres-balancedinvariantcomment-render-committed PRIVATE NeutrinoCodeText)
neutrino_register_test(NAME postgres-balancedinvariantcomment-golden
  COMMAND postgres-balancedinvariantcomment-render-committed ${_pg_bic_golden})
neutrino_register_test_properties(postgres-balancedinvariantcomment-golden PROPERTIES LABELS "contract;ctest-native")

add_custom_command(OUTPUT ${_pg_bic_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_bic_work}
    -DOUT=${_pg_bic_mut_inc}
    -DNODE=balanced_invariant_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated BalancedInvariantComment printer include ( C3)")
add_custom_target(postgres-balancedinvariantcomment-mutated-inc DEPENDS ${_pg_bic_mut_inc})

add_executable(postgres-balancedinvariantcomment-render-mutated
  test/postgres_stmt_shell_render_harness.cpp)
add_dependencies(postgres-balancedinvariantcomment-render-mutated
  postgres-balancedinvariantcomment-mutated-inc)
target_compile_definitions(postgres-balancedinvariantcomment-render-mutated PRIVATE
  "NODE_INC=\"${_pg_bic_mut_inc}\""
  HARNESS_BALANCED_INVARIANT_COMMENT)
target_link_libraries(postgres-balancedinvariantcomment-render-mutated PRIVATE NeutrinoCodeText)

neutrino_register_test(NAME postgres-balancedinvariantcomment-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-balancedinvariantcomment-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-balancedinvariantcomment-render-mutated>
  -DGOLDEN=${_pg_bic_golden}
  "-DMUTATED_EXPECT=must net to zerX"
  -DNODE_LABEL=BalancedInvariantComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_stmt_shell_render_pair.cmake)
neutrino_register_test_properties(postgres-balancedinvariantcomment-td-mutation PROPERTIES LABELS "contract;ctest-native")

#  C1 GOVERNING mutation witness on the PRODUCTION surface. The shell test
# above is handler-level coverage (stub PgStmt, only NeutrinoCodeText); this runs
# the REAL planFromSpec -> generatePostgresProcedureFromSpec path
# (projection materialization / PgStmt::effectLedgerComment / rendering) on a
# real effectful capability-spec (core_document_escrow, whose
# guarded effects also exercise the ${suffix}). The committed driver links the
# committed backend; the mutated driver compiles a build-time COPY of
# PostgresModel.cpp (PostgresModel_mutated.cpp, generated by
# gen_mutated_postgres_model_tu.cmake) whose SOLE delta is the printer-handlers
# include repointed at a .td-mutated file — so the real render path adopts the
# mutation WITHOUT any override boundary in the production TU (production
# PostgresModel.cpp keeps its literal committed include). The negative bites when
# the real factory/routing is removed or miswired, not only when the handler text
# drifts.
set(_pg_rp_spec ${PROJECT_SOURCE_DIR}/test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json)
# Keep the generated mutation-only TU under a test source path. The authority
# gates derive their production object set from compile_commands.json and exclude
# test TUs; placing this exact-copy witness beside production build sources would
# misclassify its intentional duplicate definitions as escaped authorities.
set(_pg_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/effect_real_path_mutation)
set(_pg_rp_mut_inc ${_pg_rp_work}/mutated_printer.inc)

# Committed real-path driver: the actual backend, committed include.
add_executable(postgres-effect-render-committed test/postgres_effect_render_driver.cpp)
target_link_libraries(postgres-effect-render-committed PRIVATE NeutrinoBackendPostgres)

# Regenerate the .td-mutated include (NODE=effect_ledger_comment: (${ledger}) -> {${ledger}}).
add_custom_command(OUTPUT ${_pg_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_rp_work}
    -DOUT=${_pg_rp_mut_inc}
    -DNODE=effect_ledger_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path EffectLedgerComment witness ()")
add_custom_target(postgres-effect-real-path-mutated-inc DEPENDS ${_pg_rp_mut_inc})

# A build-time COPY of the production emitter TU whose ONLY delta is the
# printer-handlers include, repointed at the mutated file — regenerated whenever
# PostgresModel.cpp or the mutated include changes (freshness-anchored; the
# generator fails closed if the committed include line drifts). The production
# PostgresModel.cpp is untouched and admits no override boundary.
set(_pg_rp_mut_tu ${_pg_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_rp_mut_inc}
    -DOUT=${_pg_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include copy of PostgresModel.cpp for the C1 real-path witness ()")
add_custom_target(postgres-effect-real-path-mutated-tu DEPENDS ${_pg_rp_mut_tu})

# Mutated real-path driver: the driver + the COPY of PostgresModel.cpp (which
# same-source includes the mutated handlers by absolute path). The copy defines
# graph materialization/rendering, so the committed archive member is not pulled
# (the other backend objects — GenPostgresSpec/… — still come from the
# library). The copy's other same-dir includes resolve through the backend's
# include dirs.
add_executable(postgres-effect-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_rp_mut_tu})
add_dependencies(postgres-effect-render-mutated postgres-effect-real-path-mutated-tu)
target_include_directories(postgres-effect-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-effect-render-mutated PRIVATE NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-effectledgercomment-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-effect-render-mutated>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=-- debit escrow_release (escrow.holding) when p_amount >= p_agreed_amount"
  "-DMUTATED_LINE=-- debit escrow_release {escrow.holding} when p_amount >= p_agreed_amount"
  -DNODE_LABEL=EffectLedgerComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-effectledgercomment-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  slice 1b production-path mutation witness for the CallableSig header node.
# Reuse the same real effectful capability-spec + committed driver
# (postgres-effect-render-committed), but compile a separate test-only copy of
# PostgresModel.cpp against a CallableSig-mutated generated include (RETURNS void
# -> RETURNS trigger). This proves the actual projection-renderer header + the
# CallableSig .td node own the production `CREATE OR REPLACE FUNCTION … RETURNS`
# bytes; the production TU keeps its literal committed include. The negative bites
# when the real header routing is removed/miswired, not only when the handler
# text drifts.
set(_pg_cs_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/callable_sig_real_path_mutation)
set(_pg_cs_rp_mut_inc ${_pg_cs_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_cs_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_cs_rp_work}
    -DOUT=${_pg_cs_rp_mut_inc}
    -DNODE=callable_sig
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path CallableSig witness ()")
add_custom_target(postgres-callablesig-real-path-mutated-inc DEPENDS ${_pg_cs_rp_mut_inc})

set(_pg_cs_rp_mut_tu ${_pg_cs_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_cs_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_cs_rp_mut_inc}
    -DOUT=${_pg_cs_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_cs_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include copy of PostgresModel.cpp for the CallableSig real-path witness ()")
add_custom_target(postgres-callablesig-real-path-mutated-tu DEPENDS ${_pg_cs_rp_mut_tu})

add_executable(postgres-callablesig-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_cs_rp_mut_tu})
add_dependencies(postgres-callablesig-render-mutated postgres-callablesig-real-path-mutated-tu)
target_include_directories(postgres-callablesig-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-callablesig-render-mutated PRIVATE NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-callablesig-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-callablesig-render-mutated>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=RETURNS void"
  "-DMUTATED_LINE=RETURNS trigger"
  -DNODE_LABEL=CallableSig
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-callablesig-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  slice 3 production-path mutation witness for the CallableBody block frame
# node. Recompile the real PostgresModel.cpp against a CallableBody-.td-mutated
# include (END; -> DONE;) and run the actual projection-renderer path:
# the committed driver emits `END;`; the mutated driver emits `DONE;` and NOT the
# committed line — proving the CallableBody .td node drives the production
# body-frame bytes through the real factory/routing. Reuses the committed effect
# render driver + spec.
set(_pg_cb_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/callable_body_real_path_mutation)
set(_pg_cb_rp_mut_inc ${_pg_cb_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_cb_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_cb_rp_work}
    -DOUT=${_pg_cb_rp_mut_inc}
    -DNODE=callable_body
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path CallableBody witness ()")
add_custom_target(postgres-callablebody-real-path-mutated-inc DEPENDS ${_pg_cb_rp_mut_inc})

set(_pg_cb_rp_mut_tu ${_pg_cb_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_cb_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_cb_rp_mut_inc}
    -DOUT=${_pg_cb_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_cb_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include copy of PostgresModel.cpp for the CallableBody real-path witness ()")
add_custom_target(postgres-callablebody-real-path-mutated-tu DEPENDS ${_pg_cb_rp_mut_tu})

add_executable(postgres-callablebody-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_cb_rp_mut_tu})
add_dependencies(postgres-callablebody-render-mutated postgres-callablebody-real-path-mutated-tu)
target_include_directories(postgres-callablebody-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-callablebody-render-mutated PRIVATE NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-callablebody-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-callablebody-render-mutated>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=END;"
  "-DMUTATED_LINE=DONE;"
  -DNODE_LABEL=CallableBody
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-callablebody-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  family-1 production-path mutation witness for the If guard-block node.
# Recompile the real PostgresModel.cpp against an If-.td-mutated include (END IF;
# -> END IFX;) and run the actual projection-renderer path: the
# committed driver emits `END IF;`; the mutated driver emits `END IFX;` and NOT
# the committed line — proving the If .td node drives the production guard-frame
# bytes through the real factory + the sealed authorGuard carrier.
set(_pg_if_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/if_real_path_mutation)
set(_pg_if_rp_mut_inc ${_pg_if_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_if_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_if_rp_work}
    -DOUT=${_pg_if_rp_mut_inc}
    -DNODE=if
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path If witness ()")
add_custom_target(postgres-if-real-path-mutated-inc DEPENDS ${_pg_if_rp_mut_inc})

set(_pg_if_rp_mut_tu ${_pg_if_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_if_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_if_rp_mut_inc}
    -DOUT=${_pg_if_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_if_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include copy of PostgresModel.cpp for the If real-path witness ()")
add_custom_target(postgres-if-real-path-mutated-tu DEPENDS ${_pg_if_rp_mut_tu})

add_executable(postgres-if-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_if_rp_mut_tu})
add_dependencies(postgres-if-render-mutated postgres-if-real-path-mutated-tu)
target_include_directories(postgres-if-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-if-render-mutated PRIVATE NeutrinoBackendPostgres)

# NOTE: a FlatIf-FREE spec (core_sponsored_offer), NOT the shared
# core_document_escrow `_pg_rp_spec`: the handwritten  FlatIf guard renders
# byte-identical `IF … THEN`/`END IF;` framing, so a FlatIf-bearing spec would
# leave unmutated `END IF;` lines and defeat the pair harness's committed-absent
# check. core_sponsored_offer exercises the money/replay/balance If guards
# with no conditional-effect guard, so EVERY `END IF;` comes from the If node.
set(_pg_if_rp_spec ${_curated_sponsored}/generated/capability-spec/capability-spec.json)
neutrino_register_test(NAME postgres-if-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-if-render-mutated>
  -DSPEC=${_pg_if_rp_spec}
  "-DCOMMITTED_LINE=END IF;"
  "-DMUTATED_LINE=END IFX;"
  -DNODE_LABEL=If
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-if-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  family-1 (flat) production-path mutation witness for the FlatIf flat-block
# guard node. Recompile the real PostgresModel.cpp against a flat-if-.td-mutated
# include (NODE-SCOPED END IF; -> END IFX; on ONLY the FlatIf record) and run the
# actual projection-renderer path on the FlatIf-bearing core_document_escrow
# spec: the committed driver emits `END IF;`; the mutated driver emits `END IFX;`
# on the flat guards while the If-rendered guards keep `END IF;` — and normalizing
# it back reproduces the committed render EXACTLY. Proves the FlatIf .td node drives
# the flat guard-frame bytes through the real factory + the sealed authorGuard
# carrier, and moves ONLY the FlatIf frames (flat legs + indentation unchanged).
set(_pg_fif_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/flat_if_real_path_mutation)
set(_pg_fif_rp_mut_inc ${_pg_fif_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_fif_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_fif_rp_work}
    -DOUT=${_pg_fif_rp_mut_inc}
    -DNODE=flat-if
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path FlatIf witness ()")
add_custom_target(postgres-flatif-real-path-mutated-inc DEPENDS ${_pg_fif_rp_mut_inc})

set(_pg_fif_rp_mut_tu ${_pg_fif_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_fif_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_fif_rp_mut_inc}
    -DOUT=${_pg_fif_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_fif_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include copy of PostgresModel.cpp for the FlatIf real-path witness ()")
add_custom_target(postgres-flatif-real-path-mutated-tu DEPENDS ${_pg_fif_rp_mut_tu})

add_executable(postgres-flatif-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_fif_rp_mut_tu})
add_dependencies(postgres-flatif-render-mutated postgres-flatif-real-path-mutated-tu)
target_include_directories(postgres-flatif-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-flatif-render-mutated PRIVATE NeutrinoBackendPostgres)

# core_document_escrow (the shared `_pg_rp_spec`) bears the flat
# conditional-effect guard, so it exercises FlatIf alongside the If guards — the
# harness normalizes the flat-if-only mutation back and proves the isolation.
neutrino_register_test(NAME postgres-flatif-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-flatif-render-mutated>
  -DSPEC=${_pg_rp_spec}
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_flat_if_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-flatif-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  ENDPOINT production-path mutation witness for the CallableClose `$$;` node.
# Recompile the real PostgresModel.cpp against a CallableClose-.td-mutated include
# ($$; -> @@;) and run the actual projection-renderer path: the
# committed driver emits `$$;`; the mutated driver emits `@@;` and NOT the
# committed line — proving the CallableClose .td node drives the production
# function-close bytes through the real factory/routing. Reuses the committed
# effect render driver + spec.
set(_pg_cc_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/callable_close_real_path_mutation)
set(_pg_cc_rp_mut_inc ${_pg_cc_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_cc_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_cc_rp_work}
    -DOUT=${_pg_cc_rp_mut_inc}
    -DNODE=callable_close
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path CallableClose witness ()")
add_custom_target(postgres-callableclose-real-path-mutated-inc DEPENDS ${_pg_cc_rp_mut_inc})

set(_pg_cc_rp_mut_tu ${_pg_cc_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_cc_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_cc_rp_mut_inc}
    -DOUT=${_pg_cc_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_cc_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include copy of PostgresModel.cpp for the CallableClose real-path witness ()")
add_custom_target(postgres-callableclose-real-path-mutated-tu DEPENDS ${_pg_cc_rp_mut_tu})

add_executable(postgres-callableclose-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_cc_rp_mut_tu})
add_dependencies(postgres-callableclose-render-mutated postgres-callableclose-real-path-mutated-tu)
target_include_directories(postgres-callableclose-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-callableclose-render-mutated PRIVATE NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-callableclose-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-callableclose-render-mutated>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=$$;"
  "-DMUTATED_LINE=@@;"
  -DNODE_LABEL=CallableClose
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-callableclose-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  slice 2 production-path mutation witness. Recompile the production model
# TU against a DeclareSection-mutated generated include and exercise both an
# ordinary effectful procedure and the temporal multi-policy procedure. The
# evidence-only fixture has no DECLARE section and must remain byte-identical.
set(_pg_ds_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/declare_section_real_path_mutation)
set(_pg_ds_rp_mut_inc ${_pg_ds_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_ds_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_ds_rp_work}
    -DOUT=${_pg_ds_rp_mut_inc}
    -DNODE=declare_section
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path DeclareSection witness ()")
add_custom_target(postgres-declaresection-real-path-mutated-inc
  DEPENDS ${_pg_ds_rp_mut_inc})

set(_pg_ds_rp_mut_tu ${_pg_ds_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_ds_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_ds_rp_mut_inc}
    -DOUT=${_pg_ds_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_ds_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include PostgresModel.cpp copy for the DeclareSection witness ()")
add_custom_target(postgres-declaresection-real-path-mutated-tu
  DEPENDS ${_pg_ds_rp_mut_tu})

add_executable(postgres-declaresection-render-mutated
  test/postgres_effect_render_driver.cpp
  ${_pg_ds_rp_mut_tu})
add_dependencies(postgres-declaresection-render-mutated
  postgres-declaresection-real-path-mutated-tu)
target_include_directories(postgres-declaresection-render-mutated PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-declaresection-render-mutated PRIVATE
  NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-declaresection-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-declaresection-render-mutated>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=DECLARE"
  "-DMUTATED_LINE=DECLARX"
  -DNODE_LABEL=DeclareSection
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-declaresection-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

neutrino_register_test(NAME postgres-declaresection-temporal-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-declaresection-render-mutated>
  -DSPEC=${CMAKE_CURRENT_SOURCE_DIR}/test/temporal_multi_policy_spec.json
  "-DCOMMITTED_LINE=DECLARE"
  "-DMUTATED_LINE=DECLARX"
  -DNODE_LABEL=DeclareSection
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-declaresection-temporal-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

neutrino_register_test(NAME postgres-declaresection-evidence-exclusion COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-declaresection-render-mutated>
  -DSPEC=${_curated_deadline}/generated/capability-spec/capability-spec.json
  -DNODE_LABEL=DeclareSection
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_exclusion.cmake)
neutrino_register_test_properties(postgres-declaresection-evidence-exclusion
  PROPERTIES LABELS "contract;ctest-native")

#  C2 production-path mutation witness. Reuse the real effectful
# capability-spec driver, but compile a separate test-only copy of
# PostgresModel.cpp against an IdempotencyGuardComment-mutated generated include.
# This proves the actual legalizeEffectful factory and generated dispatch own the
# production bytes; the production TU retains its literal committed include.
set(_pg_igc_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/idempotency_guard_real_path_mutation)
set(_pg_igc_rp_mut_inc ${_pg_igc_rp_work}/mutated_printer.inc)

add_custom_command(OUTPUT ${_pg_igc_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_igc_rp_work}
    -DOUT=${_pg_igc_rp_mut_inc}
    -DNODE=idempotency_guard_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path IdempotencyGuardComment witness ( C2)")
add_custom_target(postgres-idempotencyguard-real-path-mutated-inc
  DEPENDS ${_pg_igc_rp_mut_inc})

set(_pg_igc_rp_mut_tu ${_pg_igc_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_igc_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_igc_rp_mut_inc}
    -DOUT=${_pg_igc_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_igc_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include PostgresModel.cpp copy for the C2 real-path witness")
add_custom_target(postgres-idempotencyguard-real-path-mutated-tu
  DEPENDS ${_pg_igc_rp_mut_tu})

add_executable(postgres-idempotencyguard-render-mutated-real
  test/postgres_effect_render_driver.cpp
  ${_pg_igc_rp_mut_tu})
add_dependencies(postgres-idempotencyguard-render-mutated-real
  postgres-idempotencyguard-real-path-mutated-tu)
target_include_directories(postgres-idempotencyguard-render-mutated-real PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-idempotencyguard-render-mutated-real PRIVATE NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-idempotencyguardcomment-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-idempotencyguard-render-mutated-real>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=-- idempotency guard (replay-safe): one row per workflow key"
  "-DMUTATED_LINE=-- idempotency guard (replay-safe): one row per workflow keX"
  -DNODE_LABEL=IdempotencyGuardComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-idempotencyguardcomment-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  C3 production-path mutation witness: the same real balanced effectful
# spec, compiled against a test-only model TU whose generated handler comes
# from a BalancedInvariantComment-mutated .td.
set(_pg_bic_rp_work ${CMAKE_CURRENT_BINARY_DIR}/test/balanced_invariant_real_path_mutation)
set(_pg_bic_rp_mut_inc ${_pg_bic_rp_work}/mutated_printer.inc)
add_custom_command(OUTPUT ${_pg_bic_rp_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_bic_rp_work}
    -DOUT=${_pg_bic_rp_mut_inc}
    -DNODE=balanced_invariant_comment
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS model/PostgresTargetNodes.td ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a .td-mutated include for the real-path BalancedInvariantComment witness ( C3)")
add_custom_target(postgres-balancedinvariant-real-path-mutated-inc
  DEPENDS ${_pg_bic_rp_mut_inc})

set(_pg_bic_rp_mut_tu ${_pg_bic_rp_work}/PostgresModel_mutated.cpp)
add_custom_command(OUTPUT ${_pg_bic_rp_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_bic_rp_mut_inc}
    -DOUT=${_pg_bic_rp_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/model/PostgresModel.cpp ${_pg_bic_rp_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutated-include PostgresModel.cpp copy for the C3 real-path witness")
add_custom_target(postgres-balancedinvariant-real-path-mutated-tu
  DEPENDS ${_pg_bic_rp_mut_tu})

add_executable(postgres-balancedinvariant-render-mutated-real
  test/postgres_effect_render_driver.cpp
  ${_pg_bic_rp_mut_tu})
add_dependencies(postgres-balancedinvariant-render-mutated-real
  postgres-balancedinvariant-real-path-mutated-tu)
target_include_directories(postgres-balancedinvariant-render-mutated-real PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(postgres-balancedinvariant-render-mutated-real PRIVATE NeutrinoBackendPostgres)

neutrino_register_test(NAME postgres-balancedinvariantcomment-real-path-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:postgres-effect-render-committed>
  -DMUTATED=$<TARGET_FILE:postgres-balancedinvariant-render-mutated-real>
  -DSPEC=${_pg_rp_spec}
  "-DCOMMITTED_LINE=-- balanced invariant: this workflow key must net to zero"
  "-DMUTATED_LINE=-- balanced invariant: this workflow key must net to zerX"
  -DNODE_LABEL=BalancedInvariantComment
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_real_path_mutation_pair.cmake)
neutrino_register_test_properties(postgres-balancedinvariantcomment-real-path-mutation PROPERTIES LABELS "contract;ctest-native")

#  compile-NEGATIVE endpoint: the deleted RawCap/rawLine/Impl names cannot
# be used, PgStmt cannot be aggregate-built or mutated, and an external TU that
# completes the formerly friended PgStmtCtorProbe name still cannot reach the
# private constructor. Each attack is compiled independently and must fail.
# Join include dirs with `|` (not `;`, which CTest would split).
#  R1: pg_raw_seam_sealed.cpp #includes the moved model/PostgresModel.h (bare,
# byte-identical to the pre- flat header). The package subdirs restore the
# flat-sibling resolution for its bare includes so each probe reaches its intended
# seal diagnostic instead of a spurious file-not-found.
set(_pg_seal_incs
  "${LLVM_INCLUDE_DIRS};${MLIR_INCLUDE_DIRS};${PROJECT_SOURCE_DIR}/include;${PROJECT_BINARY_DIR}/include;${CMAKE_CURRENT_SOURCE_DIR};${CMAKE_CURRENT_SOURCE_DIR}/model;${_postgres_generated_dir};${CMAKE_CURRENT_SOURCE_DIR}/provider;${CMAKE_CURRENT_SOURCE_DIR}/leaf")
string(REPLACE ";" "|" _pg_seal_incs "${_pg_seal_incs}")
# probe=EXPECT diagnostic substring (regex).
set(_pg_seal_probes
  "PROBE_RAWCAP_REMOVED=RawCap"
  "PROBE_RAWLINE_REMOVED=rawLine"
  "PROBE_IMPL_REMOVED=Impl"
  "PROBE_AGGREGATE=private constructor"
  "PROBE_MUTATION=const-qualified"
  "PROBE_CTOR_PROBE_COMPLETION=private constructor")
foreach(_probe IN LISTS _pg_seal_probes)
  string(REPLACE "=" ";" _pp "${_probe}")
  list(GET _pp 0 _pdef)
  list(GET _pp 1 _pexpect)
  neutrino_register_test(NAME postgres-raw-seam-sealed.${_pdef} COMMAND ${CMAKE_COMMAND}
    -DCXX=${CMAKE_CXX_COMPILER} -DSTD=gnu++17
    "-DSYSROOT=${CMAKE_OSX_SYSROOT}"
    -DSRC=${PROJECT_SOURCE_DIR}/test/cmake/pg_raw_seam_sealed.cpp
    "-DINCS=${_pg_seal_incs}"
    -DDEFINE=${_pdef} "-DEXPECT=${_pexpect}"
    -P ${PROJECT_SOURCE_DIR}/test/cmake/compile_should_fail.cmake)
  neutrino_register_test_properties(postgres-raw-seam-sealed.${_pdef}
    PROPERTIES LABELS "contract;ctest-native")
endforeach()

#  slice 2 — the fail-closed pgddl::RawSql DDL funnel. Compile-NEGATIVE
# probes: an external TU must not be able to author a RawSql from a bare string,
# append raw text into one, extract its raw bytes, or forge/mint the DdlCap
# capability. Each is compiled INDEPENDENTLY and passes iff it fails to compile
# with its expected diagnostic.
set(_pg_rawsql_probes
  "PROBE_FROM_STRING=private constructor"
  "PROBE_APPEND_STRING=invalid operands"
  "PROBE_APPEND_CHARPTR=invalid operands"
  "PROBE_RAW_EXTRACT=private member"
  "PROBE_CAP_FORGE=private member"
  "PROBE_CAP_CTOR=private constructor"
  # : the backend-package sink is ONE exact symbol; a different package
  # function cannot inherit the grant.
  "PROBE_PACKAGE_UNREGISTERED_EXTRACT=private member"
)
foreach(_probe IN LISTS _pg_rawsql_probes)
  string(REPLACE "=" ";" _pp "${_probe}")
  list(GET _pp 0 _pdef)
  list(GET _pp 1 _pexpect)
  neutrino_register_test(NAME pg-rawsql-sealed.${_pdef} COMMAND ${CMAKE_COMMAND}
    -DCXX=${CMAKE_CXX_COMPILER} -DSTD=gnu++17
    "-DSYSROOT=${CMAKE_OSX_SYSROOT}"
    -DSRC=${PROJECT_SOURCE_DIR}/test/cmake/pg_rawsql_sealed.cpp
    "-DINCS=${_pg_seal_incs}"
    -DDEFINE=${_pdef} "-DEXPECT=${_pexpect}"
    -P ${PROJECT_SOURCE_DIR}/test/cmake/compile_should_fail.cmake)
  neutrino_register_test_properties(pg-rawsql-sealed.${_pdef}
    PROPERTIES LABELS "contract;ctest-native")
endforeach()

# : the  channel-2 raw-text authority checks (pg-channel2-*) and the
# raw-text/section/guard compile-negative probes are RETIRED with the raw
# PL/pgSQL text machinery (sql:: emitter + pgtext::authorLine/Seam). The
# PostgreSQL render path is fully on the generated PgStmt -> generated_printer
# pipeline; the pg-rawsql-sealed.* and postgres-raw-seam-sealed.* probes above
# still guard the live pgddl DDL-carrier funnel.

# /: materialize the separately linked PostgreSQL package into the
# build tree's installed-layout discovery root, mirroring the Solidity block in
# lib/backends/solidity/CMakeLists.txt. Ordinary build-tree consumers then
# traverse the same verified descriptor/startup/protocol seam as an installed
# package; the core target registry retains no PostgreSQL edge through it.
add_executable(neutrino-postgres-repository-backend
  ${PROJECT_SOURCE_DIR}/packaging/postgres/src/PostgresBackendMain.cpp
  ${PROJECT_SOURCE_DIR}/packaging/postgres/src/PostgresPackageArtifacts.cpp)
set_target_properties(neutrino-postgres-repository-backend PROPERTIES
  OUTPUT_NAME neutrino-postgres-backend)
target_include_directories(neutrino-postgres-repository-backend PRIVATE
  ${PROJECT_SOURCE_DIR}/packaging/postgres/src
  ${CMAKE_CURRENT_SOURCE_DIR}
  # : generated artifacts resolve from the BUILD tree.
  ${_postgres_generated_dir}
  ${CMAKE_CURRENT_SOURCE_DIR}/leaf
  ${CMAKE_CURRENT_SOURCE_DIR}/model
  ${CMAKE_CURRENT_SOURCE_DIR}/provider)
target_link_libraries(neutrino-postgres-repository-backend PRIVATE
  NeutrinoBackendPostgres NeutrinoSpecContract)
add_dependencies(neutrino-postgres-repository-backend
  postgres-target-registry-inc postgres-recipe-builders-inc)

# NOT under tools/lib/neutrino/backend-packages: that is the DEFAULT discovery
# root, and while the built-in "postgres" row still exists (its retirement is
# deferred  work) a package there makes the catalog refuse EVERY target
# with E_PACKAGE_DUPLICATE_TARGET -- it poisons capability-spec generation too,
# not just postgres. The  acceptance driver points at this path explicitly,
# so the package is fully real and fully verified without displacing the
# built-in route this PR must preserve.
set(NEUTRINO_POSTGRES_REPOSITORY_PACKAGE_DIR
  "${CMAKE_BINARY_DIR}/tools/lib/neutrino/extraction-candidates/postgres"
  CACHE INTERNAL "Verified build-tree PostgreSQL extraction candidate ()")
set(_postgres_repository_descriptor
  "${NEUTRINO_POSTGRES_REPOSITORY_PACKAGE_DIR}/backend-package.json")
set(_postgres_repository_entry
  "${NEUTRINO_POSTGRES_REPOSITORY_PACKAGE_DIR}/bin/neutrino-postgres-backend")
add_custom_command(
  OUTPUT ${_postgres_repository_descriptor} ${_postgres_repository_entry}
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/packaging/postgres/scripts/materialize_repository_package.py
    --materialize-package
    --binary $<TARGET_FILE:neutrino-postgres-repository-backend>
    --package-dir ${NEUTRINO_POSTGRES_REPOSITORY_PACKAGE_DIR}
  DEPENDS
    neutrino-postgres-repository-backend
    ${PROJECT_SOURCE_DIR}/packaging/postgres/scripts/materialize_repository_package.py
    ${PROJECT_SOURCE_DIR}/packaging/postgres/extraction-manifest.json
    ${PROJECT_SOURCE_DIR}/examples/target-profiles/postgres.target-profile.json
  VERBATIM)
add_custom_target(neutrino-postgres-repository-package ALL
  DEPENDS ${_postgres_repository_descriptor} ${_postgres_repository_entry})

#  acceptance scaffolding (NOT shipped in the extracted package): drives the
# verified package over the real protocol via discovery + BackendInvoker.
add_executable(neutrino-postgres-package-invoke
  ${PROJECT_SOURCE_DIR}/packaging/postgres/src/PostgresPackageInvokeDriver.cpp)
target_link_libraries(neutrino-postgres-package-invoke PRIVATE
  NeutrinoSpecContract NeutrinoFrontend)
target_include_directories(neutrino-postgres-package-invoke PRIVATE
  ${_postgres_generated_dir})
