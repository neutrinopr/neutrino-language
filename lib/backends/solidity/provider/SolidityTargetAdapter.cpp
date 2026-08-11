//===- SolidityTargetAdapter.cpp - typed target-node factories + toNode --===//
//
// The generated SolStmt factory DEFINITIONS (each routes through the shared
// validation seam and the  construction guard) and the single
// adapter->codetext boundary (toNode). No CoordinationPlan/spec/L2 intake; the
// layout renderer lives in SolidityRenderer.cpp.
//
//===----------------------------------------------------------------------===//

#include "SolidityTargetAdapter.h"
#include "SolidityTargetValidation.h"

#include <string>
#include <utility>
#include <vector>

// The generated printer driver (generated_printer::render), the codetext sink
// toNode projects each typed node through.
#include "SolidityPrinterHandlers.inc"

namespace neutrino {
namespace solidity_model {

namespace {
// Project a typed enum-field value list to the generated node's ordinal group
// (the enum VALUES are legalization-decided; the SPELLING is TableGen-owned).
// Used only by the generated FunctionSig factory below; no validation
// dependency, so it lives with its sole caller.
template <typename Enum>
std::vector<int> projectGeneratedEnumOrdinals(const std::vector<Enum> &values) {
  std::vector<int> ordinals;
  ordinals.reserve(values.size());
  for (Enum value : values)
    ordinals.push_back(static_cast<int>(value));
  return ordinals;
}
} // namespace

// The typed target-node factory DEFINITIONS generated from
// SolidityTargetNodes.td. Each projects its typed inputs, calls
// validateGeneratedSolStmt (the shared fail-closed seam, in
// SolidityTargetValidation), and constructs an immutable SolStmt through the
// private canonical ctor (which routes through SolStmt::ensureAuthorable).
#include "SolidityEmitBuilders.inc"

// One legalized statement -> one codetext node. This is the whole adapter's
// codetext semantics: the TYPED shapes expand to their fixed Solidity syntax;
// framing nests; a Line is verbatim. No shape carries a decision — the layout
// is fixed.
codetext::Node toNode(const SolStmt &s) {
  using namespace codetext;
  // Every SolStmt::Kind is now emitted by the shared generated printer driver:
  // leaves render their fixed line/blank syntax; the nesting shapes (Guarded,
  // Block) frame their recursively-lowered children between the generated
  // open/close delimiters. No handwritten emission or dispatch remains — the
  // layout is entirely .td-owned.
  //
  // A node that carries an inert `comment` renders through the generic
  // `CommentedLine` printer layout (baaa6f), which OWNS the `// ` framing —
  // this backend constructs no codetext comment node. The per-node comment body
  // is handed over as `CommentedLineData`; the padding is left at 0 here because
  // the shared trailing-comment column is a document-layout concern, not a
  // backend one: `codetext::alignTrailingComments` (a target-blind policy)
  // re-pads the commented siblings into one column below. This backend performs
  // NO sibling-width calculation.
  std::vector<Node> children;
  children.reserve(s.body.size());
  for (const SolStmt &c : s.body) {
    if (c.comment.empty())
      children.push_back(toNode(c));
    else
      children.push_back(generated_printer::render(
          c, {}, target_printer::CommentedLineData{0, c.comment}));
  }
  alignTrailingComments(children);
  return generated_printer::render(s, std::move(children));
}

} // namespace solidity_model
} // namespace neutrino
