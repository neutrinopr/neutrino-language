# [] Generate a printer-handlers include from the TEST-ONLY Lines fixture .td,
# optionally with a fixed line REMOVED (MUTATE=1), so the render harness can prove
# the committed handler renders three flat lines and the .td-mutated handler
# renders differently (a Syntax mutation changes production output).
#
# Invoked from an add_custom_command:
#   cmake -DGEN=... -DTD=... -DSCHEMA=... -DTBLGEN=... -DWORK=... -DOUT=... \
#         [-DMUTATE=1] -P this
#
# The generator resolves tblgen's include dir as the .td's GRANDPARENT and the
# record `include "TargetPrinter.td"`, so mirror that layout under WORK:
#   ${WORK}/backends/TargetPrinter.td          (schema copy)
#   ${WORK}/backends/linesfixture/fixture.td    (the fixture record)
# -> grandparent of fixture.td is ${WORK}/backends, which carries the schema.

file(READ "${TD}" _td)
if(MUTATE)
  # Remove the FIXED third line from the multi-line template (a line REMOVAL —
  # the render provably loses a line). `\\n` is the literal backslash-n the .td
  # source carries; `\${middle}` is the literal placeholder.
  set(_committed "first line\\nmiddle \${middle} line\\nthird line")
  set(_mutated "first line\\nmiddle \${middle} line")
  string(REPLACE "${_committed}" "${_mutated}" _td_out "${_td}")
  if(_td_out STREQUAL _td)
    message(FATAL_ERROR
      "gen-lines-fixture VACUOUS: committed template not found to mutate in ${TD}")
  endif()
else()
  set(_td_out "${_td}")
endif()

file(MAKE_DIRECTORY "${WORK}/backends/linesfixture")
configure_file("${SCHEMA}" "${WORK}/backends/TargetPrinter.td" COPYONLY)
file(WRITE "${WORK}/backends/linesfixture/fixture.td" "${_td_out}")

execute_process(
  COMMAND python3 "${GEN}"
    --td "${WORK}/backends/linesfixture/fixture.td"
    --out "${WORK}/fixture_registry.inc"
    --printer-out "${OUT}"
    --tblgen "${TBLGEN}"
  RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
  message(FATAL_ERROR "gen-lines-fixture: generator failed:\n${_out}${_err}")
endif()
