add_llvm_executable(neutrino-gen neutrino-gen.cpp)

llvm_update_compile_flags(neutrino-gen)
target_link_libraries(neutrino-gen PRIVATE NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
if(NEUTRINO_CORE_ONLY)
  target_compile_definitions(neutrino-gen PRIVATE NEUTRINO_CORE_ONLY=1)
endif()

mlir_check_all_link_libraries(neutrino-gen)

if(NOT NEUTRINO_CORE_ONLY)
#  governing production-path mutation witness for the shared
# AuthorizedObserverTable schema node. Recompile the real PostgresModel.cpp
# against a PostgresTargetNodes.td-mutated unified printer include, then run the
# complete neutrino-gen PostgreSQL project path for both the single-policy and
# temporal schemas. The generated schemas must differ only at the mutated node.
# Keep the mutation-only TU under a test path so the channel-2 symbol-ownership
# gate excludes this intentional duplicate exactly like the existing backend
# real-path witnesses.
set(_pg_schema_mut_work ${CMAKE_CURRENT_BINARY_DIR}/test/authorized_observer_real_path)
set(_pg_schema_mut_inc ${_pg_schema_mut_work}/mutated_printer.inc)
set(_pg_schema_mut_tu ${_pg_schema_mut_work}/PostgresModel_mutated.cpp)
set(_pg_backend_dir ${PROJECT_SOURCE_DIR}/lib/backends/postgres)

add_custom_command(OUTPUT ${_pg_schema_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_schema_mut_work}
    -DOUT=${_pg_schema_mut_inc}
    -DNODE=authorized_observer
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating an AuthorizedObserverTable-mutated unified PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_schema_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_schema_mut_inc}
    -DOUT=${_pg_schema_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_schema_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the mutation-only production PostgresModel.cpp copy for ")

add_custom_target(postgres-schema-real-path-mutated-tu
  DEPENDS ${_pg_schema_mut_tu})

add_executable(neutrino-gen-schema-mutated
  neutrino-gen.cpp
  ${_pg_schema_mut_tu})
add_dependencies(neutrino-gen-schema-mutated
  postgres-schema-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-schema-mutated)
target_include_directories(neutrino-gen-schema-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-schema-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-schema-mutated)

neutrino_register_test(NAME postgres-authorizedobserver-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-schema-mutated>
    -DOUT_ROOT=${_pg_schema_mut_work}/runs
    -DSINGLE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DSINGLE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    -DTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_schema_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-authorizedobserver-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

#  second schema slice: mutate CoordinationStatusTable in the same unified
# PgSchemaDecl registry and recompile the exact production PostgresModel.cpp.
# The resulting complete neutrino-gen binary must carry that mutation through
# both the effectful schemaSql and evidence-only schemaSqlEvidence selections.
set(_pg_coord_mut_work ${CMAKE_CURRENT_BINARY_DIR}/test/coordination_status_real_path)
set(_pg_coord_mut_inc ${_pg_coord_mut_work}/mutated_printer.inc)
set(_pg_coord_mut_tu ${_pg_coord_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_coord_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_coord_mut_work}
    -DOUT=${_pg_coord_mut_inc}
    -DNODE=coordination_status
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a CoordinationStatusTable-mutated unified PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_coord_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_coord_mut_inc}
    -DOUT=${_pg_coord_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_coord_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the CoordinationStatusTable mutation-only production model copy")

add_custom_target(postgres-coordination-status-real-path-mutated-tu
  DEPENDS ${_pg_coord_mut_tu})

add_executable(neutrino-gen-coordination-status-mutated
  neutrino-gen.cpp
  ${_pg_coord_mut_tu})
add_dependencies(neutrino-gen-coordination-status-mutated
  postgres-coordination-status-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-coordination-status-mutated)
target_include_directories(neutrino-gen-coordination-status-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-coordination-status-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-coordination-status-mutated)

neutrino_register_test(NAME postgres-coordinationstatus-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-coordination-status-mutated>
    -DOUT_ROOT=${_pg_coord_mut_work}/runs
    -DEFFECTFUL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DEFFECTFUL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_coordination_status_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-coordinationstatus-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

# Recompile the production PostgreSQL model against a LedgerBalanceTable
# mutation, then exercise both the effectful selection and evidence-only
# exclusion through complete neutrino-gen runs.
set(_pg_ledger_mut_work ${CMAKE_CURRENT_BINARY_DIR}/test/ledger_balance_real_path)
set(_pg_ledger_mut_inc ${_pg_ledger_mut_work}/mutated_printer.inc)
set(_pg_ledger_mut_tu ${_pg_ledger_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_ledger_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_ledger_mut_work}
    -DOUT=${_pg_ledger_mut_inc}
    -DNODE=ledger_balance
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a LedgerBalanceTable-mutated unified PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_ledger_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_ledger_mut_inc}
    -DOUT=${_pg_ledger_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_ledger_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the LedgerBalanceTable mutation-only production model copy")

add_custom_target(postgres-ledger-balance-real-path-mutated-tu
  DEPENDS ${_pg_ledger_mut_tu})

add_executable(neutrino-gen-ledger-balance-mutated
  neutrino-gen.cpp
  ${_pg_ledger_mut_tu})
add_dependencies(neutrino-gen-ledger-balance-mutated
  postgres-ledger-balance-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-ledger-balance-mutated)
target_include_directories(neutrino-gen-ledger-balance-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-ledger-balance-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-ledger-balance-mutated)

neutrino_register_test(NAME postgres-ledgerbalance-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-ledger-balance-mutated>
    -DOUT_ROOT=${_pg_ledger_mut_work}/runs
    -DEFFECTFUL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DEFFECTFUL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_ledger_balance_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-ledgerbalance-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

# Recompile the production PostgreSQL model against a PostingIdempotencyTable
# mutation, then exercise both the effectful selection and evidence-only
# exclusion through complete neutrino-gen runs.
set(_pg_pi_table_mut_work
  ${CMAKE_CURRENT_BINARY_DIR}/test/posting_idempotency_table_real_path)
set(_pg_pi_table_mut_inc ${_pg_pi_table_mut_work}/mutated_printer.inc)
set(_pg_pi_table_mut_tu ${_pg_pi_table_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_pi_table_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_pi_table_mut_work}
    -DOUT=${_pg_pi_table_mut_inc}
    -DNODE=posting_idempotency_table
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a PostingIdempotencyTable-mutated PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_pi_table_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_pi_table_mut_inc}
    -DOUT=${_pg_pi_table_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_pi_table_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the PostingIdempotencyTable mutation-only model copy")

add_custom_target(postgres-posting-idempotency-table-real-path-mutated-tu
  DEPENDS ${_pg_pi_table_mut_tu})

add_executable(neutrino-gen-posting-idempotency-table-mutated
  neutrino-gen.cpp
  ${_pg_pi_table_mut_tu})
add_dependencies(neutrino-gen-posting-idempotency-table-mutated
  postgres-posting-idempotency-table-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-posting-idempotency-table-mutated)
target_include_directories(neutrino-gen-posting-idempotency-table-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-posting-idempotency-table-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-posting-idempotency-table-mutated)

neutrino_register_test(NAME postgres-postingidempotencytable-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-posting-idempotency-table-mutated>
    -DOUT_ROOT=${_pg_pi_table_mut_work}/runs
    -DEFFECTFUL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DEFFECTFUL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_posting_idempotency_table_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-postingidempotencytable-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

# Recompile the production PostgreSQL model against a CommittedGroupTable
# mutation, then exercise temporal selection and both excluded schema routes.
set(_pg_cg_table_mut_work
  ${CMAKE_CURRENT_BINARY_DIR}/test/committed_group_table_real_path)
set(_pg_cg_table_mut_inc ${_pg_cg_table_mut_work}/mutated_printer.inc)
set(_pg_cg_table_mut_tu ${_pg_cg_table_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_cg_table_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_cg_table_mut_work}
    -DOUT=${_pg_cg_table_mut_inc}
    -DNODE=committed_group_table
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a CommittedGroupTable-mutated PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_cg_table_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_cg_table_mut_inc}
    -DOUT=${_pg_cg_table_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_cg_table_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the CommittedGroupTable mutation-only model copy")

add_custom_target(postgres-committed-group-table-real-path-mutated-tu
  DEPENDS ${_pg_cg_table_mut_tu})

add_executable(neutrino-gen-committed-group-table-mutated
  neutrino-gen.cpp
  ${_pg_cg_table_mut_tu})
add_dependencies(neutrino-gen-committed-group-table-mutated
  postgres-committed-group-table-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-committed-group-table-mutated)
target_include_directories(neutrino-gen-committed-group-table-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-committed-group-table-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-committed-group-table-mutated)

neutrino_register_test(NAME postgres-committedgrouptable-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-committed-group-table-mutated>
    -DOUT_ROOT=${_pg_cg_table_mut_work}/runs
    -DTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    -DTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json
    -DNONTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DNONTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_committed_group_table_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-committedgrouptable-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

#  PostingsTable production mutation proof. TWO mutation-only neutrino-gen
# copies — one mutating the BASE record, one the MEMO record — prove each fixed
# variant drives ITS effectful path (base -> memo-less, memo -> memo), that the
# memo record cannot leak onto the memo-less path, and that neither reaches the
# evidence-only schema. Every other byte stays exact.
set(_pg_postings_base_work ${CMAKE_CURRENT_BINARY_DIR}/test/postings_base_real_path)
set(_pg_postings_base_inc ${_pg_postings_base_work}/mutated_printer.inc)
set(_pg_postings_base_tu ${_pg_postings_base_work}/PostgresModel_mutated.cpp)
set(_pg_postings_memo_work ${CMAKE_CURRENT_BINARY_DIR}/test/postings_memo_real_path)
set(_pg_postings_memo_inc ${_pg_postings_memo_work}/mutated_printer.inc)
set(_pg_postings_memo_tu ${_pg_postings_memo_work}/PostgresModel_mutated.cpp)

foreach(_variant base memo)
  set(_w ${_pg_postings_${_variant}_work})
  set(_inc ${_pg_postings_${_variant}_inc})
  set(_tu ${_pg_postings_${_variant}_tu})
  add_custom_command(OUTPUT ${_inc}
    COMMAND ${CMAKE_COMMAND}
      -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
      -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
      -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
      -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
      -DWORK=${_w} -DOUT=${_inc} -DNODE=postings_${_variant}
      -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
    DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
            ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
            ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
            ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
    COMMENT "Regenerating a postings-${_variant}-mutated unified PostgreSQL printer")
  add_custom_command(OUTPUT ${_tu}
    COMMAND ${CMAKE_COMMAND}
      -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp -DMUT_INC=${_inc} -DOUT=${_tu}
      -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
    DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_inc}
            ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
    COMMENT "Generating the postings-${_variant} mutation-only production model copy")
  add_custom_target(postgres-postings-${_variant}-real-path-mutated-tu DEPENDS ${_tu})
  add_executable(neutrino-gen-postings-${_variant}-mutated neutrino-gen.cpp ${_tu})
  add_dependencies(neutrino-gen-postings-${_variant}-mutated
    postgres-postings-${_variant}-real-path-mutated-tu)
  llvm_update_compile_flags(neutrino-gen-postings-${_variant}-mutated)
  target_include_directories(neutrino-gen-postings-${_variant}-mutated PRIVATE
    ${_pg_backend_dir}
    $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
  target_link_libraries(neutrino-gen-postings-${_variant}-mutated PRIVATE
    NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
  mlir_check_all_link_libraries(neutrino-gen-postings-${_variant}-mutated)
endforeach()

neutrino_register_test(NAME postgres-postingstable-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DBASE_MUTATED=$<TARGET_FILE:neutrino-gen-postings-base-mutated>
    -DMEMO_MUTATED=$<TARGET_FILE:neutrino-gen-postings-memo-mutated>
    -DOUT_ROOT=${_pg_postings_base_work}/runs
    -DMEMOLESS_INPUT=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memoless_fixture.neu
    -DMEMOLESS_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memoless_fixture.scn.json
    -DMEMO_INPUT=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memo_fixture.neu
    -DMEMO_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memo_fixture.scn.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_postings_table_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-postingstable-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

#  KeyClaimTable production mutation proof. One mutation-only neutrino-gen
# copy recompiles the model against a KeyClaimTable-mutated printer; the mutation
# must reach only the temporal schema (last declaration) and stay absent from the
# non-temporal and evidence-only paths, all other bytes exact.
set(_pg_kc_table_mut_work ${CMAKE_CURRENT_BINARY_DIR}/test/key_claim_table_real_path)
set(_pg_kc_table_mut_inc ${_pg_kc_table_mut_work}/mutated_printer.inc)
set(_pg_kc_table_mut_tu ${_pg_kc_table_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_kc_table_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_kc_table_mut_work}
    -DOUT=${_pg_kc_table_mut_inc}
    -DNODE=key_claim_table
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a KeyClaimTable-mutated PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_kc_table_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_kc_table_mut_inc}
    -DOUT=${_pg_kc_table_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_kc_table_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the KeyClaimTable mutation-only model copy")

add_custom_target(postgres-key-claim-table-real-path-mutated-tu
  DEPENDS ${_pg_kc_table_mut_tu})

add_executable(neutrino-gen-key-claim-table-mutated neutrino-gen.cpp ${_pg_kc_table_mut_tu})
add_dependencies(neutrino-gen-key-claim-table-mutated
  postgres-key-claim-table-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-key-claim-table-mutated)
target_include_directories(neutrino-gen-key-claim-table-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-key-claim-table-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-key-claim-table-mutated)

neutrino_register_test(NAME postgres-keyclaimtable-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-key-claim-table-mutated>
    -DOUT_ROOT=${_pg_kc_table_mut_work}/runs
    -DTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    -DTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json
    -DNONTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DNONTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_key_claim_table_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-keyclaimtable-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

#  QuorumAcceptanceTable production mutation proof. One mutation-only
# neutrino-gen copy recompiles the model against a QuorumAcceptanceTable-mutated
# printer; the mutation must drive the single-policy quorum schema wherever it is
# selected (the effectful gated path AND the gated evidence-only path) and stay
# absent from the temporal and non-quorum paths, all other bytes exact.
set(_pg_qa_table_mut_work ${CMAKE_CURRENT_BINARY_DIR}/test/quorum_acceptance_table_real_path)
set(_pg_qa_table_mut_inc ${_pg_qa_table_mut_work}/mutated_printer.inc)
set(_pg_qa_table_mut_tu ${_pg_qa_table_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_qa_table_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_qa_table_mut_work}
    -DOUT=${_pg_qa_table_mut_inc}
    -DNODE=quorum_acceptance_table
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a QuorumAcceptanceTable-mutated PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_qa_table_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_qa_table_mut_inc}
    -DOUT=${_pg_qa_table_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_qa_table_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the QuorumAcceptanceTable mutation-only model copy")

add_custom_target(postgres-quorum-acceptance-table-real-path-mutated-tu
  DEPENDS ${_pg_qa_table_mut_tu})

add_executable(neutrino-gen-quorum-acceptance-table-mutated neutrino-gen.cpp ${_pg_qa_table_mut_tu})
add_dependencies(neutrino-gen-quorum-acceptance-table-mutated
  postgres-quorum-acceptance-table-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-quorum-acceptance-table-mutated)
target_include_directories(neutrino-gen-quorum-acceptance-table-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-quorum-acceptance-table-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-quorum-acceptance-table-mutated)

neutrino_register_test(NAME postgres-quorumacceptancetable-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-quorum-acceptance-table-mutated>
    -DOUT_ROOT=${_pg_qa_table_mut_work}/runs
    -DQUORUM_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DQUORUM_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -DTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    -DTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json
    -DNONQUORUM_INPUT=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memo_fixture.neu
    -DNONQUORUM_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memo_fixture.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_quorum_acceptance_table_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-quorumacceptancetable-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")

#  TemporalQuorumAcceptanceTable production mutation proof. One mutation-only
# neutrino-gen copy recompiles the model against a TemporalQuorumAcceptanceTable-
# mutated printer; the mutation must reach only the temporal per-policy quorum
# schema and stay absent from the single-policy quorum, gated evidence-only and
# non-quorum paths, all other bytes exact.
set(_pg_tqa_table_mut_work ${CMAKE_CURRENT_BINARY_DIR}/test/temporal_quorum_acceptance_table_real_path)
set(_pg_tqa_table_mut_inc ${_pg_tqa_table_mut_work}/mutated_printer.inc)
set(_pg_tqa_table_mut_tu ${_pg_tqa_table_mut_work}/PostgresModel_mutated.cpp)

add_custom_command(OUTPUT ${_pg_tqa_table_mut_inc}
  COMMAND ${CMAKE_COMMAND}
    -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
    -DTD=${_pg_backend_dir}/model/PostgresTargetNodes.td
    -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
    -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -DWORK=${_pg_tqa_table_mut_work}
    -DOUT=${_pg_tqa_table_mut_inc}
    -DNODE=temporal_quorum_acceptance_table
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresTargetNodes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_pg_stmt_shell_inc.cmake
  COMMENT "Regenerating a TemporalQuorumAcceptanceTable-mutated PostgreSQL printer")

add_custom_command(OUTPUT ${_pg_tqa_table_mut_tu}
  COMMAND ${CMAKE_COMMAND}
    -DSRC=${_pg_backend_dir}/model/PostgresModel.cpp
    -DMUT_INC=${_pg_tqa_table_mut_inc}
    -DOUT=${_pg_tqa_table_mut_tu}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  DEPENDS ${_pg_backend_dir}/model/PostgresModel.cpp ${_pg_tqa_table_mut_inc}
          ${PROJECT_SOURCE_DIR}/test/cmake/gen_mutated_postgres_model_tu.cmake
  COMMENT "Generating the TemporalQuorumAcceptanceTable mutation-only model copy")

add_custom_target(postgres-temporal-quorum-acceptance-table-real-path-mutated-tu
  DEPENDS ${_pg_tqa_table_mut_tu})

add_executable(neutrino-gen-temporal-quorum-acceptance-table-mutated neutrino-gen.cpp ${_pg_tqa_table_mut_tu})
add_dependencies(neutrino-gen-temporal-quorum-acceptance-table-mutated
  postgres-temporal-quorum-acceptance-table-real-path-mutated-tu)
llvm_update_compile_flags(neutrino-gen-temporal-quorum-acceptance-table-mutated)
target_include_directories(neutrino-gen-temporal-quorum-acceptance-table-mutated PRIVATE
  ${_pg_backend_dir}
  $<TARGET_PROPERTY:NeutrinoBackendPostgres,INCLUDE_DIRECTORIES>)
target_link_libraries(neutrino-gen-temporal-quorum-acceptance-table-mutated PRIVATE
  NeutrinoEmit NeutrinoFrontend NeutrinoTooling MLIRParser)
mlir_check_all_link_libraries(neutrino-gen-temporal-quorum-acceptance-table-mutated)

neutrino_register_test(NAME postgres-temporalquorumacceptancetable-real-path-mutation
  COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:neutrino-gen>
    -DMUTATED=$<TARGET_FILE:neutrino-gen-temporal-quorum-acceptance-table-mutated>
    -DOUT_ROOT=${_pg_tqa_table_mut_work}/runs
    -DTEMPORAL_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    -DTEMPORAL_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json
    -DQUORUM_INPUT=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery.neu
    -DQUORUM_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/oracle/oracle_delivery_scenario.json
    -DEVIDENCE_INPUT=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.neu
    -DEVIDENCE_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/evidence/shipment_evidence_anchor.scn.json
    -DNONQUORUM_INPUT=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memo_fixture.neu
    -DNONQUORUM_SCENARIO=${PROJECT_SOURCE_DIR}/test/ir/token/Inputs/core_memo_fixture.scn.json
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_pg_temporal_quorum_acceptance_table_real_path_mutation.cmake)
neutrino_register_test_properties(postgres-temporalquorumacceptancetable-real-path-mutation
  PROPERTIES LABELS "contract;ctest-native")
endif()
