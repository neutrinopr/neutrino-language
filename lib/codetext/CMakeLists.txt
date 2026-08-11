# The language-neutral structured code emitter LEAF (M5 codetext S1, ). A bottom-of-the-graph
# utility: a block/line/blank document model whose printer owns indentation + structural newlines
# (docs/backends/CODETEXT.md). Generic emission MECHANICS only — NO target semantics, NO ProcedureView, NO
# MLIR dialect, NO renderer/backend policy — so ANY backend/policy module can depend on it WITHOUT the
# NeutrinoEmit monolith and WITHOUT a backend-to-backend edge (the foundation for the  migrations).
# Links ONLY MLIRSupport (llvm StringRef); it is NOT the NeutrinoSpecContract leaf, so the
# module-composition gate does not treat it as a spec-renderer module. `NeutrinoCodeText` is exercised
# standalone by the gtest unit tier (unittests/CodeTextTest.cpp, ) — no backend needed.
add_mlir_library(NeutrinoCodeText
  CodeText.cpp
  TargetPrinter.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  MLIRSupport
)

# [] TEST-ONLY proof of the shared target-printer `Lines` layout: a single
# generated node renders a FLAT multi-line statement. The fixture .td
# (test/LinesPrinterFixture.td) is NOT a production backend — it lives here, under
# a non-`*TargetNodes.td` name, so the backend-discovery globs never see it. One
# render harness (a minimal LinesStmt shim + the generated printer include,
# linking only NeutrinoCodeText) is compiled twice:
#   * against the COMMITTED (unmutated) fixture include -> renders three flat
#     sibling lines with the middle-line field projected (properties a/b/c);
#   * against a .td-MUTATED include (a fixed line removed) -> renders differently,
#     proving a Syntax mutation changes the rendered bytes (property d).
set(_lines_fixture_td ${CMAKE_CURRENT_SOURCE_DIR}/test/LinesPrinterFixture.td)
set(_lines_fixture_work ${CMAKE_CURRENT_BINARY_DIR}/lines_fixture)
set(_lines_committed_inc ${_lines_fixture_work}/committed_printer.inc)
set(_lines_mutated_inc ${_lines_fixture_work}/mutated_printer.inc)

foreach(_variant committed mutated)
  if(_variant STREQUAL "mutated")
    set(_out ${_lines_mutated_inc})
    set(_mutate_arg -DMUTATE=1)
  else()
    set(_out ${_lines_committed_inc})
    set(_mutate_arg)
  endif()
  add_custom_command(OUTPUT ${_out}
    COMMAND ${CMAKE_COMMAND}
      -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
      -DTD=${_lines_fixture_td}
      -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
      -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
      -DWORK=${_lines_fixture_work}/${_variant}
      -DOUT=${_out} ${_mutate_arg}
      -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_lines_fixture_inc.cmake
    DEPENDS ${_lines_fixture_td} ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
            ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
            ${PROJECT_SOURCE_DIR}/test/cmake/gen_lines_fixture_inc.cmake
    COMMENT "Generating the ${_variant} Lines-fixture printer include ()")
  add_custom_target(lines-fixture-${_variant}-inc DEPENDS ${_out})

  add_executable(lines-fixture-render-${_variant} test/lines_fixture_render_harness.cpp)
  add_dependencies(lines-fixture-render-${_variant} lines-fixture-${_variant}-inc)
  target_compile_definitions(lines-fixture-render-${_variant} PRIVATE
    "NODE_INC=\"${_out}\"")
  target_link_libraries(lines-fixture-render-${_variant} PRIVATE NeutrinoCodeText)
endforeach()

# The committed harness IS the render unit test (asserts properties a/b/c).
neutrino_register_test(NAME lines-fixture-render COMMAND lines-fixture-render-committed)
neutrino_register_test_properties(lines-fixture-render PROPERTIES LABELS "ctest-native")

# The pair driver asserts property (d): committed renders the 3-line form; the
# .td-mutated handler drops a line and fails it.
neutrino_register_test(NAME lines-fixture-td-mutation COMMAND ${CMAKE_COMMAND}
  -DCOMMITTED=$<TARGET_FILE:lines-fixture-render-committed>
  -DMUTATED=$<TARGET_FILE:lines-fixture-render-mutated>
  -P ${PROJECT_SOURCE_DIR}/test/cmake/run_lines_fixture_render_pair.cmake)
neutrino_register_test_properties(lines-fixture-td-mutation PROPERTIES LABELS "ctest-native")

