#ifndef NEUTRINO_LIFECYCLE_H
#define NEUTRINO_LIFECYCLE_H

// The lifecycle CONTRACT leaf (, ): the model + its spec-JSON
// reconstruction, View.h-free so it belongs in NeutrinoSpecContract. The
// ProcedureView adapter `lifecycleModel(const ProcedureView&)` lives in
// Neutrino/LifecycleView.h (an above-leaf adapter TU), so a consumer of the
// contract does not pull in View.h/ProcedureView.
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// The canonical coordination lifecycle machine (M5 WP3, ). This is the ONE
// definition of the OPEN..CLOSE state machine — states, transitions, effects,
// terminals, instance key — that both the capability spec
// (GenSpec.lifecycleObj) and the slot artifacts (GenSlot) project from. Before
// WP3 the spec modeled the machine while GenSlot re-invented its operation
// vocabulary and compensation semantics by hand; now the machine lives here in
// the kernel and each renderer SERIALIZES it, so a slot artifact cannot drift
// from the spec's lifecycle.
//
// Today the machine is fixed (the DSL has no author-defined states); a `view`
// only parameterizes the instance-key fields. When author-defined machines
// arrive (the reserved kernel.state.* rules, ), this is where they land.
struct LifecycleState {
  std::string name;
  bool terminal;
  std::string terminalKind; // "success" | "aborted" | "" (non-terminal)
};

struct LifecycleTransition {
  std::string name;                 // the operation name (OPEN, COMMIT, ...)
  std::string from, to;             // state names
  std::vector<std::string> effects; // e.g. {"post"}, {"compensate"}
  std::string idempotency = "reject"; // "reject" | "noop_on_identical"
};

struct LifecycleModel {
  std::vector<std::string> instanceKeyFields; // the workflow/idempotency key
  std::string initialState;
  std::vector<LifecycleState> states;
  std::vector<LifecycleTransition> transitions; // canonical order
  std::string successState;                     // terminalStates.success
  std::string abortedState;                     // terminalStates.aborted
  std::string contestedState; // terminalStates.contested ("" = none). Used by
                              // the oracle quorum machine (S3, ) for the
                              // `escalate` timeout fallback; "" for every other
                              // shape, so the terminal set is unchanged.

  // The operation vocabulary: transition names, de-duplicated, in
  // first-appearance order (CLOSE appears once though it has two transitions).
  // This is the set a slot artifact advertises and iterates — derived, never
  // hand-listed.
  std::vector<std::string> operationNames() const;

  // Operation names whose transition carries `effect` (e.g. "post" -> the
  // value-committing op; "compensate" -> the compensating op).
  std::vector<std::string> operationsWithEffect(llvm::StringRef effect) const;

  // The protocol predecessor of `op`: the unique operation that produces the
  // single from-state `op` departs from, or "" when `op` starts from the
  // initial state or has more than one from-state (an entry op, or a
  // multi-source exit like CLOSE which is reachable from several states).
  // Derived from the transition graph, so the slot's operation ordering can't
  // drift from the machine (M5 WP3, ).
  std::string requiresPrior(llvm::StringRef op) const;
};

// Reconstruct the canonical machine from the frozen capability-spec's
// `lifecycle` section (the same machine `lifecycleModel(view)` produced, now
// round-tripped through the spec JSON) — so a spec-JSON renderer (GenSlotSpec,
// ) projects the slot lifecycle without a ProcedureView. Reads
// `lifecycle.instanceKey.fields`, `initialState`, `states[]`, `transitions[]`
// (name/from/to/effects) and `terminalStates.{success,aborted}`.
LifecycleModel lifecycleModelFromSpec(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_LIFECYCLE_H
