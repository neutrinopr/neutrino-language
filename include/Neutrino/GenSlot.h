#ifndef NEUTRINO_GENSLOT_H
#define NEUTRINO_GENSLOT_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Registry entry for target-neutral slot coordination artifacts. Full-profile
// adapters may append package-owned backend declarations; retained core does
// not.
std::vector<std::string>
emitSlotProject(const ProcedureView &view, const Scenario &scenario,
                const std::string &outDir,
                const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENSLOT_H
