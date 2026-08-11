#  production mutation proof for CoordinationStatusTable. The committed and
# .td-mutated binaries both run the complete neutrino-gen PostgreSQL path for
# one effectful and one evidence-only fixture. C++ retains rail selection and
# preflight composition; only the generated table shape may change.

foreach(_required COMMITTED MUTATED OUT_ROOT EFFECTFUL_INPUT
                  EFFECTFUL_SCENARIO EVIDENCE_INPUT EVIDENCE_SCENARIO)
  if(NOT DEFINED ${_required})
    message(FATAL_ERROR
      "coordination-status real-path mutation: missing ${_required}")
  endif()
endforeach()

set(_committed_token "attested        boolean NOT NULL DEFAULT false")
set(_mutated_token "attested        bigint  NOT NULL DEFAULT 0")
set(_table_marker "CREATE TABLE IF NOT EXISTS coordination_status (")
set(_preflight_marker
    "-- Upgrade preflight (): refuse a pre-(procedure, key) `coordination_status`")

function(_prove_coordination_path _label _input _scenario _evidence_only)
  set(_committed_dir "${OUT_ROOT}/${_label}/committed")
  set(_mutated_dir "${OUT_ROOT}/${_label}/mutated")
  file(REMOVE_RECURSE "${OUT_ROOT}/${_label}")

  execute_process(
    COMMAND "${COMMITTED}" --target=postgres "--scenario=${_scenario}"
            "${_input}" -o "${_committed_dir}"
    RESULT_VARIABLE _committed_rc
    OUTPUT_VARIABLE _committed_stdout
    ERROR_VARIABLE _committed_stderr)
  if(NOT _committed_rc EQUAL 0)
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): committed neutrino-gen "
      "failed (${_committed_rc}):\n${_committed_stdout}\n${_committed_stderr}")
  endif()

  execute_process(
    COMMAND "${MUTATED}" --target=postgres "--scenario=${_scenario}"
            "${_input}" -o "${_mutated_dir}"
    RESULT_VARIABLE _mutated_rc
    OUTPUT_VARIABLE _mutated_stdout
    ERROR_VARIABLE _mutated_stderr)
  if(NOT _mutated_rc EQUAL 0)
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): mutated neutrino-gen failed "
      "(${_mutated_rc}):\n${_mutated_stdout}\n${_mutated_stderr}")
  endif()

  file(READ "${_committed_dir}/schema.sql" _committed_schema)
  file(READ "${_mutated_dir}/schema.sql" _mutated_schema)

  string(FIND "${_committed_schema}" "${_committed_token}" _committed_at)
  string(FIND "${_mutated_schema}" "${_mutated_token}" _mutated_at)
  string(FIND "${_mutated_schema}" "${_committed_token}" _stale_at)
  if(_committed_at EQUAL -1 OR _mutated_at EQUAL -1 OR NOT _stale_at EQUAL -1)
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): CoordinationStatusTable did "
      "not change through the production schema path")
  endif()

  string(FIND "${_committed_schema}" "${_preflight_marker}" _preflight_at)
  string(FIND "${_committed_schema}" "${_table_marker}" _table_at)
  if(_preflight_at EQUAL -1 OR _table_at EQUAL -1 OR
     NOT _preflight_at LESS _table_at)
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): preflight/table ordering drifted")
  endif()

  string(FIND "${_committed_schema}"
         "CREATE TABLE IF NOT EXISTS ledger_balance (" _ledger_at)
  if(_evidence_only AND NOT _ledger_at EQUAL -1)
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): evidence-only selection "
      "unexpectedly emitted effectful ledger schema")
  elseif(NOT _evidence_only AND _ledger_at EQUAL -1)
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): effectful selection lost its "
      "ledger schema")
  endif()

  string(REPLACE "${_mutated_token}" "${_committed_token}"
         _normalized_mutated "${_mutated_schema}")
  if(NOT "${_normalized_mutated}" STREQUAL "${_committed_schema}")
    message(FATAL_ERROR
      "coordination-status mutation (${_label}): schema bytes beyond the "
      "selected TableGen mutation changed")
  endif()
endfunction()

_prove_coordination_path("effectful" "${EFFECTFUL_INPUT}"
                         "${EFFECTFUL_SCENARIO}" FALSE)
_prove_coordination_path("evidence" "${EVIDENCE_INPUT}"
                         "${EVIDENCE_SCENARIO}" TRUE)

message(STATUS
  "CoordinationStatusTable mutation reaches effectful and evidence-only "
  "production paths; all other SQL bytes and preflight ordering remain exact")
