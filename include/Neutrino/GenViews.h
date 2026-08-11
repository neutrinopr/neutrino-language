#ifndef NEUTRINO_GENVIEWS_H
#define NEUTRINO_GENVIEWS_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Per-participant narrowed views (Trust lane, T5): one <participant>.json per
// declared participant, showing only the slice that participant is responsible
// for — visible operations, required inputs, permitted counterparties, binding
// policy, and evidence obligations (the legs it authorizes). No participant
// view leaks another participant's obligations. Empty when no participants are
// declared.
//
// Target-owned generator contract (): the `views` target's emit entry lives
// here, not in the shared Backends.h. Matches the registry EmitFn; `views` IS
// gated (an agent-facing implementation contract). See
// docs/backends/BACKEND_GENERATORS.md.
std::vector<std::string> emitViews(const ProcedureView &view,
                                   const Scenario &scenario,
                                   const std::string &outDir,
                                   const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENVIEWS_H
