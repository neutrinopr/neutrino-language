//===- lines_fixture_render_harness.cpp - Lines substrate render proof ----===//
//
// Renders the TEST-ONLY Lines fixture node (LinesPrinterFixture.td) through the
// GENERATED printer handler and asserts the four Lines-substrate properties
// (). The generated include is chosen at compile time via -DNODE_INC, so
// the SAME harness runs against:
//   * the COMMITTED (unmutated) fixture include -> all properties hold, exit 0;
//   * a .td-MUTATED include (a fixed line REMOVED) -> the render differs, exit
//     != 0 (property (d): a Syntax mutation changes the rendered bytes).
// A minimal LinesStmt shim stands in for a backend model, so the harness
// compiles against the generated include ALONE (linking only NeutrinoCodeText —
// no backend link). Neutrino/TargetPrinter.h is pulled in by the generated
// include, not directly here.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CodeText.h"

#include <cstdio>
#include <string>
#include <vector>

namespace neutrino {
namespace linesfixture_model {
// Minimal stand-in for a backend model: the generated printer include needs
// only the Kind enum (ordinal identical to LinesPrinterFixture.td) and the
// ordered operands the arity-generic projection reads.
struct LinesStmt {
  enum class Kind { MultiLine = 0 };
  Kind kind;
  std::vector<std::string> operands;
};
} // namespace linesfixture_model
} // namespace neutrino

#include NODE_INC // the generated printer handlers (committed or mutated)

using namespace neutrino;

// The committed fixture renders three FLAT sibling lines; the middle line
// projects operand 0.
static const char *kExpectedFlat =
    "first line\nmiddle PROJECTED line\nthird line\n";
// (a) FLATNESS: nested inside a block, all three lines share exactly ONE indent
// (same level) — NOT progressively nested like Block would produce.
static const char *kExpectedNested =
    "wrap {\n  first line\n  middle PROJECTED line\n  third line\n}\n";

int main() {
  linesfixture_model::LinesStmt s{
      linesfixture_model::LinesStmt::Kind::MultiLine, {"PROJECTED"}};

  // (c) codetext invariant: render succeeds and Document::print does not abort
  // — the driver SPLIT the projected template before constructing any line, so
  // no emitted line carries an embedded newline (validate() stays clean).
  codetext::Document doc;
  doc.add(linesfixture_model::generated_printer::render(s));
  if (!doc.validate().empty()) {
    fprintf(stderr, "lines-fixture: document malformed: %s\n",
            doc.validate().c_str());
    return 2;
  }
  std::string flat = doc.print();
  printf("flat=[%s]\n", flat.c_str());

  codetext::Document nested;
  nested.add(codetext::block(
      "wrap {", "}", {linesfixture_model::generated_printer::render(s)}));
  std::string nestedOut = nested.print();
  printf("nested=[%s]\n", nestedOut.c_str());

  // (b) per-line field projection: the MIDDLE line carries the projected value.
  bool middleProjected =
      flat.find("middle PROJECTED line") != std::string::npos;

  if (flat != kExpectedFlat) {
    fprintf(stderr,
            "flat render mismatch:\n  got:      [%s]\n  expected: [%s]\n",
            flat.c_str(), kExpectedFlat);
    return 1;
  }
  if (nestedOut != kExpectedNested) {
    fprintf(stderr,
            "nested flatness mismatch:\n  got:      [%s]\n  expected: [%s]\n",
            nestedOut.c_str(), kExpectedNested);
    return 1;
  }
  if (!middleProjected) {
    fprintf(stderr, "middle-line field projection missing\n");
    return 1;
  }
  return 0;
}
