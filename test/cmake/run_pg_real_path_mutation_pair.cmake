# [] Real-generator .td mutation on the PRODUCTION surface. Runs the
# actual planFromSpec -> generatePostgresProcedureFromSpec (legalizePostgres /
# legalizeEffectful / PgStmt::effectLedgerComment / printPostgres) path on a real
# effectful capability-spec:
#   * the COMMITTED driver must emit the exact committed target-node line
#     (proving the real factory + routing produce it — the negative bites if
#     legalization stops emitting the node or its factory is deleted);
#   * the driver built with PostgresModel.cpp recompiled against a .td-MUTATED
#     include must emit the MUTATED shape and NOT the committed shape (proving the
#     .td record drives production bytes through the real path, not just the
#     standalone handler).
#
# Invoked as a CTest:
#   cmake -DCOMMITTED=<exe> -DMUTATED=<exe> -DSPEC=<spec.json>
#         -DCOMMITTED_LINE=<...> -DMUTATED_LINE=<...> -DNODE_LABEL=<...> -P this

if(NOT DEFINED NODE_LABEL)
  set(NODE_LABEL "EffectLedgerComment")
endif()

execute_process(COMMAND "${COMMITTED}" "${SPEC}"
  RESULT_VARIABLE _crc OUTPUT_VARIABLE _cout ERROR_VARIABLE _cerr)
if(NOT _crc EQUAL 0)
  message(FATAL_ERROR "real-path mutation: the COMMITTED driver failed (rc=${_crc}):\n${_cerr}")
endif()
string(FIND "${_cout}" "${COMMITTED_LINE}" _has_committed)
if(_has_committed EQUAL -1)
  message(FATAL_ERROR
    "real-path mutation: the COMMITTED real render did NOT contain the expected "
    "${NODE_LABEL} line:\n  [${COMMITTED_LINE}]\n"
    "the real legalization/${NODE_LABEL} routing is broken or removed.")
endif()

execute_process(COMMAND "${MUTATED}" "${SPEC}"
  RESULT_VARIABLE _mrc OUTPUT_VARIABLE _mout ERROR_VARIABLE _merr)
if(NOT _mrc EQUAL 0)
  message(FATAL_ERROR "real-path mutation: the MUTATED driver failed (rc=${_mrc}):\n${_merr}")
endif()
# The mutated real render must carry the mutated shape and must NOT reproduce the
# committed line (the mutation genuinely changed production output, not crashed).
string(FIND "${_mout}" "${MUTATED_LINE}" _has_mutated)
string(FIND "${_mout}" "${COMMITTED_LINE}" _mut_has_committed)
if(_has_mutated EQUAL -1 OR NOT _mut_has_committed EQUAL -1)
  message(FATAL_ERROR
    "real-path mutation: the .td-mutated real render did not change the "
    "${NODE_LABEL} line as expected (want [${MUTATED_LINE}], not "
    "[${COMMITTED_LINE}]):\n${_mout}")
endif()

message(STATUS
  "real-path mutation holds for ${NODE_LABEL}: the committed real legalize/print "
  "path emits the node, and the .td mutation changes it through the real factory.")
