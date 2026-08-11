#ifndef NEUTRINO_SOLIDITY_PACKAGE_ARTIFACTS_H
#define NEUTRINO_SOLIDITY_PACKAGE_ARTIFACTS_H

#include "llvm/ADT/StringRef.h"

#include <string>
#include <vector>

namespace neutrino {

// The package-owned artifact boundary used by the external protocol entry.
// It deliberately names no compiler plan, scenario, or source representation.
struct SoliditySourceFile {
  std::string path;
  std::string content;
};

std::string generateThresholdQuorumGuardForCanonicalization(
    llvm::StringRef canonicalization);
std::string generateCoordinationEnvelope();

} // namespace neutrino

#endif // NEUTRINO_SOLIDITY_PACKAGE_ARTIFACTS_H
