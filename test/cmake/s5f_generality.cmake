# S5f (): [8] generality — a second, differently-shaped domain (core_scheme_settlement)
# translates, verifies, and generates both executable backends. Bash-free: each tool step is an
# execute_process whose exit code is the assertion (pass == 0). -D: TRANSLATE OPT GEN SRC2 SCENARIO2 OUT.

if(NOT DEFINED TRANSLATE OR NOT DEFINED OPT OR NOT DEFINED GEN
   OR NOT DEFINED SRC2 OR NOT DEFINED SCENARIO2 OR NOT DEFINED OUT)
  message(FATAL_ERROR "s5f_generality: TRANSLATE OPT GEN SRC2 SCENARIO2 OUT are required")
endif()

file(REMOVE_RECURSE ${OUT})
file(MAKE_DIRECTORY ${OUT})

function(_run label)
  execute_process(COMMAND ${ARGN} RESULT_VARIABLE _rc OUTPUT_QUIET ERROR_VARIABLE _err)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "s5f generality: ${label} failed (rc=${_rc})\n${_err}")
  endif()
endfunction()

_run("translate"       ${TRANSLATE} ${SRC2} -o ${OUT}/d2.mlir)
_run("opt verify"      ${OPT} ${OUT}/d2.mlir)
_run("generate solidity" ${GEN} --target=solidity --scenario=${SCENARIO2} ${SRC2} -o ${OUT}/d2)
_run("generate postgres" ${GEN} --target=postgres --scenario=${SCENARIO2} ${SRC2} -o ${OUT}/d2)
