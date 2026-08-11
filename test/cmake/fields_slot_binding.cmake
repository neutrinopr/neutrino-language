# S5e (): field pins for the core_flexible_binding slot golden (was [32]'s Python check). The
# late-binding policy must be carried in the wire contract (capability.json, covered by capabilityHash).
file(READ "${GOLD}/capability.json" _c)
foreach(_s "\"mode\": \"to_be_bound\"" "\"authorizedBinder\": \"sponsorco\"" "\"minAssurance\": \"A2\"")
  string(FIND "${_c}" "${_s}" _p)
  if(_p EQUAL -1)
    message(FATAL_ERROR "core_flexible_binding slot golden missing binding field: [${_s}]")
  endif()
endforeach()
