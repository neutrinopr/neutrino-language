#ifndef NEUTRINO_GENSECURITY_H
#define NEUTRINO_GENSECURITY_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Capability Security Pass (Phase 20): domain-aware business/trust invariant
// report (security.json) — authorization, value, topology, trust-boundary,
// state.
//
// Target-owned generator contract (): the `security` target's emit entry
// lives here. Matches the registry EmitFn; analysis target (not
// security-gated). The shared `hasSecurityViolations` predicate (used by the
// gate too) lives in Neutrino/Validate.h. See
// docs/backends/BACKEND_GENERATORS.md.
std::vector<std::string> emitSecurity(const ProcedureView &view,
                                      const Scenario &scenario,
                                      const std::string &outDir,
                                      const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENSECURITY_H
