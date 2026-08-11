# S5e (): field pins for the coverage golden (was [16]'s grep). Asserts the highest language
# level and the derived maturity ceiling are present, so a regeneration can't silently change them.
file(READ "${GOLD}/coverage.json" _c)
foreach(_s "\"highestLevel\": \"L5\"" "\"level\": 1, \"name\": \"Core Compliant\"")
  string(FIND "${_c}" "${_s}" _p)
  if(_p EQUAL -1)
    message(FATAL_ERROR "coverage golden missing field: [${_s}]")
  endif()
endforeach()
