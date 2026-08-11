//===- SolidityTargetValidation.h - fail-closed target-node policy -------===//
//
// The reusable fail-closed validation policy over the typed Solidity target
// nodes: the single throw site (`specFail`), the per-node lexical/vocabulary
// contract (`validateGeneratedSolStmt`) the generated factories route through,
// and the typed-parameter projection those factories use. Kept separate from
// the generated per-node ABI (SolidityTargetAdapter) and the layout renderer
// (SolidityRenderer): validation is C++ policy, not schema-derived shape.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYTARGETVALIDATION_H
#define NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYTARGETVALIDATION_H

#include "SolidityTargetAdapter.h"

#include <string>
#include <vector>

namespace neutrino {
namespace solidity_model {

// Shared fail-closed projection boundary used by the public ABI wrapper and
// graph materializer; the single implementation preserves the throw ratchet.
[[noreturn]] void specFail(const std::string &message);

// Validation is reusable C++ policy, separate from the generated per-node ABI
// and storage mapping. The generated builder owns only schema-derived field
// order/cardinality and calls this one seam after projecting those typed
// inputs.
void validateGeneratedSolStmt(
    SolStmt::Kind kind, const std::vector<std::string> &operands,
    const std::vector<SolStmt> &body,
    const std::vector<std::vector<std::string>> &group,
    const std::vector<std::vector<int>> &enumOrdinals);

// Project + validate a typed parameter list into the generated node's repeated
// group (one `[type, location, name]` item per parameter). The generated
// event/function/interface factories call this; it lives with the validation
// policy because each parameter is checked (validateParam) as a closed shape.
std::vector<std::vector<std::string>>
projectGeneratedParams(const std::vector<SolParam> &params, const char *ctx);

} // namespace solidity_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYTARGETVALIDATION_H
