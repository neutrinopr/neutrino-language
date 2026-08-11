//===- BoundedCoordinator.cpp - bounded dynamic realization () --------===//
//
// The shared bounded coordinator's executable semantics for the S5
// falsification experiment. It reuses the  reference evaluator for the
// per-transition meaning (so an instance's observable trace equals the
// reference by construction) and adds the dynamic-realization obligations:
// admission (reject an out-of-subset coordinationPlan before any mutation),
// statically-derived step + storage bounds enforced at runtime, and
// cross-instance isolation (each instance advances its OWN state only). Not a
// production coordinator.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/BoundedCoordinator.h"

#include "llvm/Support/JSON.h"

using namespace llvm;

namespace neutrino {

namespace {
Error admitError(const Twine &msg) {
  return createStringError(inconvertibleErrorCode(),
                           "bounded admission: " + msg);
}
} // namespace

Expected<BoundedBounds> admitBounded(const CoordinationPlan &coordinationPlan) {
  // Only the supported ledger-effect kinds — an unsupported instruction is
  // refused here, before any instance state is touched.
  for (const PlanEffect &e : coordinationPlan.effects)
    if (e.kind != "debit" && e.kind != "credit")
      return admitError("unsupported effect kind '" + e.kind + "'");

  // Size caps: an oversized / unbounded coordinationPlan is refused before
  // dispatch.
  if ((int)coordinationPlan.effects.size() > kBoundedMaxEffects)
    return admitError("coordinationPlan exceeds the bounded effect cap");
  if ((int)coordinationPlan.computes.size() > kBoundedMaxComputes)
    return admitError("coordinationPlan exceeds the bounded compute cap");
  if ((int)coordinationPlan.attestations.size() > kBoundedMaxAttestations)
    return admitError("coordinationPlan exceeds the bounded attestation cap");
  if (coordinationPlan.terminal.success.empty())
    return admitError("coordinationPlan has no success terminal");

  // Statically derive the resource bounds. A transition emits: authorization +
  // the per-procedure reconciled event + terminal (3), one compute observation
  // each, and up to guard + attestation + ledger-delta + event (4) per effect.
  // One instance persists: status + the posted key + a net slot per effect leg.
  BoundedBounds b;
  b.maxSteps = 3 + (int)coordinationPlan.computes.size() +
               4 * (int)coordinationPlan.effects.size();
  b.maxStorageSlots = 2 + 2 * (int)coordinationPlan.effects.size();
  if (b.maxSteps > kBoundedMaxSteps)
    return admitError("derived step bound exceeds the coordinator cap");
  if (b.maxStorageSlots > kBoundedMaxStorageSlots)
    return admitError("derived storage bound exceeds the coordinator cap");
  return b;
}

Expected<SharedCoordinator>
SharedCoordinator::create(const CoordinationPlan &coordinationPlan) {
  Expected<BoundedBounds> bounds = admitBounded(coordinationPlan);
  if (!bounds)
    return bounds.takeError();
  return SharedCoordinator(coordinationPlan, *bounds);
}

SharedCoordinator::SharedCoordinator(const CoordinationPlan &coordinationPlan,
                                     BoundedBounds bounds)
    : coordinationPlan_(coordinationPlan), bounds_(bounds) {}

TransitionResult SharedCoordinator::run(StringRef instanceId,
                                        const TransitionInput &input) {
  // ISOLATION: run against ONLY this instance's state (created empty if new); a
  // transition here can neither read nor mutate any other instance.
  EvalState &state = instances_[instanceId.str()];
  TransitionResult r = evaluateTransition(coordinationPlan_, state, input);

  // Runtime BOUNDS enforcement: a step or storage overrun refuses and rolls
  // back (the committed r.next is discarded, the instance state is unchanged).
  int slots = (int)r.next.balances.size() + (int)r.next.postedKeys.size() +
              (int)r.next.keyStatus.size();
  if ((int)r.trace.size() > bounds_.maxSteps ||
      slots > bounds_.maxStorageSlots) {
    TransitionResult refused;
    refused.outcome = Outcome::Refused;
    refused.refusalCode = (int)r.trace.size() > bounds_.maxSteps
                              ? "bounds.step_exceeded"
                              : "bounds.storage_exceeded";
    refused.next = state; // unchanged
    json::Object o;
    o["kind"] = "refusal";
    o["code"] = refused.refusalCode;
    refused.trace.push_back(std::move(o));
    return refused;
  }

  // Commit: only this instance advances.
  state = r.next;
  return r;
}

const EvalState *SharedCoordinator::stateOf(StringRef instanceId) const {
  auto it = instances_.find(instanceId.str());
  return it == instances_.end() ? nullptr : &it->second;
}

int SharedCoordinator::instanceCount() const { return (int)instances_.size(); }

} // namespace neutrino
