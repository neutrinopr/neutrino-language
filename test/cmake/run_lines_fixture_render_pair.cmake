# [] Prove the Lines fixture .td drives production output: the COMMITTED
# generated handler renders the three flat lines (exit 0); the .td-MUTATED handler
# (a fixed line removed) does NOT (exit != 0) and its render drops that line.
#
# Invoked as a CTest:
#   cmake -DCOMMITTED=<exe> -DMUTATED=<exe> -P this

execute_process(COMMAND "${COMMITTED}"
  RESULT_VARIABLE _crc OUTPUT_VARIABLE _cout ERROR_VARIABLE _cerr)
if(NOT _crc EQUAL 0)
  message(FATAL_ERROR
    "lines-fixture render pair: the COMMITTED handler did NOT render the flat "
    "3-line form (rc=${_crc}):\n${_cout}${_cerr}")
endif()

execute_process(COMMAND "${MUTATED}"
  RESULT_VARIABLE _mrc OUTPUT_VARIABLE _mout ERROR_VARIABLE _merr)
if(_mrc EQUAL 0)
  message(FATAL_ERROR
    "lines-fixture render pair: the .td-MUTATED handler still reproduced the "
    "committed 3-line form — the syntax-record mutation did not change "
    "output:\n${_mout}${_merr}")
endif()
# Non-vacuity: the mutated render dropped the third line (not an unrelated crash).
string(FIND "${_mout}" "third line" _idx)
if(NOT _idx EQUAL -1)
  message(FATAL_ERROR
    "lines-fixture render pair: the mutated handler still emitted `third line` "
    "(vacuous failure):\n${_mout}${_merr}")
endif()

message(STATUS
  "lines-fixture render pair holds: committed renders 3 flat lines; the "
  ".td-mutated handler drops a line and fails.")
