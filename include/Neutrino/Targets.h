#ifndef NEUTRINO_TARGETS_H
#define NEUTRINO_TARGETS_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Target registry (T9 R1 /  — split out of the former kitchen-sink
// Backends.h). Dispatch validates the CoordinationPlan once and passes it
// through the registry boundary, so an emitter never re-normalizes a
// user-provided view through an invariant-only path. The lowering/gating
// classification and valid-target list derive from the same table instead of
// being duplicated across the CLI. Adding a target = adding one entry (plus
// its per-target Gen<Target>.h). See
// docs/backends/BACKEND_GENERATORS.md.
using EmitFn = std::vector<std::string> (*)(const ProcedureView &,
                                            const Scenario &,
                                            const std::string &,
                                            const CoordinationPlan &);
struct TargetSpec {
  std::string name;
  EmitFn emit;
  // A value-lowering target produces deployable/coordination artifacts and is
  // refused for a capability with hard security violations. A bundled
  // development path may override its local renderer gate, but this
  // classification is not external-package dispatch authorization. Analysis
  // targets (security/capability/coverage) are never gated.
  bool gated;
  // A scenario-free target emits from source alone and ignores --scenario (the
  // canonical spec, D2; ): the CLI selects the procedure from the module
  // directly instead of via scenario.procedure, and requires no --scenario.
  bool scenarioFree = false;
  // A driver-serialized target's artifacts are written DIRECTLY by the driver
  // (neutrino-gen) with checked `Expected` propagation, so it registers NO emit
  // function (`emit == nullptr`) and must never be dispatched through
  // `TargetSpec::emit`. This keeps the registry honest: a fallible target is
  // represented explicitly here, never as a publicly-callable registered
  // emitter whose only behavior is to abort ( re-review).
  bool driverSerialized = false;
};
// Registered targets, in CLI/usage order.
const std::vector<TargetSpec> &targetRegistry();
// The TargetSpec for `name`, or nullptr if it is not a registered target.
const TargetSpec *findTarget(const std::string &name);
// The human-readable target list for usage/errors, e.g.
// "'solidity', 'postgres', ..., or 'views'".
std::string targetUsageList();

} // namespace neutrino

#endif // NEUTRINO_TARGETS_H
