# Production mutation proof for PostingIdempotencyTable. The changed TableGen
# shape must reach the effectful schema, preserve every other byte and
# declaration position, and remain excluded from the evidence-only schema.

foreach(_required COMMITTED MUTATED OUT_ROOT EFFECTFUL_INPUT
                  EFFECTFUL_SCENARIO EVIDENCE_INPUT EVIDENCE_SCENARIO)
  if(NOT DEFINED ${_required})
    message(FATAL_ERROR
      "posting-idempotency-table real-path mutation: missing ${_required}")
  endif()
endforeach()

set(_committed_token "entry           text NOT NULL")
set(_mutated_token "entry           jsonb NOT NULL")
set(_previous_table_marker "CREATE TABLE IF NOT EXISTS ledger_balance (")
set(_table_marker "CREATE TABLE IF NOT EXISTS posting_idempotency (")
set(_next_table_marker "CREATE TABLE IF NOT EXISTS postings (")

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
      "posting-idempotency-table mutation: neutrino-gen failed (${_rc}):\n"
      "${_stdout}\n${_stderr}")
  endif()
  file(READ "${_out_dir}/schema.sql" _schema)
  set(${_result_var} "${_schema}" PARENT_SCOPE)
endfunction()

function(_prove_effectful_path)
  _run_schema("${COMMITTED}" "${EFFECTFUL_INPUT}" "${EFFECTFUL_SCENARIO}"
              "${OUT_ROOT}/effectful/committed" _committed_schema)
  _run_schema("${MUTATED}" "${EFFECTFUL_INPUT}" "${EFFECTFUL_SCENARIO}"
              "${OUT_ROOT}/effectful/mutated" _mutated_schema)

  string(FIND "${_committed_schema}" "${_committed_token}" _committed_at)
  string(FIND "${_mutated_schema}" "${_mutated_token}" _mutated_at)
  string(FIND "${_mutated_schema}" "${_committed_token}" _stale_at)
  if(_committed_at EQUAL -1 OR _mutated_at EQUAL -1 OR NOT _stale_at EQUAL -1)
    message(FATAL_ERROR
      "posting-idempotency-table mutation: PostingIdempotencyTable did not "
      "change through the production effectful schema path")
  endif()

  string(FIND "${_committed_schema}" "${_previous_table_marker}" _previous_at)
  string(FIND "${_committed_schema}" "${_table_marker}" _table_at)
  string(FIND "${_committed_schema}" "${_next_table_marker}" _next_at)
  if(_previous_at EQUAL -1 OR _table_at EQUAL -1 OR _next_at EQUAL -1 OR
     NOT _previous_at LESS _table_at OR NOT _table_at LESS _next_at)
    message(FATAL_ERROR
      "posting-idempotency-table mutation: schema declaration ordering drifted")
  endif()

  string(REPLACE "${_mutated_token}" "${_committed_token}"
         _normalized_mutated "${_mutated_schema}")
  if(NOT "${_normalized_mutated}" STREQUAL "${_committed_schema}")
    message(FATAL_ERROR
      "posting-idempotency-table mutation: schema bytes beyond the selected "
      "TableGen mutation changed")
  endif()
endfunction()

function(_prove_evidence_path)
  _run_schema("${COMMITTED}" "${EVIDENCE_INPUT}" "${EVIDENCE_SCENARIO}"
              "${OUT_ROOT}/evidence/committed" _committed_schema)
  _run_schema("${MUTATED}" "${EVIDENCE_INPUT}" "${EVIDENCE_SCENARIO}"
              "${OUT_ROOT}/evidence/mutated" _mutated_schema)

  string(FIND "${_committed_schema}" "${_table_marker}" _committed_at)
  string(FIND "${_mutated_schema}" "${_table_marker}" _mutated_at)
  if(NOT _committed_at EQUAL -1 OR NOT _mutated_at EQUAL -1)
    message(FATAL_ERROR
      "posting-idempotency-table mutation: evidence-only selection emitted "
      "the effectful replay table")
  endif()
  if(NOT "${_committed_schema}" STREQUAL "${_mutated_schema}")
    message(FATAL_ERROR
      "posting-idempotency-table mutation: an unselected node changed "
      "evidence-only SQL")
  endif()
endfunction()

_prove_effectful_path()
_prove_evidence_path()

message(STATUS
  "PostingIdempotencyTable mutation reaches only the effectful production "
  "path; all other SQL bytes and declaration ordering remain exact")
