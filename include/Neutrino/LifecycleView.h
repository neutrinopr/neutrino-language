#ifndef NEUTRINO_LIFECYCLEVIEW_H
#define NEUTRINO_LIFECYCLEVIEW_H

// The ProcedureView adapter for the lifecycle contract (). Kept ABOVE the
// NeutrinoSpecContract leaf (in NeutrinoAnalysis) because it depends on
// View.h/ProcedureView, so the contract leaf (Neutrino/Lifecycle.h) stays
// View.h-free. The capability-spec producer (GenSpec) uses this to build the
// machine from a ProcedureView; the spec-JSON renderers use
// lifecycleModelFromSpec (in the leaf).
#include "Neutrino/Lifecycle.h"
#include "Neutrino/View.h"

namespace neutrino {

// Build the canonical machine for `view` (the instance key comes from the
// view's entry idempotency keys; the rest is the fixed machine today).
LifecycleModel lifecycleModel(const ProcedureView &view);

} // namespace neutrino

#endif // NEUTRINO_LIFECYCLEVIEW_H
