//===- GenSoliditySpec.cpp - Solidity contract entry -------------------===//
//
// Public ABI wrappers project once, then delegate to the graph-only Solidity
// adapter. The backend never receives the CoordinationPlan.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSoliditySpec.h"

#include "SolidityRecipeProvider.h"
#include "SolidityTargetValidation.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/StrCase.h"

#include "llvm/Support/Error.h"

#include <string>
#include <vector>

namespace neutrino {

namespace {
projection::BackendProjectionGraph
projectForSolidity(const CoordinationPlan &coordinationPlan) {
  llvm::Expected<projection::BackendProjectionGraph> projection =
      projection::projectBackendGraph(coordinationPlan);
  if (!projection)
    solidity_model::specFail(llvm::toString(projection.takeError()));
  return std::move(*projection);
}
} // namespace

std::string
generateSolidityContractFromSpec(const CoordinationPlan &coordinationPlan) {
  return solidity_model::materializeSolidityProjectionArtifact(
             projectForSolidity(coordinationPlan))
      .contractSource;
}

std::vector<SoliditySourceFile>
generateSoliditySourcesFromSpec(const CoordinationPlan &coordinationPlan) {
  // Thin from-spec adapter: hydrate the plan into the backend graph, then
  // dispatch to the roled provider that owns the SoliditySourceFile
  // composition. No tracked construction lives here.
  return solidity_model::materializeSoliditySources(
      projectForSolidity(coordinationPlan));
}

} // namespace neutrino
