#ifndef NEUTRINO_GENCOVERAGE_H
#define NEUTRINO_GENCOVERAGE_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Registry entry for the target-neutral language-coverage report. Full-profile
// adapters may append package-owned maturity facts, but the retained core
// report does not assert production backend capabilities.
std::vector<std::string> emitCoverage(const ProcedureView &view,
                                      const Scenario &scenario,
                                      const std::string &outDir,
                                      const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENCOVERAGE_H
