# [] Prove the framed-lines fixture .td drives production output, surface by
# surface: the COMMITTED generated handler renders the expected
# header+items+footer form (exit 0); a handler built from the .td with ONE
# surface mutated (MODE = header | item | footer | placeholder) does NOT
# (exit != 0) and its render carries the mutation-specific EXPECT_TOKEN — so
# each part of the closed frame independently controls the emitted bytes, and
# the failure is the mutation taking effect, not an unrelated crash.
#
# Invoked as a CTest:
#   cmake -DCOMMITTED=<exe> -DMUTATED=<exe> -DMODE=<mode> -DEXPECT_TOKEN=<tok> -P this

execute_process(COMMAND "${COMMITTED}"
  RESULT_VARIABLE _crc OUTPUT_VARIABLE _cout ERROR_VARIABLE _cerr)
if(NOT _crc EQUAL 0)
  message(FATAL_ERROR
    "framed-lines render pair [${MODE}]: the COMMITTED handler did NOT render the "
    "expected header+items+footer form (rc=${_crc}):\n${_cout}${_cerr}")
endif()

execute_process(COMMAND "${MUTATED}"
  RESULT_VARIABLE _mrc OUTPUT_VARIABLE _mout ERROR_VARIABLE _merr)
if(_mrc EQUAL 0)
  message(FATAL_ERROR
    "framed-lines render pair [${MODE}]: the .td-MUTATED handler still reproduced "
    "the committed form — the ${MODE} mutation did not change output:\n${_mout}${_merr}")
endif()
# Non-vacuity: the mutated render carries the mutation-specific token (the change
# took effect), not an unrelated crash before reaching the mutated surface.
string(FIND "${_mout}" "${EXPECT_TOKEN}" _idx)
if(_idx EQUAL -1)
  message(FATAL_ERROR
    "framed-lines render pair [${MODE}]: the mutated handler did not emit the "
    "expected mutated token `${EXPECT_TOKEN}` (vacuous failure):\n${_mout}${_merr}")
endif()

message(STATUS
  "framed-lines render pair [${MODE}] holds: committed renders the frame; the "
  "${MODE}-mutated handler changes output (`${EXPECT_TOKEN}`) and fails the golden.")
