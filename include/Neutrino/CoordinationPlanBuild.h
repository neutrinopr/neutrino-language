#ifndef NEUTRINO_COORDINATION_PLAN_BUILD_H
#define NEUTRINO_COORDINATION_PLAN_BUILD_H

// The direct producer of the CoordinationPlan from verified MLIR (). Kept
// ABOVE the NeutrinoSpecContract leaf (in NeutrinoAnalysis) because it depends
// on View.h/ProcedureView — so the plan CONTRACT + planFromSpec stay
// View.h-free in the leaf while the from-MLIR normalization lives here, next to
// viewOf and lifecycleModel. This is the analysis the issue asks for:
// capability-spec's normalized decisions and the renderers both consume the
// plan built here; planFromSpec (leaf) is the identical-contract reconstruction
// from an external spec.

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/View.h"

namespace neutrino {

// Normalize + VERIFY the plan directly from a procedure's verified MLIR view.
// Byte-for-byte identical to planFromSpec on the same procedure's capability-
// spec (both hand raw inputs to the one assemblePlan seam).
llvm::Expected<CoordinationPlan> normalizePlan(const ProcedureView &view);

} // namespace neutrino

#endif // NEUTRINO_COORDINATION_PLAN_BUILD_H
