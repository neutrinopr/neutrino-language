# [] Regenerate a printer-handlers include from a MUTATED copy of a typed
# statement-shell syntax record (`= ${rhs}` -> `:= ${rhs}`), so the render harness
# can be compiled against it and prove the mutation changes production output.
# NODE selects which record to mutate (LocalDecl slice 2a, Assign slice 2b).
#
# Invoked from an add_custom_command:
#   cmake -DNODE=LocalDecl|Assign -DGEN=... -DTD=... -DSCHEMA=... -DTBLGEN=... \
#         -DWORK=... -DOUT=... -P this
#
# The generator resolves tblgen's include dir as the .td's GRANDPARENT and the
# record `include "TargetPrinter.td"`, so mirror that layout under WORK:
#   ${WORK}/backends/TargetPrinter.td          (schema copy)
#   ${WORK}/backends/solidity/mutated.td       (mutated record)
# -> grandparent of mutated.td is ${WORK}/backends, which carries the schema.
# The templates are defined here (not passed via -D) because a `${...};` value
# would be mangled by CMake list-splitting / variable expansion on the command line.

if(NODE STREQUAL "InterfaceShell")
  #  slice 3: mutate the `interface` container keyword; the render provably
  # changes and no longer matches the production golden.
  set(_committed_tpl "interface \${name} {")
  set(_mutated_tpl "interfacex \${name} {")
elseif(NODE STREQUAL "InterfaceSignature")
  #  slice 3: mutate the `returns` clause framing of the interface signature.
  set(_committed_tpl "returns (\${returns});")
  set(_mutated_tpl "returnsx (\${returns});")
elseif(NODE STREQUAL "ContractShell")
  #  slice 2: mutate the `contract` container keyword; the render provably
  # changes (`contract <name> {` -> `contractx <name> {`) and no longer matches
  # the production golden — proving the container framing is `.td`-owned.
  set(_committed_tpl "contract \${name} {")
  set(_mutated_tpl "contractx \${name} {")
elseif(NODE STREQUAL "FunctionSig")
  # : mutate the CLOSED callable-kind SPELLING `"function"` -> `"functionx"`
  # in the EnumSpelling record. The quoted token appears in the .td spelling list
  # AND verbatim in the generated spelling table, so the render provably changes
  # (`function attest(...)` -> `functionx attest(...)`) and no longer matches the
  # production golden — proving the enum spelling is `.td`-owned, not baked.
  set(_committed_tpl "\"function\"")
  set(_mutated_tpl "\"functionx\"")
elseif(NODE STREQUAL "EventDecl")
  # Mutate the `event` keyword itself (no `=` to flip); the render provably changes.
  set(_committed_tpl "event \${name}(\${params});")
  set(_mutated_tpl "eventx \${name}(\${params});")
elseif(NODE STREQUAL "StorageDecl")
  # No literal `=` to flip; append a marker so the render provably changes.
  set(_committed_tpl "\${type} \${modifiers} \${name};")
  set(_mutated_tpl "\${type} \${modifiers} \${name} /*mut*/;")
elseif(NODE STREQUAL "EnumDecl")
  # Mutate the `enum` keyword itself (no `=` to flip); the render provably changes.
  set(_committed_tpl "enum \${name} { \${variants} }")
  set(_mutated_tpl "enumx \${name} { \${variants} }")
elseif(NODE STREQUAL "Import")
  # Mutate the `import` keyword itself (no `=` to flip); the render provably
  # changes. The .td template escapes its quotes (`import \"${path}\";`), so match
  # the literal backslash-quote bytes (CMake `\\\"` -> `\"`).
  set(_committed_tpl "import \\\"\${path}\\\";")
  set(_mutated_tpl "importx \\\"\${path}\\\";")
elseif(NODE STREQUAL "Pragma")
  # Mutate the `pragma` keyword itself (no `=` to flip); the render provably changes.
  set(_committed_tpl "pragma solidity \${version};")
  set(_mutated_tpl "pragmax solidity \${version};")
elseif(NODE STREQUAL "SpdxLicense")
  # Mutate the `//` marker of the SPDX directive; the render provably changes.
  set(_committed_tpl "// SPDX-License-Identifier: \${license}")
  set(_mutated_tpl "//x SPDX-License-Identifier: \${license}")
elseif(NODE STREQUAL "DocComment")
  # Mutate the `///` marker itself (no `=` to flip); the render provably changes.
  set(_committed_tpl "/// \${text}")
  set(_mutated_tpl "///x \${text}")
elseif(NODE STREQUAL "CompoundAssign")
  # No literal `=` to flip; append a marker so the render provably changes.
  set(_committed_tpl "\${lhs} \${op} \${rhs};")
  set(_mutated_tpl "\${lhs} \${op} \${rhs} /*mut*/;")
elseif(NODE STREQUAL "Assign")
  set(_committed_tpl "\${lhs} = \${rhs};")
  set(_mutated_tpl "\${lhs} := \${rhs};")
else()
  set(_committed_tpl "\${type} \${name} = \${rhs};")
  set(_mutated_tpl "\${type} \${name} := \${rhs};")
endif()

file(READ "${TD}" _td)
string(REPLACE "${_committed_tpl}" "${_mutated_tpl}" _td_mut "${_td}")
if(_td_mut STREQUAL _td)
  message(FATAL_ERROR
    "gen-mutated-stmt-shell VACUOUS: the ${NODE} syntax record "
    "`${_committed_tpl}` was not found in ${TD} to mutate.")
endif()

file(MAKE_DIRECTORY "${WORK}/backends/solidity")
configure_file("${SCHEMA}" "${WORK}/backends/TargetPrinter.td" COPYONLY)
file(WRITE "${WORK}/backends/solidity/mutated.td" "${_td_mut}")

execute_process(
  COMMAND python3 "${GEN}"
    --td "${WORK}/backends/solidity/mutated.td"
    --out "${WORK}/mutated_registry.inc"
    --printer-out "${OUT}"
    --tblgen "${TBLGEN}"
  RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
  message(FATAL_ERROR "gen-mutated-stmt-shell: generator failed:\n${_out}${_err}")
endif()

# Sanity: the regenerated handler must carry the mutated grammar (the generator
# consumed the record) and not the committed grammar for THIS node.
file(READ "${OUT}" _printer)
string(FIND "${_printer}" "${_mutated_tpl}" _has_mut)
string(FIND "${_printer}" "${_committed_tpl}" _has_committed)
if(_has_mut EQUAL -1 OR NOT _has_committed EQUAL -1)
  message(FATAL_ERROR
    "gen-mutated-stmt-shell: regenerated handler did not adopt the mutated `:=` "
    "grammar for ${NODE} (generator does not consume the syntax record).")
endif()
