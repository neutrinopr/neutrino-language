# S5e (): field pins for the security golden (was [22]'s greps). Asserts the five Capability
# Security Pass categories are present and the sample domain reports ok, across regenerations.
file(READ "${GOLD}/security.json" _c)
foreach(_s "\"category\": \"authorization\"" "\"category\": \"value\"" "\"category\": \"topology\""
           "\"category\": \"trustBoundary\"" "\"category\": \"state\"" "\"ok\": true")
  string(FIND "${_c}" "${_s}" _p)
  if(_p EQUAL -1)
    message(FATAL_ERROR "security golden missing field: [${_s}]")
  endif()
endforeach()
