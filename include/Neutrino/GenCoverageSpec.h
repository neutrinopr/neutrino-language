#ifndef NEUTRINO_GENCOVERAGESPEC_H
#define NEUTRINO_GENCOVERAGESPEC_H

#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

// Derive target-neutral language coverage from the frozen capability-spec.
// This retained-core API owns exercised levels and network-owned classification
// only; production backend availability and maturity belong to full-profile
// adapters or backend packages.
std::string coverageReportFromSpec(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_GENCOVERAGESPEC_H
