//===- framed_lines_fixture_render_harness.cpp - framed-lines render proof
//-===//
//
// Renders the TEST-ONLY framed-lines fixture node (FramedLinesFixture.td)
// through the REAL GENERATED printer handler and asserts the
// framed-lines-substrate properties. The generated include is chosen at compile
// time via -DNODE_INC, so the SAME harness runs against:
//   * the COMMITTED (unmutated) fixture include -> all properties hold, exit 0;
//   * a .td-MUTATED include (a token in Header/ItemSyntax/Footer changed) ->
//   the
//     render differs, exit != 0 — proving the record drives production bytes.
// A minimal FramedStmt shim stands in for a backend model (its `.group` carries
// the item tuples), so the harness compiles against the generated include
// ALONE, linking only NeutrinoCodeText.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CodeText.h"

#include <cstdio>
#include <string>
#include <vector>

namespace neutrino {
namespace framedfixture_model {
// Minimal stand-in for a backend model: the generated printer needs the Kind
// enum (ordinal identical to FramedLinesFixture.td), the ordered scalar
// operands (none here — framed-lines header/footer are literal), and the
// repeated item `group` (one [input, set, quorum] tuple per rendered item
// line).
struct FramedStmt {
  enum class Kind { PolicyCase = 0 };
  Kind kind;
  std::vector<std::string> operands;
  std::vector<std::vector<std::string>> group;
};
} // namespace framedfixture_model
} // namespace neutrino

#include NODE_INC // the generated printer handlers (committed or mutated)

using namespace neutrino;

// THREE item lines (a UNIQUE middle) between a fixed header/footer, each
// projecting its tuple in order.
static const char *kExpectedFlat =
    "CASE p_policy\n"
    "  WHEN 'p_hi' THEN v_set := 'set_hi'; v_m := 2;\n"
    "  WHEN 'p_mid' THEN v_set := 'set_mid'; v_m := 5;\n"
    "  WHEN 'p_lo' THEN v_set := 'set_lo'; v_m := 1;\n"
    "  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
    "END CASE;\n";
// The unique MIDDLE item, at its exact position (line index 2: after the header
// and the first item, before the last item).
static const char *kExpectedMiddleLine =
    "  WHEN 'p_mid' THEN v_set := 'set_mid'; v_m := 5;";
// FLATNESS: nested in a block, every header/item/footer line shares exactly ONE
// indent level — NOT progressive nesting.
static const char *kExpectedNested =
    "wrap {\n"
    "  CASE p_policy\n"
    "    WHEN 'p_hi' THEN v_set := 'set_hi'; v_m := 2;\n"
    "    WHEN 'p_mid' THEN v_set := 'set_mid'; v_m := 5;\n"
    "    WHEN 'p_lo' THEN v_set := 'set_lo'; v_m := 1;\n"
    "    ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
    "  END CASE;\n"
    "}\n";

int main() {
  framedfixture_model::FramedStmt s{
      framedfixture_model::FramedStmt::Kind::PolicyCase,
      /*operands=*/{},
      /*group=*/
      {{"'p_hi'", "'set_hi'", "2"},
       {"'p_mid'", "'set_mid'", "5"},
       {"'p_lo'", "'set_lo'", "1"}}};

  // codetext invariant: render succeeds and print() does not abort — the driver
  // split every template before constructing any line, so no line carries an
  // embedded newline.
  codetext::Document doc;
  doc.add(framedfixture_model::generated_printer::render(s));
  if (!doc.validate().empty()) {
    fprintf(stderr, "framed-lines-fixture: document malformed: %s\n",
            doc.validate().c_str());
    return 2;
  }
  std::string flat = doc.print();
  printf("flat=[%s]\n", flat.c_str());

  codetext::Document nested;
  nested.add(codetext::block(
      "wrap {", "}", {framedfixture_model::generated_printer::render(s)}));
  std::string nestedOut = nested.print();
  printf("nested=[%s]\n", nestedOut.c_str());

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

  // Middle-item projection AT its exact position: with header=line0 and the
  // first item=line1, the UNIQUE middle tuple must project at line index 2
  // (before the last item) — proving order + per-item projection, not just that
  // the set of lines is present.
  {
    std::vector<std::string> flatLines;
    std::size_t start = 0, nl;
    while ((nl = flat.find('\n', start)) != std::string::npos) {
      flatLines.push_back(flat.substr(start, nl - start));
      start = nl + 1;
    }
    if (flatLines.size() < 3 || flatLines[2] != kExpectedMiddleLine) {
      fprintf(stderr,
              "middle-item position mismatch: line[2]=[%s] expected [%s]\n",
              flatLines.size() > 2 ? flatLines[2].c_str() : "<none>",
              kExpectedMiddleLine);
      return 1;
    }
  }

  // 0-item control: header+footer only, no item lines (the layout does not
  // require items — semantic cardinality is the upstream factory's job).
  framedfixture_model::FramedStmt empty{
      framedfixture_model::FramedStmt::Kind::PolicyCase, {}, {}};
  codetext::Document e;
  e.add(framedfixture_model::generated_printer::render(empty));
  const char *kExpectedEmpty =
      "CASE p_policy\n"
      "  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
      "END CASE;\n";
  if (e.print() != kExpectedEmpty) {
    fprintf(stderr, "zero-item render mismatch:\n  got: [%s]\n",
            e.print().c_str());
    return 1;
  }
  return 0;
}
