#ifndef NEUTRINO_VALIDATE_H
#define NEUTRINO_VALIDATE_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// Scenario/security validation over a ProcedureView (T9 R1 /  — split out
// of the former kitchen-sink Backends.h). See
// docs/backends/BACKEND_GENERATORS.md.

// Validate a scenario against the procedure it targets: required inputs
// present, input types match (numeric vs string), computed keys declared (no
// unknown keys), declared expect.computed values equal evaluation over the
// inputs, money amounts non-negative, no unknown inputs. Returns
// human-readable error messages (empty == valid).
std::vector<std::string> validateScenario(const ProcedureView &view,
                                          const Scenario &scenario);

// True if the Capability Security Pass finds any hard violation (authorization,
// value, or topology). Shared by the security report and the gate so they
// agree.
bool hasSecurityViolations(const ProcedureView &view,
                           const CoordinationPlan &coordinationPlan);

// The same core pre-dispatch security admission over an already validated
// canonical capability spec. This is the external --from-spec authority; it
// must remain identical to the source path's view -> spec admission.
bool hasSecurityViolations(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_VALIDATE_H
