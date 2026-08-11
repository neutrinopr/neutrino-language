if(NOT DEFINED NODE_LABEL)
  set(NODE_LABEL "DeclareSection")
endif()

execute_process(COMMAND "${COMMITTED}" "${SPEC}"
  RESULT_VARIABLE _crc OUTPUT_VARIABLE _cout ERROR_VARIABLE _cerr)
if(NOT _crc EQUAL 0)
  message(FATAL_ERROR
    "${NODE_LABEL} exclusion: committed driver failed (rc=${_crc}):\n${_cerr}")
endif()
execute_process(COMMAND "${MUTATED}" "${SPEC}"
  RESULT_VARIABLE _mrc OUTPUT_VARIABLE _mout ERROR_VARIABLE _merr)
if(NOT _mrc EQUAL 0)
  message(FATAL_ERROR
    "${NODE_LABEL} exclusion: mutated driver failed (rc=${_mrc}):\n${_merr}")
endif()
if(NOT _cout STREQUAL _mout)
  message(FATAL_ERROR
    "${NODE_LABEL} exclusion: a path with no DECLARE section changed under the "
    ".td mutation:\n--- committed ---\n${_cout}\n--- mutated ---\n${_mout}")
endif()
string(FIND "${_cout}" "DECLARE" _has_declare)
if(NOT _has_declare EQUAL -1)
  message(FATAL_ERROR
    "${NODE_LABEL} exclusion fixture unexpectedly emitted a DECLARE section")
endif()
message(STATUS
  "${NODE_LABEL} exclusion holds: the evidence-only production path is "
  "byte-identical under the DECLARE mutation")
