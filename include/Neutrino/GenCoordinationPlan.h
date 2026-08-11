#ifndef NEUTRINO_GENCOORDINATIONPLAN_H
#define NEUTRINO_GENCOORDINATIONPLAN_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// The canonical sem(plan) projection used by the curated same-waist witness.
// It consumes only the verified CoordinationPlan, preserves typed operands,
// policy/topology edges, replay, balance, and lifecycle obligations, and
// replaces source/display identities with structural labels.
llvm::Expected<llvm::json::Value>
canonicalPlanSemantics(const CoordinationPlan &coordinationPlan);

// Deterministic JSON serialization of a normalized plan (shared by the target's
// from-MLIR path and neutrino-gen's --from-spec reconstruction path).
llvm::Expected<std::string>
coordinationPlanToText(const CoordinationPlan &coordinationPlan);

// Deterministic JSON serialization of the COMPLETE backend projection graph
// of a `CoordinationPlan` — nodes (per §2 family) + typed edges (§3). Shared
// by the from-MLIR and --from-spec paths; invariant under the waist round-trip
// (Property P1). Emitted as backend-projection.json alongside the plan.
llvm::Expected<std::string>
backendProjectionToText(const CoordinationPlan &coordinationPlan);

// The `coordination-plan` target () is DRIVER-SERIALIZED ():
// neutrino-gen writes coordination-plan.json + backend-projection.json
// directly, via CHECKED `Expected` propagation of `coordinationPlanToText` +
// `backendProjectionToText` (both declared above), so a serialization/legality
// failure fails closed with a stable diagnostic and leaves no partial artifact.
// It therefore registers NO emit function (TargetRegistry.def uses
// NEUTRINO_TARGET_DRIVER; the TargetSpec's `emit` is nullptr and
// `driverSerialized` is true) — there is no publicly- callable
// `emitCoordinationPlan`. The artifact is built from the SAME frozen
// capability-spec through the SAME planFromSpec normalization the renderers
// use, so it is exactly what the backends see. Scenario-free + non-gated, like
// capability-spec.

} // namespace neutrino

#endif // NEUTRINO_GENCOORDINATIONPLAN_H
