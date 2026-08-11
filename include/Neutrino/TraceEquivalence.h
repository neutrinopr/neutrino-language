#ifndef NEUTRINO_TRACE_EQUIVALENCE_H
#define NEUTRINO_TRACE_EQUIVALENCE_H

// Normalized trace-equivalence: the observable projection of a realization that
// is compared, in a canonical form, against the deterministic reference
// evaluator's trace (CoordinationEval). Each realization — the reference oracle
// itself, or a rigid lowering's fold — is normalized to an ObservedTrace, and
// compareTraces reports the FIRST divergence with coordinates. This is the
// semantic-agreement check the differential harness (neutrino-equiv) runs; it
// is deliberately NOT a byte diff of artifacts (source equality is not semantic
// proof) — it compares observable meaning: outcome, computed values, the
// ordered event choreography, net ledger movement, the terminal, and the replay
// set.
//
// applyTamper deliberately breaks an ObservedTrace one defect-class at a time
// so the comparison's sensitivity is proven non-vacuous: a dropped effect, an
// altered amount, reordered observations, a wrong terminal, a replay omission,
// a partial commit, an altered derived value, or a changed outcome must each
// surface as a divergence.

#include "Neutrino/CoordinationEval.h"

#include "llvm/ADT/StringRef.h"

#include <map>
#include <set>
#include <string>
#include <vector>

namespace neutrino {

// The observable projection every realization can produce, in canonical form.
struct ObservedTrace {
  std::string outcome; // "committed" | "replayed" | "refused"
  std::map<std::string, long long> computed; // compute name -> value
  std::vector<std::string> events;           // ordered choreography event names
  std::map<std::string, long long> ledger;   // ledger name -> net minor units
  std::string terminal;             // the reached terminal state ("" if none)
  std::set<std::string> postedKeys; // the replay/idempotency set
  std::string refusalCode;          // "" unless outcome == refused
};

// Project the reference evaluator's transition result to an ObservedTrace: the
// computed values + ordered events from the trace, the net ledger by ledger
// name (summing the per-account deltas), and the outcome/terminal/replay state.
ObservedTrace observedFromTransition(const TransitionResult &result);

// The classes of tamper the equivalence check must detect (each maps to a
// deliberate ObservedTrace mutation for the non-vacuous self-test). Together
// they exercise every field compareTraces compares, so no compared field is
// trusted without a negative that proves its check bites.
enum class TamperKind {
  DropEffect,     // remove an event + its ledger contribution
  AlterAmount,    // change a ledger net
  ReorderObs,     // swap two events (order is load-bearing)
  WrongTerminal,  // change the terminal state
  ReplayOmission, // drop a posted key
  PartialCommit,  // drop a ledger entry (some, not all, movement committed)
  AlterComputed,  // change a derived value (launder-via-derived-value vector)
  AlterOutcome,   // change the outcome (e.g. committed -> replayed)
};

// Parse a tamper kind from its stable CLI token ("drop_effect", "alter_amount",
// "reorder_obs", "wrong_terminal", "replay_omission", "partial_commit",
// "alter_computed", "alter_outcome"). Returns false into `out` unset for an
// unknown token (the caller fails closed).
bool parseTamperKind(llvm::StringRef token, TamperKind &out);

// Deliberately break `t` per `kind` (a no-op only when `t` has nothing of that
// class to break — the caller treats that as a self-test failure, since the
// tamper could not be exercised).
void applyTamper(ObservedTrace &t, TamperKind kind);

// One divergence between two ObservedTraces, with coordinates.
struct TraceDivergence {
  bool diverged = false;
  std::string field; // "outcome" | "computed" | "events" | "ledger" | ...
  std::string
      locator; // the compute/event/ledger name or index at the divergence
  std::string expected; // reference value
  std::string actual;   // candidate value
};

// Compare a candidate ObservedTrace against the reference, returning the FIRST
// divergence (deterministic field order). `diverged == false` means observable
// agreement.
TraceDivergence compareTraces(const ObservedTrace &reference,
                              const ObservedTrace &candidate);

} // namespace neutrino

#endif // NEUTRINO_TRACE_EQUIVALENCE_H
