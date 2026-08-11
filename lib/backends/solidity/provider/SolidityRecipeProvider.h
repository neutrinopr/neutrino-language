//===- SolidityRecipeProvider.h - generated-recipe Solidity adapter -------===//
//
// Backend-internal  seam.  Callers supply one exact finalized recipe key;
// the generic runtime traverses the generated module and the single Solidity
// provider constructs the resulting typed target nodes.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYRECIPEPROVIDER_H
#define NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYRECIPEPROVIDER_H

#include "Neutrino/SolidityPackageArtifacts.h"
#include "SolidityRenderer.h"

namespace neutrino {
namespace solidity_model {

struct SolidityProjectionArtifact {
  SolidityContract contractModel;
  std::string contractSource;
  std::vector<SoliditySourceFile> namedSources;
};

SolidityProjectionArtifact materializeSolidityProjectionArtifact(
    const projection::BackendProjectionGraph &projection);

// The named-sources projection: materializes the artifact and hands back its
// SoliditySourceFile bundle. Lives in the recipe-provider (the roled provider
// plumbing) so the from-spec ABI adapter holds no tracked construction.
std::vector<SoliditySourceFile> materializeSoliditySources(
    const projection::BackendProjectionGraph &projection);

void appendEvidenceGuardConsumerRecipe(std::vector<SolStmt> &output);
void appendTemporalGuardConsumerRecipe(std::vector<SolStmt> &output);
SolidityContract materializeEvidenceContractRecipe(
    const projection::FinalizedProjectionSequence &sequence);
SolidityContract materializeTemporalContractRecipe(
    const projection::FinalizedProjectionSequence &sequence);
SolidityContract materializeEffectfulWithAttestationContractRecipe(
    const projection::FinalizedProjectionSequence &sequence);
SolidityContract materializeEffectfulWithoutAttestationContractRecipe(
    const projection::FinalizedProjectionSequence &sequence);

} // namespace solidity_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYRECIPEPROVIDER_H
