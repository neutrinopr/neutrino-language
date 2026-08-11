# [] Real-generator .td mutation on the PRODUCTION surface for the FLAT
# guard node (`FlatIf`, flat-block layout). Runs the actual planFromSpec ->
# printPostgres path on a FlatIf-bearing spec.
#
# `FlatIf` and `If` render the SAME `IF … THEN`/`END IF;` text — they differ only
# in child indentation (flat vs nested) — so a plain substring witness cannot
# isolate FlatIf: the If-rendered guards legitimately keep `END IF;` in the
# mutated render. Instead the flat-if .td mutation is NODE-SCOPED (only the
# FlatIf record's close becomes `END IFX;`), and this harness proves the change
# is EXACTLY the FlatIf frames:
#   * the COMMITTED driver emits `END IF;` and NO `END IFX;` (the flat guard
#     renders; the mutated token is absent);
#   * the driver built against the .td-MUTATED include emits `END IFX;` (the
#     FlatIf .td node drives production bytes through the real sealed authorGuard
#     carrier);
#   * normalizing the mutated render's `END IFX;` back to `END IF;` reproduces
#     the committed render EXACTLY — so the mutation moved ONLY the FlatIf
#     close-frame bytes and nothing else (the flat legs, their indentation, and
#     every If-rendered guard are untouched).
#
# Invoked as a CTest:
#   cmake -DCOMMITTED=<exe> -DMUTATED=<exe> -DSPEC=<spec.json> -P this

execute_process(COMMAND "${COMMITTED}" "${SPEC}"
  RESULT_VARIABLE _crc OUTPUT_VARIABLE _cout ERROR_VARIABLE _cerr)
if(NOT _crc EQUAL 0)
  message(FATAL_ERROR "flat-if real-path mutation: COMMITTED driver failed (rc=${_crc}):\n${_cerr}")
endif()
string(FIND "${_cout}" "END IF;" _c_has_committed)
string(FIND "${_cout}" "END IFX;" _c_has_mutated)
if(_c_has_committed EQUAL -1 OR NOT _c_has_mutated EQUAL -1)
  message(FATAL_ERROR
    "flat-if real-path mutation: the COMMITTED render must contain the flat "
    "guard close [END IF;] and none of [END IFX;] — the real legalize/FlatIf "
    "routing is broken or the spec bears no flat  guard:\n${_cout}")
endif()

execute_process(COMMAND "${MUTATED}" "${SPEC}"
  RESULT_VARIABLE _mrc OUTPUT_VARIABLE _mout ERROR_VARIABLE _merr)
if(NOT _mrc EQUAL 0)
  message(FATAL_ERROR "flat-if real-path mutation: MUTATED driver failed (rc=${_mrc}):\n${_merr}")
endif()
string(FIND "${_mout}" "END IFX;" _m_has_mutated)
if(_m_has_mutated EQUAL -1)
  message(FATAL_ERROR
    "flat-if real-path mutation: the .td-mutated render did NOT emit [END IFX;] "
    "— the FlatIf .td node does not drive production bytes:\n${_mout}")
endif()

# The ONLY difference must be the FlatIf close frames: undo the mutation and the
# renders must be byte-identical (the flat legs, their flat indentation, and the
# If-rendered guards are all unchanged).
string(REPLACE "END IFX;" "END IF;" _mnorm "${_mout}")
if(NOT _mnorm STREQUAL _cout)
  message(FATAL_ERROR
    "flat-if real-path mutation: normalizing [END IFX;]->[END IF;] did NOT "
    "reproduce the committed render — the mutation changed more than the FlatIf "
    "close frames:\n--- committed ---\n${_cout}\n--- mutated (normalized) ---\n${_mnorm}")
endif()

message(STATUS
  "flat-if real-path mutation holds: the FlatIf flat-block .td node drives the "
  "production guard-close bytes through the real sealed authorGuard carrier, and "
  "the mutation moves EXACTLY the FlatIf frames (flat legs + If guards unchanged).")
