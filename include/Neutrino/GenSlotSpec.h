#ifndef NEUTRINO_GENSLOTSPEC_H
#define NEUTRINO_GENSLOTSPEC_H

#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

struct SlotArtifact {
  std::string name;
  std::string content;
};

using SlotArtifacts = std::vector<SlotArtifact>;

// Render target-neutral coordination artifacts from the frozen capability
// contract. Production backend claims belong to full-profile adapters.
SlotArtifacts generateSlotFromSpec(const llvm::json::Object &spec);

// Recompute capability.lock after a typed artifact transformation. The lock
// algorithm is target-neutral and remains authoritative in the public core.
void refreshSlotCapabilityLock(SlotArtifacts &artifacts);

} // namespace neutrino

#endif // NEUTRINO_GENSLOTSPEC_H
