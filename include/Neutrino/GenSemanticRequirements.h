#ifndef NEUTRINO_GENSEMANTICREQUIREMENTS_H
#define NEUTRINO_GENSEMANTICREQUIREMENTS_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Serialize the compiler-owned semantic requirements derived from a verified
// CoordinationPlan. Shared by source and external-spec reconstruction paths.
std::string
semanticRequirementsToText(const CoordinationPlan &coordinationPlan);

// Scenario-free, non-gated semantic requirement projection.
std::vector<std::string>
emitSemanticRequirements(const ProcedureView &view, const Scenario &scenario,
                         const std::string &outDir,
                         const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENSEMANTICREQUIREMENTS_H
