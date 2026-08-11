//===- TargetRegistry.cpp - the generation target table ------------------===//
//
// A single source of truth for the generation targets. The CLI derives
// the valid-target list, the lowering/gating classification, and the emit
// dispatch from this table, so adding a backend target is one entry here rather
// than three edits scattered across the tool.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/TargetCatalog.h"
#include "Neutrino/Targets.h"
// Per-target generator contracts: every target owns its header,
// included here so the registry table references its emit entry without the
// declaration living in the shared Backends.h. See
// docs/backends/BACKEND_GENERATORS.md.
#include "Neutrino/GenAgreementEnvelope.h"
#include "Neutrino/GenCoordinationPlan.h"
#include "Neutrino/GenCoordinationTrace.h"
#include "Neutrino/GenCoverage.h"
#include "Neutrino/GenSecurity.h"
#include "Neutrino/GenSemanticRequirements.h"
#include "Neutrino/GenSlot.h"
#include "Neutrino/GenSpec.h"
#include "Neutrino/GenViews.h"
#include "Neutrino/TestRealization.h"
#ifndef NEUTRINO_CORE_ONLY
#include "Neutrino/GenPostgres.h"
#endif

namespace neutrino {

llvm::Expected<TargetCatalog>
loadTargetCatalog(llvm::ArrayRef<std::string> packageDirectories) {
  return loadTargetCatalogWithBuiltins(packageDirectories, targetRegistry());
}

const std::vector<TargetSpec> &targetRegistry() {
  // The table is generated from the declarative source
  // include/Neutrino/TargetRegistry.def — this file no
  // longer owns an independent hand-maintained table. Add/change a target
  // THERE, not here; the per-target rationale (gating/scenario-free) lives
  // beside each row, and the profile↔registry reconciliation is byte-gated by
  // self-test [97].
  static const std::vector<TargetSpec> kTargets = {
#define NEUTRINO_TARGET(Name, Emit, Gated, ScenarioFree)                       \
  {Name, Emit, Gated, ScenarioFree, /*driverSerialized=*/false},
// A driver-serialized target registers NO emit function (): the driver
// writes its artifacts directly with checked Expected propagation, so it is
// represented explicitly (emit == nullptr, driverSerialized == true) rather
// than as a callable emitter that only aborts.
#define NEUTRINO_TARGET_DRIVER(Name, Gated, ScenarioFree)                      \
  {Name, nullptr, Gated, ScenarioFree, /*driverSerialized=*/true},
#include "Neutrino/TargetRegistry.def"
#undef NEUTRINO_TARGET
#undef NEUTRINO_TARGET_DRIVER
  };
  return kTargets;
}

const TargetSpec *findTarget(const std::string &name) {
  for (const auto &t : targetRegistry())
    if (t.name == name)
      return &t;
  return nullptr;
}

std::string targetUsageList() {
  const auto &targets = targetRegistry();
  std::string out;
  for (size_t i = 0; i < targets.size(); ++i) {
    if (i)
      out += (i + 1 == targets.size()) ? ", or " : ", ";
    out += "'" + targets[i].name + "'";
  }
  return out;
}

} // namespace neutrino
