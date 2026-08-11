#ifndef NEUTRINO_GENCAPABILITYMODELSPEC_H
#define NEUTRINO_GENCAPABILITYMODELSPEC_H

#include "Neutrino/BackendPackage.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

struct CapabilityModelArtifact {
  std::string fileName;
  std::string bytes;
};

// Builds one deterministic capability model for every verified package profile
// in target order. Package profiles are the sole source of target-specific
// facts; the capability spec contributes only the source capability witness.
llvm::Expected<std::vector<CapabilityModelArtifact>>
generateCapabilityModelsFromSpec(
    const llvm::json::Object &spec, llvm::StringRef catalogIdentity,
    llvm::ArrayRef<backend_package::TargetProfile> profiles);

// Total, injective mapping from an admitted target identity to one artifact
// basename. The two established safe identities retain their public filenames.
std::string capabilityModelArtifactName(llvm::StringRef target);

llvm::Expected<std::string> capabilityModelCatalogBytes(
    llvm::StringRef catalogIdentity,
    llvm::ArrayRef<backend_package::TargetProfile> profiles);

} // namespace neutrino

#endif // NEUTRINO_GENCAPABILITYMODELSPEC_H
