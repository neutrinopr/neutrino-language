# [] Prove a node's `.td` syntax record drives production output by RENDERING
# through both the committed and the .td-mutated generated handler:
#   * the COMMITTED handler must reproduce the golden line(s) (exit 0);
#   * the MUTATED handler must NOT (exit != 0) and its render must carry the
#     mutated form, so the failure is caused by the syntax-record mutation, not a
#     crash.
# The PostgreSQL parallel of run_stmt_shell_render_pair.cmake.
#
# Invoked as a CTest:
#   cmake -DCOMMITTED=<exe> -DMUTATED=<exe> -DGOLDEN=<.sql> \
#         [-DMUTATED_EXPECT=<token>] [-DNODE_LABEL=<name>] -P this
# MUTATED_EXPECT/NODE_LABEL default to the ProgressFlag node's values.

if(NOT DEFINED MUTATED_EXPECT)
  set(MUTATED_EXPECT "v_progress ::= false;")
endif()
if(NOT DEFINED NODE_LABEL)
  set(NODE_LABEL "ProgressFlag")
endif()
set(_mutated_expect "${MUTATED_EXPECT}")

execute_process(COMMAND "${COMMITTED}" "${GOLDEN}"
  RESULT_VARIABLE _crc OUTPUT_VARIABLE _cout ERROR_VARIABLE _cerr)
if(NOT _crc EQUAL 0)
  message(FATAL_ERROR
    "PG ${NODE_LABEL} render pair: the COMMITTED generated handler did NOT "
    "reproduce the golden line(s) (rc=${_crc}):\n${_cout}${_cerr}")
endif()

execute_process(COMMAND "${MUTATED}" "${GOLDEN}"
  RESULT_VARIABLE _mrc OUTPUT_VARIABLE _mout ERROR_VARIABLE _merr)
if(_mrc EQUAL 0)
  message(FATAL_ERROR
    "PG ${NODE_LABEL} render pair: the .td-MUTATED generated handler still "
    "reproduced the golden line(s) — the syntax-record mutation did not change "
    "production output:\n${_mout}${_merr}")
endif()
# Non-vacuity: the mutated failure must be the mutated render, not an unrelated crash.
string(FIND "${_mout}" "${_mutated_expect}" _idx)
if(_idx EQUAL -1)
  message(FATAL_ERROR
    "PG ${NODE_LABEL} render pair: the mutated handler failed but did NOT render "
    "the expected `${_mutated_expect}` line (vacuous failure):\n${_mout}${_merr}")
endif()

message(STATUS
  "PG ${NODE_LABEL} render pair holds: committed handler renders the golden "
  "line(s); the .td-mutated handler renders `${_mutated_expect}` and fails it.")
