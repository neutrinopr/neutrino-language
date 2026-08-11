//===- SolidityRenderer.cpp - materialized model -> Solidity source ------===//
//
// Lays a materialized SolidityContract out to Solidity source via codetext —
// layout only. This file has no CoordinationPlan/spec/L2 intake or fallback
// entry; it consumes only the typed target model the adapter materialized.
// Output is byte-identical to the pre-split renderer (proved by the Solidity
// goldens).
//
//===----------------------------------------------------------------------===//

#include "SolidityRenderer.h"
#include "SolidityTargetValidation.h"

#include "Neutrino/CodeText.h"

#include <string>

namespace neutrino {
namespace solidity_model {

std::string renderSolidityProjection(const SolidityContract &m) {
  using namespace codetext;
  // : THIN generic renderer. The contract is one composed typed node tree —
  // the source-unit header records plus a ContractShell whose ordered body (type
  // declarations, events, storage slots with their inert trailing comments, and
  // the functions, blank-separated) is composed ENTIRELY by the closed recipe
  // grammar (Sequence/Emit/ForEach/OptionalOp/Call/Nested). This renderer
  // therefore owns NO section ordering, spacing, or comment-column alignment: it
  // just recurses each root through the shared generic `toNode` (which performs
  // the generic trailing-comment alignment) and prints. Output is byte-identical
  // to the pre- handwritten composition (the Solidity goldens prove it).
  Document doc;
  for (const SolStmt &h : m.header)
    doc.add(toNode(h));
  // FAIL-CLOSED: `containerNode` is an invariant every materialization path
  // establishes; an absent node means the model never went through
  // legalization, so refuse to render rather than dereference an empty optional
  // (UB).
  if (!m.containerNode)
    specFail("renderSolidityProjection: the contract carries no ContractShell "
             "container node — projection materialization did not run");
  doc.add(toNode(*m.containerNode));
  return doc.print("    ");
}

} // namespace solidity_model
} // namespace neutrino
