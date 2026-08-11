# [ C1] Build-time copy of the REAL production emitter TU
# (PostgresModel.cpp) whose SOLE difference is the printer-handlers include,
# repointed at the .td-mutated generated file. This keeps the mutation-only
# recompile OUTSIDE production source — the committed PostgresModel.cpp retains
# its literal include and admits no compile-time override boundary (no
# MacroEmitterBoundary regression). Fails CLOSED if the exact committed include
# line is absent, so the copy can never silently drift from production into a
# maintained fork.
#
#   cmake -DSRC=<PostgresModel.cpp> -DMUT_INC=<mutated .inc abspath> -DOUT=<copy> -P this

file(READ "${SRC}" _txt)
set(_needle "#include \"PostgresPrinterHandlers.inc\"")
string(FIND "${_txt}" "${_needle}" _at)
if(_at EQUAL -1)
  message(FATAL_ERROR
    "gen-mutated-pg-model-tu: the committed printer-handlers include line was not "
    "found in ${SRC}; the production emitter TU drifted — update this anchor so the "
    "mutated copy stays an exact one-line delta from production.")
endif()
# Exactly one occurrence expected (a second would make the copy ambiguous).
string(REPLACE "${_needle}" "@@NEU_MUT@@" _probe "${_txt}")
string(FIND "${_probe}" "@@NEU_MUT@@" _first)
string(FIND "${_probe}" "@@NEU_MUT@@" _dummy)
string(REGEX MATCHALL "@@NEU_MUT@@" _hits "${_probe}")
list(LENGTH _hits _n)
if(NOT _n EQUAL 1)
  message(FATAL_ERROR "gen-mutated-pg-model-tu: expected exactly one committed include line, found ${_n}")
endif()
string(REPLACE "${_needle}" "#include \"${MUT_INC}\"" _out "${_txt}")
file(WRITE "${OUT}" "${_out}")
