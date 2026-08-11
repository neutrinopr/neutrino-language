#  production mutation proof for AuthorizedObserverTable. The same complete
# neutrino-gen PostgreSQL project path is run with the committed backend and a
# test-only PostgresModel.cpp copy compiled against a real .td-mutated unified
# printer. Both the single-policy and temporal schema routes must consume the
# node, and every other schema byte (including preflight order) must stay exact.

foreach(_required COMMITTED MUTATED OUT_ROOT SINGLE_INPUT SINGLE_SCENARIO
                  TEMPORAL_INPUT TEMPORAL_SCENARIO)
  if(NOT DEFINED ${_required})
    message(FATAL_ERROR "schema real-path mutation: missing ${_required}")
  endif()
endforeach()

set(_committed_token "observer_id  text NOT NULL")
set(_mutated_token "observer_id  bigint NOT NULL")
set(_table_marker "CREATE TABLE IF NOT EXISTS authorized_observer (")

function(_prove_schema_path _label _input _scenario _preflight_marker)
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
      "schema real-path mutation (${_label}): committed neutrino-gen failed "
      "(${_committed_rc}):\n${_committed_stdout}\n${_committed_stderr}")
  endif()

  execute_process(
    COMMAND "${MUTATED}" --target=postgres "--scenario=${_scenario}"
            "${_input}" -o "${_mutated_dir}"
    RESULT_VARIABLE _mutated_rc
    OUTPUT_VARIABLE _mutated_stdout
    ERROR_VARIABLE _mutated_stderr)
  if(NOT _mutated_rc EQUAL 0)
    message(FATAL_ERROR
      "schema real-path mutation (${_label}): mutated neutrino-gen failed "
      "(${_mutated_rc}):\n${_mutated_stdout}\n${_mutated_stderr}")
  endif()

  file(READ "${_committed_dir}/schema.sql" _committed_schema)
  file(READ "${_mutated_dir}/schema.sql" _mutated_schema)

  string(FIND "${_committed_schema}" "${_committed_token}" _committed_at)
  string(FIND "${_mutated_schema}" "${_mutated_token}" _mutated_at)
  string(FIND "${_mutated_schema}" "${_committed_token}" _stale_at)
  if(_committed_at EQUAL -1 OR _mutated_at EQUAL -1 OR NOT _stale_at EQUAL -1)
    message(FATAL_ERROR
      "schema real-path mutation (${_label}): AuthorizedObserverTable did not "
      "change through the production schema path")
  endif()

  string(FIND "${_committed_schema}" "${_table_marker}" _table_at)
  string(FIND "${_committed_schema}" "${_preflight_marker}" _preflight_at)
  if(_table_at EQUAL -1 OR _preflight_at EQUAL -1 OR
     NOT _table_at LESS _preflight_at)
    message(FATAL_ERROR
      "schema real-path mutation (${_label}): authorized_observer/preflight "
      "ordering drifted")
  endif()

  string(REPLACE "${_mutated_token}" "${_committed_token}"
         _normalized_mutated "${_mutated_schema}")
  if(NOT "${_normalized_mutated}" STREQUAL "${_committed_schema}")
    message(FATAL_ERROR
      "schema real-path mutation (${_label}): schema bytes beyond the selected "
      "TableGen mutation changed")
  endif()
endfunction()

_prove_schema_path("single" "${SINGLE_INPUT}" "${SINGLE_SCENARIO}"
                   "-- Upgrade preflight (): refuse a pre-(procedure, key) `quorum_acceptance`")
_prove_schema_path("temporal" "${TEMPORAL_INPUT}" "${TEMPORAL_SCENARIO}"
                   "-- Temporal upgrade preflight ()")

message(STATUS
  "AuthorizedObserverTable mutation reaches both production schema paths; "
  "all other SQL bytes and preflight ordering remain exact")
