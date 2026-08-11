//===- SolidityRenderer.h - materialized Solidity contract + renderer ----===//
//
// The materialized target model (contract/function/event/storage aggregates)
// and the layout-only renderer that lays it out to Solidity source via
// codetext. Every field is supplied by projection traversal and target idioms;
// the renderer references no construct Kind. Backend-internal seam header:
// consumes only the typed coordination leaf, never View.h.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYRENDERER_H
#define NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYRENDERER_H

#include "SolidityTargetAdapter.h"

#include <optional>
#include <string>
#include <vector>

namespace neutrino {
namespace solidity_model {

// The `enum <name> { <variants> }` declaration the contract's status uses.
struct SolEnum {
  std::string name;
  std::vector<std::string> variants;
};

enum class SoliditySourceRequirement {
  ThresholdQuorumAcceptance,
  CoordinationEnvelope,
};

struct SoliditySourceDependency {
  SoliditySourceRequirement kind;
  std::vector<std::string> canonicalizations;
};

// One authoritative storage-slot print record (): the typed StorageDecl
// node (its `.td`-owned `<type> <modifiers> <name>;` syntax) bundled with its
// optional trailing comment BODY (unframed — codetext owns the `// `). Bundling
// the two removes the parallel-vector hazard — the printer never indexes a decl
// against a separately-stored comment.
struct StorageSlot {
  SolStmt decl;
  std::string comment;
};

// The materialized Solidity coordination contract. Every field is supplied by
// projection traversal and target idioms; the renderer lays it out in order.
struct SolidityContract {
  std::string name;
  std::string targetSourceName;
  std::vector<SoliditySourceDependency> sourceDependencies;
  bool evidenceOnly = false;
  bool gated = false;          // quorum-gated (vs legacy self-attest)
  std::vector<SolStmt> header; // SPDX/pragma/doc + optional guard iface
  // : the contract is ONE composed typed node tree — the whole body (status
  // enum, events, storage slots with their inert trailing comments, and the
  // functions, blank-separated) rides this single ContractShell container node,
  // composed ENTIRELY by the closed recipe grammar
  // (Sequence/Emit/ForEach/OptionalOp/Call/Nested) — see the contract recipes.
  // There are no parallel semantic (statusEnum/events/storage/functions) or
  // rendered-node (typeDeclarations/eventDecls/storageSlots/functionNodes)
  // duplicates to keep synchronized: the renderer recurses this node through the
  // generic `toNode` and prints. Optional only because SolStmt is immutable (no
  // default ctor); projection materialization always sets it.
  std::optional<SolStmt> containerNode;
};

// Render a materialized model to Solidity source — layout only, via codetext.
std::string renderSolidityProjection(const SolidityContract &model);

} // namespace solidity_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYRENDERER_H
