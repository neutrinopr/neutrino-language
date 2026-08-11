# [] Generate a printer-handlers include from the TEST-ONLY framed-lines
# fixture .td, optionally with ONE surface INDEPENDENTLY mutated (MUTATE_MODE),
# so the render pair proves each part of the closed frame is load-bearing: an
# independent header, item-operator, footer, or item-placeholder-wiring mutation
# each changes the generated output.
#
# Invoked from an add_custom_command:
#   cmake -DGEN=... -DTD=... -DSCHEMA=... -DTBLGEN=... -DWORK=... -DOUT=... \
#         [-DMUTATE_MODE=header|item|footer|placeholder] -P this
#
# The generator resolves tblgen's include dir as the .td's GRANDPARENT and the
# record `include "TargetPrinter.td"`, so mirror that layout under WORK:
#   ${WORK}/backends/TargetPrinter.td              (schema copy)
#   ${WORK}/backends/framedfixture/fixture.td       (the fixture record)

file(READ "${TD}" _td)
if(MUTATE_MODE STREQUAL "header")
  set(_from "CASE p_policy") # the fixed header token
  set(_to "CASE p_policyX")
elseif(MUTATE_MODE STREQUAL "item")
  set(_from "THEN v_set := \${set}") # the item assignment operator
  set(_to "THEN v_set ::= \${set}")
elseif(MUTATE_MODE STREQUAL "footer")
  set(_from "END CASE;") # the fixed footer token
  set(_to "END CASEX;")
elseif(MUTATE_MODE STREQUAL "placeholder")
  # SWAP the two item placeholders: every field stays referenced + dense (so the
  # generator's placeholder-match check is satisfied), but each tuple projects to
  # different bytes — proving the ${name}->field-index wiring is load-bearing.
  set(_from "v_set := \${set}; v_m := \${quorum}")
  set(_to "v_set := \${quorum}; v_m := \${set}")
elseif(MUTATE_MODE)
  message(FATAL_ERROR "gen-framed-lines-fixture: unknown MUTATE_MODE '${MUTATE_MODE}'")
endif()

if(MUTATE_MODE)
  string(REPLACE "${_from}" "${_to}" _td_out "${_td}")
  if(_td_out STREQUAL _td)
    message(FATAL_ERROR
      "gen-framed-lines-fixture VACUOUS (${MUTATE_MODE}): token '${_from}' not found to mutate in ${TD}")
  endif()
else()
  set(_td_out "${_td}")
endif()

file(MAKE_DIRECTORY "${WORK}/backends/framedfixture")
configure_file("${SCHEMA}" "${WORK}/backends/TargetPrinter.td" COPYONLY)
file(WRITE "${WORK}/backends/framedfixture/fixture.td" "${_td_out}")

execute_process(
  COMMAND python3 "${GEN}"
    --td "${WORK}/backends/framedfixture/fixture.td"
    --out "${WORK}/fixture_registry.inc"
    --printer-out "${OUT}"
    --tblgen "${TBLGEN}"
  RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
  message(FATAL_ERROR "gen-framed-lines-fixture: generator failed:\n${_out}${_err}")
endif()
