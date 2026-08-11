#ifndef NEUTRINO_BOUNDED_COORDINATOR_H
#define NEUTRINO_BOUNDED_COORDINATOR_H

#include "Neutrino/CoordinationEval.h"
#include "Neutrino/CoordinationPlan.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <map>
#include <string>

namespace neutrino {

// The bounded dynamic-realization coordinator ( S5 falsification
// experiment). A SHARED coordinator hosts MANY coordination instances in one
// deployment; each is an ADMITTED coordination in a deliberately small bounded
// subset, run per-instance with ISOLATED state. It reuses the  reference
// evaluator for the transition SEMANTICS — so an instance's observable trace is
// equivalent to the reference by construction (and proven by S4
// trace-equivalence) — and adds the dynamic-realization obligations the
// experiment falsifies:
//   - ADMISSION: reject a coordinationPlan outside the bounded subset BEFORE
//   any state
//     mutation (the on-chain admit() analogue);
//   - static step + storage BOUNDS, enforced at runtime;
//   - cross-instance ISOLATION (a transition on instance A can neither read nor
//     mutate instance B).
// This is the executable model whose obligations the shared Solidity
// coordinator realizes; it is NOT a production coordinator (no
// upgrade/registry/runtime).

// Hard caps of the bounded coordinator's supported subset. A coordinationPlan
// whose derived bounds exceed a cap is refused at admission.
inline constexpr int kBoundedMaxEffects = 4;
inline constexpr int kBoundedMaxComputes = 4;
inline constexpr int kBoundedMaxAttestations = 1;
inline constexpr int kBoundedMaxSteps = 32; // trace observations / transition
inline constexpr int kBoundedMaxStorageSlots =
    16; // persistent slots / instance

// The statically-derived resource bounds of an admitted coordination.
struct BoundedBounds {
  int maxSteps = 0; // upper bound on observations one transition emits
  int maxStorageSlots =
      0; // upper bound on persistent slots one instance writes
};

// Admission: validate `coordinationPlan` is in the closed bounded subset and
// derive its static bounds. Fails closed (Error) — BEFORE any state mutation —
// on an unsupported effect kind, an oversized/unbounded coordinationPlan (more
// effects / computes / attestations than the caps, or derived bounds over the
// caps), or a coordinationPlan with no success terminal. Pure; the on-chain
// admit() mirrors these checks.
llvm::Expected<BoundedBounds>
admitBounded(const CoordinationPlan &coordinationPlan);

// A shared coordinator hosting instances of ONE admitted coordination. Each
// instance id names a distinct co-hosted coordination invocation with its own
// isolated persistent state.
class SharedCoordinator {
public:
  // Admit `coordinationPlan` (fails closed if out of subset) and host instances
  // of it. The coordinationPlan must outlive the coordinator (held by reference
  // — the semantics live in the coordinationPlan, not copied).
  static llvm::Expected<SharedCoordinator>
  create(const CoordinationPlan &coordinationPlan);

  // Construct with EXPLICIT bounds (test seam): lets an adversarial test set
  // bounds below what the coordinationPlan needs to prove runtime enforcement
  // bites.
  SharedCoordinator(const CoordinationPlan &coordinationPlan,
                    BoundedBounds bounds);

  // Run one instance's transition, using ONLY that instance's state. Refuses
  // (rolling back, state unchanged) on a step/storage-bound overrun
  // ("bounds.step_exceeded" / "bounds.storage_exceeded"); otherwise commits the
  // instance's next state and returns the reference-equivalent result.
  TransitionResult run(llvm::StringRef instanceId,
                       const TransitionInput &input);

  // The isolated state of an instance (null if it has never committed).
  const EvalState *stateOf(llvm::StringRef instanceId) const;
  int instanceCount() const;
  const BoundedBounds &bounds() const { return bounds_; }

private:
  const CoordinationPlan &coordinationPlan_;
  BoundedBounds bounds_;
  std::map<std::string, EvalState> instances_; // per-instance isolated storage
};

} // namespace neutrino

#endif // NEUTRINO_BOUNDED_COORDINATOR_H
