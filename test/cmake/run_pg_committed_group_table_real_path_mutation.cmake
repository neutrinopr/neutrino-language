# Production mutation proof for CommittedGroupTable. The changed TableGen shape
# must reach only the temporal schema while every other selected byte and table
# position remains exact.

foreach(_required COMMITTED MUTATED OUT_ROOT TEMPORAL_INPUT TEMPORAL_SCENARIO
                  NONTEMPORAL_INPUT NONTEMPORAL_SCENARIO
                  EVIDENCE_INPUT EVIDENCE_SCENARIO)
  if(NOT DEFINED ${_required})
    message(FATAL_ERROR
      "committed-group-table real-path mutation: missing ${_required}")
  endif()
endforeach()

set(_committed_token "committed_at    timestamptz NOT NULL DEFAULT now()")
set(_mutated_token "committed_at    timestamp   NOT NULL DEFAULT now()")
set(_quorum_marker "CREATE TABLE IF NOT EXISTS quorum_acceptance (")
set(_table_marker "CREATE TABLE IF NOT EXISTS committed_group (")
set(_key_claim_marker "CREATE TABLE IF NOT EXISTS key_claim (")

function(_run_schema _binary _input _scenario _out_dir _result_var)
  file(REMOVE_RECURSE "${_out_dir}")
  execute_process(
    COMMAND "${_binary}" --target=postgres "--scenario=${_scenario}"
            "${_input}" -o "${_out_dir}"
    RESULT_VARIABLE _rc
    OUTPUT_VARIABLE _stdout
    ERROR_VARIABLE _stderr)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR
      "committed-group-table mutation: neutrino-gen failed (${_rc}):\n"
      "${_stdout}\n${_stderr}")
  endif()
  file(READ "${_out_dir}/schema.sql" _schema)
  set(${_result_var} "${_schema}" PARENT_SCOPE)
endfunction()

function(_prove_temporal_path)
  _run_schema("${COMMITTED}" "${TEMPORAL_INPUT}" "${TEMPORAL_SCENARIO}"
              "${OUT_ROOT}/temporal/committed" _committed_schema)
  _run_schema("${MUTATED}" "${TEMPORAL_INPUT}" "${TEMPORAL_SCENARIO}"
              "${OUT_ROOT}/temporal/mutated" _mutated_schema)

  string(FIND "${_committed_schema}" "${_committed_token}" _committed_at)
  string(FIND "${_mutated_schema}" "${_mutated_token}" _mutated_at)
  string(FIND "${_mutated_schema}" "${_committed_token}" _stale_at)
  if(_committed_at EQUAL -1 OR _mutated_at EQUAL -1 OR NOT _stale_at EQUAL -1)
    message(FATAL_ERROR
      "committed-group-table mutation: CommittedGroupTable did not change "
      "through the production temporal schema path")
  endif()

  string(FIND "${_committed_schema}" "${_quorum_marker}" _quorum_at)
  string(FIND "${_committed_schema}" "${_table_marker}" _table_at)
  string(FIND "${_committed_schema}" "${_key_claim_marker}" _key_claim_at)
  if(_quorum_at EQUAL -1 OR _table_at EQUAL -1 OR _key_claim_at EQUAL -1 OR
     NOT _quorum_at LESS _table_at OR NOT _table_at LESS _key_claim_at)
    message(FATAL_ERROR
      "committed-group-table mutation: temporal schema declaration ordering drifted")
  endif()

  string(REPLACE "${_mutated_token}" "${_committed_token}"
         _normalized_mutated "${_mutated_schema}")
  if(NOT "${_normalized_mutated}" STREQUAL "${_committed_schema}")
    message(FATAL_ERROR
      "committed-group-table mutation: schema bytes beyond the selected "
      "TableGen mutation changed")
  endif()
endfunction()

function(_prove_excluded_path _name _input _scenario)
  _run_schema("${COMMITTED}" "${_input}" "${_scenario}"
              "${OUT_ROOT}/${_name}/committed" _committed_schema)
  _run_schema("${MUTATED}" "${_input}" "${_scenario}"
              "${OUT_ROOT}/${_name}/mutated" _mutated_schema)

  string(FIND "${_committed_schema}" "${_table_marker}" _committed_at)
  string(FIND "${_mutated_schema}" "${_table_marker}" _mutated_at)
  if(NOT _committed_at EQUAL -1 OR NOT _mutated_at EQUAL -1)
    message(FATAL_ERROR
      "committed-group-table mutation: ${_name} selection emitted the temporal table")
  endif()
  if(NOT "${_committed_schema}" STREQUAL "${_mutated_schema}")
    message(FATAL_ERROR
      "committed-group-table mutation: an unselected node changed ${_name} SQL")
  endif()
endfunction()

_prove_temporal_path()
_prove_excluded_path("non-temporal" "${NONTEMPORAL_INPUT}" "${NONTEMPORAL_SCENARIO}")
_prove_excluded_path("evidence" "${EVIDENCE_INPUT}" "${EVIDENCE_SCENARIO}")

message(STATUS
  "CommittedGroupTable mutation reaches only the temporal production path; "
  "all other SQL bytes and declaration ordering remain exact")
