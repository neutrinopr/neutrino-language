# Production mutation proof for the single-policy QuorumAcceptanceTable ().
# The mutated TableGen shape must drive the single-policy quorum schema wherever
# it is selected — the effectful gated path AND the gated evidence-only path,
# which both render the single quorum_acceptance shape — while remaining absent
# from the temporal path (which selects the separate handwritten temporal
# quorum_acceptance) and from a non-quorum coordination. Every other byte stays
# exact.

foreach(_required COMMITTED MUTATED OUT_ROOT QUORUM_INPUT QUORUM_SCENARIO
                  EVIDENCE_INPUT EVIDENCE_SCENARIO TEMPORAL_INPUT TEMPORAL_SCENARIO
                  NONQUORUM_INPUT NONQUORUM_SCENARIO)
  if(NOT DEFINED ${_required})
    message(FATAL_ERROR "quorum-acceptance-table real-path mutation: missing ${_required}")
  endif()
endforeach()

# The single-policy primary key `(procedure, claim_id)` is the one token unique
# to the single QuorumAcceptanceTable shape — every column line is byte-identical
# to the temporal shape, whose key ends `(procedure, claim_id, policy)`.
set(_committed_token "PRIMARY KEY (procedure, claim_id)")
set(_mutated_token "PRIMARY KEY (procedure, claim_idX)")
set(_observer_marker "CREATE TABLE IF NOT EXISTS authorized_observer (")
set(_table_marker "CREATE TABLE IF NOT EXISTS quorum_acceptance (")

function(_run_schema _binary _input _scenario _out_dir _result_var)
  file(REMOVE_RECURSE "${_out_dir}")
  execute_process(
    COMMAND "${_binary}" --target=postgres "--scenario=${_scenario}"
            "${_input}" -o "${_out_dir}"
    RESULT_VARIABLE _rc OUTPUT_VARIABLE _stdout ERROR_VARIABLE _stderr)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR
      "quorum-acceptance-table mutation: neutrino-gen failed (${_rc}):\n${_stdout}\n${_stderr}")
  endif()
  file(READ "${_out_dir}/schema.sql" _schema)
  set(${_result_var} "${_schema}" PARENT_SCOPE)
endfunction()

# The single-policy quorum schema is driven by the node — the mutation lands and
# nothing else moves. Used for both the effectful gated and gated evidence-only
# selections.
function(_prove_present _name _input _scenario)
  _run_schema("${COMMITTED}" "${_input}" "${_scenario}"
              "${OUT_ROOT}/${_name}/committed" _committed_schema)
  _run_schema("${MUTATED}" "${_input}" "${_scenario}"
              "${OUT_ROOT}/${_name}/mutated" _mutated_schema)

  string(FIND "${_committed_schema}" "${_committed_token}" _committed_at)
  string(FIND "${_mutated_schema}" "${_mutated_token}" _mutated_at)
  string(FIND "${_mutated_schema}" "${_committed_token}" _stale_at)
  if(_committed_at EQUAL -1 OR _mutated_at EQUAL -1 OR NOT _stale_at EQUAL -1)
    message(FATAL_ERROR
      "quorum-acceptance-table mutation: the node did not drive the ${_name} "
      "single-policy quorum schema")
  endif()
  string(FIND "${_committed_schema}" "${_observer_marker}" _obs_at)
  string(FIND "${_committed_schema}" "${_table_marker}" _tab_at)
  if(_obs_at EQUAL -1 OR _tab_at EQUAL -1 OR NOT _obs_at LESS _tab_at)
    message(FATAL_ERROR
      "quorum-acceptance-table mutation: ${_name} declaration ordering drifted")
  endif()
  string(REPLACE "${_mutated_token}" "${_committed_token}" _norm "${_mutated_schema}")
  if(NOT "${_norm}" STREQUAL "${_committed_schema}")
    message(FATAL_ERROR
      "quorum-acceptance-table mutation: ${_name} bytes beyond the selected "
      "mutation changed")
  endif()
endfunction()

# The node is NOT selected here (temporal uses the separate handwritten shape;
# a non-quorum coordination emits no quorum_acceptance), so the mutation cannot
# change a single byte.
function(_prove_excluded_path _name _input _scenario)
  _run_schema("${COMMITTED}" "${_input}" "${_scenario}"
              "${OUT_ROOT}/${_name}/committed" _committed_schema)
  _run_schema("${MUTATED}" "${_input}" "${_scenario}"
              "${OUT_ROOT}/${_name}/mutated" _mutated_schema)
  string(FIND "${_mutated_schema}" "${_mutated_token}" _leaked)
  if(NOT _leaked EQUAL -1 OR NOT "${_committed_schema}" STREQUAL "${_mutated_schema}")
    message(FATAL_ERROR
      "quorum-acceptance-table mutation: the single-policy node leaked into the "
      "${_name} path")
  endif()
endfunction()

_prove_present("quorum" "${QUORUM_INPUT}" "${QUORUM_SCENARIO}")
_prove_present("evidence" "${EVIDENCE_INPUT}" "${EVIDENCE_SCENARIO}")
_prove_excluded_path("temporal" "${TEMPORAL_INPUT}" "${TEMPORAL_SCENARIO}")
_prove_excluded_path("non-quorum" "${NONQUORUM_INPUT}" "${NONQUORUM_SCENARIO}")

message(STATUS
  "QuorumAcceptanceTable mutation drives the single-policy quorum schema "
  "(effectful + gated evidence-only) and is absent from the temporal and "
  "non-quorum paths; all other bytes exact")
