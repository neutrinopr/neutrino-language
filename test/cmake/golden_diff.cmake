# S5e (): bash-free drift + field gate for a generated golden artifact.
#
# Run as: cmake -DGEN=<build outdir> -DGOLD=<committed golden dir> -DFILES=a.json|b.json
#              [-DFIELDSCRIPT=<path to a fields_*.cmake>] -P golden_diff.cmake
#
# The artifact was regenerated into GEN by the generate-golden-artifacts DAG target (the CTest
# fixture builds it before this runs). This byte-compares each committed golden file against the
# generated one with `cmake -E compare_files`, then optionally includes a per-target field script
# that pins specific semantic fields in the committed golden (via ${GOLD}). Lists are `|`-separated
# (a single add_test arg can't carry CMake's `;`). Fail-closed: any mismatch is a FATAL_ERROR.

if(NOT DEFINED GEN OR NOT DEFINED GOLD OR NOT DEFINED FILES)
  message(FATAL_ERROR "golden_diff: GEN, GOLD and FILES are required")
endif()

string(REPLACE "|" ";" _files "${FILES}")
foreach(_f ${_files})
  if(NOT EXISTS "${GEN}/${_f}")
    message(FATAL_ERROR "golden_diff: generated file missing (did generation run?): ${GEN}/${_f}")
  endif()
  execute_process(
    COMMAND ${CMAKE_COMMAND} -E compare_files "${GEN}/${_f}" "${GOLD}/${_f}"
    RESULT_VARIABLE _rc)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "golden drift: ${_f} differs from the committed golden "
                        "(generated ${GEN}/${_f} vs ${GOLD}/${_f})")
  endif()
endforeach()

# Optional per-target field pins: a fields_*.cmake that asserts specific semantic substrings exist
# in a committed golden (${GOLD}). These survive a golden regeneration that would otherwise silently
# change a field the byte-diff alone accepts. The substrings live in the script (no add_test quoting).
if(DEFINED FIELDSCRIPT)
  include("${FIELDSCRIPT}")
endif()