# [] TEST-ONLY proof of the shared `framed-lines` layout: a single generated
# node renders a fixed header + one item template repeated per model tuple + a
# fixed footer. The fixture .td (test/FramedLinesFixture.td) is NOT a production
# backend — non-`*TargetNodes.td` name, so the discovery globs never see it. The
# render harness (a minimal FramedStmt shim + the generated include, linking only
# NeutrinoCodeText) is compiled against the COMMITTED include (renders
# header+items+footer, per-item projection, unique-middle position, 0/N items)
# AND against four INDEPENDENTLY-mutated includes — one per closed-frame surface
# (header, item operator, footer, item-placeholder wiring) — each of which
# renders differently, proving every surface of the record drives production
# bytes rather than one incidental token.
set(_framed_fixture_td ${CMAKE_CURRENT_SOURCE_DIR}/test/FramedLinesFixture.td)
set(_framed_fixture_work ${CMAKE_CURRENT_BINARY_DIR}/framed_lines_fixture)
set(_framed_committed_inc ${_framed_fixture_work}/committed_printer.inc)

# variant -> (MUTATE_MODE, EXPECT_TOKEN the mutated render must carry)
set(_framed_mutation_modes header item footer placeholder)
set(_framed_token_header "CASE p_policyX")
set(_framed_token_item "v_set ::=")
set(_framed_token_footer "END CASEX;")
set(_framed_token_placeholder "v_set := 2;")

foreach(_variant committed ${_framed_mutation_modes})
  set(_fout ${_framed_fixture_work}/${_variant}_printer.inc)
  if(_variant STREQUAL "committed")
    set(_fmutate_arg)
  else()
    set(_fmutate_arg -DMUTATE_MODE=${_variant})
  endif()
  add_custom_command(OUTPUT ${_fout}
    COMMAND ${CMAKE_COMMAND}
      -DGEN=${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
      -DTD=${_framed_fixture_td}
      -DSCHEMA=${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
      -DTBLGEN=${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
      -DWORK=${_framed_fixture_work}/${_variant}
      -DOUT=${_fout} ${_fmutate_arg}
      -P ${PROJECT_SOURCE_DIR}/test/cmake/gen_framed_lines_fixture_inc.cmake
    DEPENDS ${_framed_fixture_td} ${PROJECT_SOURCE_DIR}/lib/backends/TargetPrinter.td
            ${PROJECT_SOURCE_DIR}/scripts/generators/gen_target_node_registry.py
            ${PROJECT_SOURCE_DIR}/test/cmake/gen_framed_lines_fixture_inc.cmake
    COMMENT "Generating the ${_variant} framed-lines-fixture printer include ()")
  add_custom_target(framed-lines-fixture-${_variant}-inc DEPENDS ${_fout})

  add_executable(framed-lines-fixture-render-${_variant} test/framed_lines_fixture_render_harness.cpp)
  add_dependencies(framed-lines-fixture-render-${_variant} framed-lines-fixture-${_variant}-inc)
  target_compile_definitions(framed-lines-fixture-render-${_variant} PRIVATE
    "NODE_INC=\"${_fout}\"")
  target_link_libraries(framed-lines-fixture-render-${_variant} PRIVATE NeutrinoCodeText)
endforeach()

# The committed harness IS the render unit test (header+items+footer, per-item
# projection, unique-middle position, flatness, 0/N items).
neutrino_register_test(NAME framed-lines-fixture-render COMMAND framed-lines-fixture-render-committed)
neutrino_register_test_properties(framed-lines-fixture-render PROPERTIES LABELS "ctest-native")

# One pair driver per surface: committed renders the frame; the surface-mutated
# handler changes output (carrying the surface-specific token) and fails the
# golden — so header, item operator, footer, and item-placeholder wiring each
# independently drive production bytes.
foreach(_mode ${_framed_mutation_modes})
  neutrino_register_test(NAME framed-lines-fixture-td-mutation-${_mode} COMMAND ${CMAKE_COMMAND}
    -DCOMMITTED=$<TARGET_FILE:framed-lines-fixture-render-committed>
    -DMUTATED=$<TARGET_FILE:framed-lines-fixture-render-${_mode}>
    -DMODE=${_mode}
    -DEXPECT_TOKEN=${_framed_token_${_mode}}
    -P ${PROJECT_SOURCE_DIR}/test/cmake/run_framed_lines_fixture_render_pair.cmake)
  neutrino_register_test_properties(framed-lines-fixture-td-mutation-${_mode} PROPERTIES LABELS "ctest-native")
endforeach()
