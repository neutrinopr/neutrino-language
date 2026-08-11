# Production mutation proof for the two PostingsTable variants (). The base
# record must drive the memo-LESS effectful schema; the memo record must drive
# the memo effectful schema and never leak onto the memo-less path; neither may
# appear on the evidence-only path. Every byte beyond the selected mutation stays
# exact, so the .td shapes — not a C++ template — own the production bytes.

foreach(_required COMMITTED BASE_MUTATED MEMO_MUTATED OUT_ROOT
                  MEMOLESS_INPUT MEMOLESS_SCENARIO MEMO_INPUT MEMO_SCENARIO
                  EVIDENCE_INPUT EVIDENCE_SCENARIO)
  if(NOT DEFINED ${_required})
    message(FATAL_ERROR "postings-table real-path mutation: missing ${_required}")
  endif()
endforeach()

set(_base_committed "signed_amount  bigint NOT NULL")
set(_base_mutated "signed_amount  numeric NOT NULL")
set(_memo_committed "    memo           text\n")
set(_memo_mutated "    memo           jsonb\n")
set(_postings_marker "CREATE TABLE IF NOT EXISTS postings (")

function(_run_schema _binary _input _scenario _out_dir _result_var)
  file(REMOVE_RECURSE "${_out_dir}")
  execute_process(
    COMMAND "${_binary}" --target=postgres "--scenario=${_scenario}"
            "${_input}" -o "${_out_dir}"
    RESULT_VARIABLE _rc OUTPUT_VARIABLE _stdout ERROR_VARIABLE _stderr)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "postings-table mutation: neutrino-gen failed (${_rc}):\n${_stdout}\n${_stderr}")
  endif()
  file(READ "${_out_dir}/schema.sql" _schema)
  set(${_result_var} "${_schema}" PARENT_SCOPE)
endfunction()

# 1) base bites memo-less: the base record drives the memo-less effectful schema.
_run_schema("${COMMITTED}" "${MEMOLESS_INPUT}" "${MEMOLESS_SCENARIO}"
            "${OUT_ROOT}/memoless/committed" _ml_committed)
_run_schema("${BASE_MUTATED}" "${MEMOLESS_INPUT}" "${MEMOLESS_SCENARIO}"
            "${OUT_ROOT}/memoless/base" _ml_base)
string(FIND "${_ml_committed}" "${_postings_marker}" _ml_has_postings)
string(FIND "${_ml_committed}" "${_memo_committed}" _ml_has_memo)
if(_ml_has_postings EQUAL -1 OR NOT _ml_has_memo EQUAL -1)
  message(FATAL_ERROR "postings-table mutation: memo-less path must emit postings WITHOUT a memo column")
endif()
string(FIND "${_ml_base}" "${_base_mutated}" _ml_base_new)
string(FIND "${_ml_base}" "${_base_committed}" _ml_base_stale)
if(_ml_base_new EQUAL -1 OR NOT _ml_base_stale EQUAL -1)
  message(FATAL_ERROR "postings-table mutation: the base .td shape did not drive the memo-less schema")
endif()
string(REPLACE "${_base_mutated}" "${_base_committed}" _ml_base_norm "${_ml_base}")
if(NOT "${_ml_base_norm}" STREQUAL "${_ml_committed}")
  message(FATAL_ERROR "postings-table mutation: memo-less bytes beyond the base mutation changed")
endif()

# 2) memo bites memo: the memo record drives the memo effectful schema.
_run_schema("${COMMITTED}" "${MEMO_INPUT}" "${MEMO_SCENARIO}"
            "${OUT_ROOT}/memo/committed" _m_committed)
_run_schema("${MEMO_MUTATED}" "${MEMO_INPUT}" "${MEMO_SCENARIO}"
            "${OUT_ROOT}/memo/memo" _m_memo)
string(FIND "${_m_committed}" "${_memo_committed}" _m_has_memo)
if(_m_has_memo EQUAL -1)
  message(FATAL_ERROR "postings-table mutation: memo path must emit the memo column")
endif()
string(FIND "${_m_memo}" "${_memo_mutated}" _m_memo_new)
string(FIND "${_m_memo}" "${_memo_committed}" _m_memo_stale)
if(_m_memo_new EQUAL -1 OR NOT _m_memo_stale EQUAL -1)
  message(FATAL_ERROR "postings-table mutation: the memo .td shape did not drive the memo schema")
endif()
string(REPLACE "${_memo_mutated}" "${_memo_committed}" _m_memo_norm "${_m_memo}")
if(NOT "${_m_memo_norm}" STREQUAL "${_m_committed}")
  message(FATAL_ERROR "postings-table mutation: memo bytes beyond the memo mutation changed")
endif()

# 3) the memo mutation cannot leak onto the memo-less path (the variants are
#    distinct records, not one discriminated shape).
_run_schema("${MEMO_MUTATED}" "${MEMOLESS_INPUT}" "${MEMOLESS_SCENARIO}"
            "${OUT_ROOT}/memoless/memo" _ml_memo)
if(NOT "${_ml_memo}" STREQUAL "${_ml_committed}")
  message(FATAL_ERROR "postings-table mutation: the memo record leaked onto the memo-less path")
endif()

# 4) evidence-only excludes postings entirely under every mutation.
foreach(_bin "${COMMITTED}" "${BASE_MUTATED}" "${MEMO_MUTATED}")
  _run_schema("${_bin}" "${EVIDENCE_INPUT}" "${EVIDENCE_SCENARIO}"
              "${OUT_ROOT}/evidence" _ev)
  string(FIND "${_ev}" "${_postings_marker}" _ev_has_postings)
  if(NOT _ev_has_postings EQUAL -1)
    message(FATAL_ERROR "postings-table mutation: evidence-only schema emitted a postings table")
  endif()
endforeach()

message(STATUS
  "PostingsTable variants proven: base drives the memo-less schema, memo drives "
  "the memo schema (no leak), evidence excludes postings, all other bytes exact")
