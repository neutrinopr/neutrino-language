# [] Assert that a source file FAILS to compile for a SPECIFIC reason (a
# compile-negative boundary). Invoked as a CTest:
#   cmake -DCXX=... -DSTD=... -DSYSROOT=... -DSRC=... -DINCS=a|b|c \
#         -DDEFINE=PROBE_X -DEXPECT=<diagnostic substring> -P this
# PASSES iff the compile fails AND its diagnostics contain EXPECT. FATAL_ERROR
# (test failure) if it compiles (the sealed path re-opened) or fails for a
# different reason (a broken toolchain/include, or a diagnostic drift) — so this
# proves the TYPE SYSTEM, not a scanner, holds the boundary.

string(REPLACE "|" ";" _inc_list "${INCS}")
set(_iflags "")
foreach(_d ${_inc_list})
  if(_d)
    list(APPEND _iflags "-I${_d}")
  endif()
endforeach()
set(_sysflags "")
if(SYSROOT)
  set(_sysflags "-isysroot" "${SYSROOT}")
endif()
set(_defflag "")
if(DEFINE)
  set(_defflag "-D${DEFINE}")
endif()

execute_process(
  COMMAND ${CXX} -std=${STD} ${_sysflags} ${_iflags} ${_defflag} -fsyntax-only ${SRC}
  RESULT_VARIABLE _rc
  OUTPUT_VARIABLE _out
  ERROR_VARIABLE _err)

if(_rc EQUAL 0)
  message(FATAL_ERROR
    "compile-negative boundary BREACHED [${DEFINE}]: ${SRC} compiled successfully, "
    "but it must not — a sealed authoring path re-opened.\n${_out}${_err}")
endif()
# Non-vacuity: the failure must be the SEAL, not a broken toolchain/include.
if(_err MATCHES "file not found" OR _err MATCHES "No such file")
  message(FATAL_ERROR
    "compile-negative test is VACUOUS [${DEFINE}]: ${SRC} failed on a missing "
    "include, not the seal. Fix the include flags.\n${_err}")
endif()
# ...and it must fail for THIS probe's expected reason.
if(NOT _err MATCHES "${EXPECT}")
  message(FATAL_ERROR
    "compile-negative probe [${DEFINE}] did not fail for its expected reason "
    "(${EXPECT}). Output:\n${_err}")
endif()
message(STATUS "compile-negative boundary holds [${DEFINE}]: ${SRC} rejected on '${EXPECT}'")
