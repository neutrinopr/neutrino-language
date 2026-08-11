# S5f (): [17] mutation testing — the frontend/verifier catch broken coordination. Bash-free:
# mutation_test.py exits 0 iff every critical mutant is caught; we then pin that the expected-survivor
# negative control (alter_compute_expr) is present in the report, so the suite can't silently drop it.
# -D: PY (python3) MUT (mutation_test.py) SRC TRANSLATE OPT OUT.

if(NOT DEFINED PY OR NOT DEFINED MUT OR NOT DEFINED SRC
   OR NOT DEFINED TRANSLATE OR NOT DEFINED OPT OR NOT DEFINED OUT)
  message(FATAL_ERROR "s5f_mutation: PY MUT SRC TRANSLATE OPT OUT are required")
endif()

execute_process(
  COMMAND ${PY} ${MUT} --source ${SRC} --translate ${TRANSLATE} --opt ${OPT} --out ${OUT}
  RESULT_VARIABLE _rc OUTPUT_QUIET ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
  message(FATAL_ERROR "s5f mutation: a critical mutant survived (rc=${_rc})\n${_err}")
endif()

# negative control: the report must still carry the expected-survivor mutation.
file(READ ${OUT}/mutation-report.json _report)
string(FIND "${_report}" "\"mutation\": \"alter_compute_expr\"" _pos)
if(_pos EQUAL -1)
  message(FATAL_ERROR "s5f mutation: expected-survivor negative control (alter_compute_expr) missing from the report")
endif()
