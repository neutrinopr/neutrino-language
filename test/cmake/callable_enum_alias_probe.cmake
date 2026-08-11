# [ review] Compile-NEGATIVE: an ALIAS member injected into the GENERATED
# callable-enum X-macro is caught at compile time by the position-drift coverage
# assertion. Copies the generated enum source + its consumers to a temp dir,
# injects `NEU_SOL_ENUM_<Enum>(Aliased, <ordinal>, "aliased")` (an ordinal that
# aliases an existing member — the exact bypass a terminal `Count` sentinel
# cannot see), and compiles the probe TU. PASSES iff the compile FAILS with the
# position-drift diagnostic; FATAL if it compiles (the alias slipped through) or
# fails for a different reason (toolchain/include drift).
#
# Invoked as a CTest:
#   cmake -DCXX=.. -DSTD=.. -DSYSROOT=.. -DSOLDIR=.. -DINCS=a|b|c \
#         -DPROBE=..cpp -DENUM=CallableKind|CallableModifier -DWORK=.. -P this

#  R1: the header lives under provider/, the generated .inc under generated/;
# copy each from its subdir into WORK by BASENAME so the probe's flat bare
# `#include "..."` (via -I${WORK}) still resolves after the structural move.
set(_headers
  provider/SolidityTargetAdapter.h
  generated/SolidityTargetEnums.inc
  generated/SolidityCallableCoverage.inc
  generated/SolidityPrinterHandlers.inc
  generated/SolidityTargetNodes.inc)

file(REMOVE_RECURSE "${WORK}")
file(MAKE_DIRECTORY "${WORK}")
foreach(_h ${_headers})
  get_filename_component(_hbase "${_h}" NAME)
  configure_file("${SOLDIR}/${_h}" "${WORK}/${_hbase}" COPYONLY)
endforeach()

# Inject an alias member (ordinal 1 aliases the second member) just before the
# selected enum's X-macro `#endif`.
set(_anchor "#endif // NEU_SOL_ENUM_${ENUM}")
set(_alias "NEU_SOL_ENUM_${ENUM}(Aliased, 1, \"aliased\")\n${_anchor}")
file(READ "${WORK}/SolidityTargetEnums.inc" _e)
string(REPLACE "${_anchor}" "${_alias}" _mut "${_e}")
if(_mut STREQUAL _e)
  message(FATAL_ERROR
    "callable-enum alias probe VACUOUS: anchor ${_anchor!r} not found in the "
    "generated enum source (naming drift).")
endif()
file(WRITE "${WORK}/SolidityTargetEnums.inc" "${_mut}")

string(REPLACE "|" ";" _inc_list "${INCS}")
set(_iflags "-I${WORK}")
foreach(_d ${_inc_list})
  if(_d)
    list(APPEND _iflags "-I${_d}")
  endif()
endforeach()
set(_sysflags "")
if(SYSROOT)
  set(_sysflags "-isysroot" "${SYSROOT}")
endif()

execute_process(
  COMMAND ${CXX} -std=${STD} ${_sysflags} ${_iflags} -fsyntax-only ${PROBE}
  RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)

if(_rc EQUAL 0)
  message(FATAL_ERROR
    "callable-enum alias probe BREACHED [${ENUM}]: the probe compiled with an "
    "aliased enum member — coverage did not catch it.\n${_out}${_err}")
endif()
if(_err MATCHES "file not found" OR _err MATCHES "No such file")
  message(FATAL_ERROR
    "callable-enum alias probe VACUOUS [${ENUM}]: failed on a missing include, "
    "not the coverage assert. Fix the include flags.\n${_err}")
endif()
if(NOT _err MATCHES "drifted from its declaration position")
  message(FATAL_ERROR
    "callable-enum alias probe [${ENUM}] did not fail for its expected reason "
    "(position drift). Output:\n${_err}")
endif()
message(STATUS
  "callable-enum alias probe holds [${ENUM}]: an aliased generated enum member "
  "is rejected on the position-drift coverage assertion.")
