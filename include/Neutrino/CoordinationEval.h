#ifndef NEUTRINO_COORDINATION_EVAL_H
#define NEUTRINO_COORDINATION_EVAL_H

// The ONE deterministic reference evaluator (): the semantic oracle every
// realization is checked against. It runs OVER the target-neutral
// CoordinationPlan () — so the .neu, direct-MLIR, and spec-reconstruction
// paths, which all normalize to the same coordination plan, reach the same
// result — and produces a normalized, ordered observation trace plus the next
// semantic state. It is TOTAL over the closed vocabulary: every supported node
// either produces observations or an explicit, coded refusal (no value is
// silently reinterpreted), and the evaluator NEVER mutates state partially —
// all validation, including balance-overflow checking, precedes a single
// commit, so a refused transition leaves the input state byte-for-byte
// unchanged.
//
// The state modeled here is the SEMANTIC coordination state — the per-account
// ledger balances, the replay/idempotency guard, and the coordination's own
// lifecycle status — NOT the network-owned session/transcript lifecycle (see
// docs/spec/COORDINATION_EVALUATOR.md). Time and external attestations are
// EXPLICIT transition inputs: the evaluator never reads an ambient clock nor
// admits on its own.

#include "Neutrino/CoordinationPlan.h"
#include "llvm/Support/JSON.h"

#include <map>
#include <set>
#include <string>
#include <tuple>

namespace neutrino {

// A posting identity: value moves are netted per (ledger, party, currency), not
// per ledger alone, so two effects against the same ledger for different
// parties (or currencies) stay distinct balances.
struct Account {
  std::string ledger;
  std::string party;
  std::string currency;
  bool operator<(const Account &o) const {
    return std::tie(ledger, party, currency) <
           std::tie(o.ledger, o.party, o.currency);
  }
};

// The observable semantic state a coordination transitions FROM / TO.
struct EvalState {
  // Per-account net balance in integer minor units (absent == 0).
  std::map<Account, long long> balances;
  // The workflow-key VALUES already committed — the idempotency guard. A
  // transition whose resolved key is in here is a replay.
  std::set<std::string> postedKeys;
  // The canonical execution claim () established for each seen workflow
  // key: key VALUE -> executionClaimHash of its FIRST invocation's input
  // payload. Inputs are immutable per key — a later invocation on the same key
  // that presents a different payload does not match this claim and is refused,
  // so one coordination instance can never combine two different payloads.
  std::map<std::string, std::string> keyClaim;
  // The TEMPORAL commit ledger (): for a coordination with per-policy
  // accepted() groups, state is keyed by (workflow key, effect group). Each
  // group's balanced legs post AT MOST ONCE per key — key VALUE -> the set of
  // committed group ids (a group's structural guardKey). A group whose quorum
  // has not yet accepted stays PENDING and commits on a later transition; the
  // coordination reaches its terminal only once every required group commits.
  std::map<std::string, std::set<std::string>> committedGroups;
  // The coordination lifecycle status PER KEY: key VALUE -> its terminal status
  // (a key absent here is open/initial). A key reaches a terminal
  // (success/aborted/contested) it cannot transition out of once every required
  // group has committed — so a terminal K1 never makes a still-open K2 look
  // terminal (per-key isolation). Distinct from the network session lifecycle.
  std::map<std::string, std::string> keyStatus;
};

// One realization's transition input: the concrete invocation. All of time,
// attestation decisions, and the authorization decision are explicit inputs.
struct TransitionInput {
  // Numeric input name -> integer minor units (time inputs live here too, as
  // ordinary numeric inputs a guard may compare against).
  std::map<std::string, long long> numeric;
  // Symbolic input name -> its token (party / currency / idempotency key /
  // string). The workflow key, party, and currency operands resolve through
  // here.
  std::map<std::string, std::string> symbols;
  // Attestation policy input -> accepted? An effect gated on a policy absent
  // here (or mapped false) is treated as NOT accepted.
  std::map<std::string, bool> attestations;
  // The topology authorization decision for this invocation (explicit — the
  // network owns real admission; the evaluator only records the given verdict).
  bool authorized = true;
};

// The disposition of a transition, an EXPLICIT contract the downstream
// legalizers consume (they must not infer it from the trace):
//   Progress   — at least one effect group committed, but a required group is
//                still pending, so the key is NOT yet terminal.
//   Terminal   — a commit that completed the LAST required group (or the
//                single-shot commit of a non-temporal coordination): the key is
//                now terminal.
//   NoProgress — a valid transition that committed nothing new while the key is
//                still open (a pending group awaits its quorum).
//   Replayed   — an idempotent no-op on an already-terminal key.
//   Refused    — an explicit, coded refusal before any mutation.
// Progress and Terminal both advance the state; the other three leave it
// unchanged.
enum class Outcome { Progress, Terminal, NoProgress, Replayed, Refused };

struct TransitionResult {
  Outcome outcome = Outcome::Refused;
  // The ordered observation trace: each element is a sorted-key JSON object
  // with a "kind" and its kind-specific fields. Order is load-bearing (a
  // reordered / dropped / duplicated ledger delta changes the trace).
  llvm::json::Array trace;
  // The state AFTER the transition (== the input state unless Committed).
  EvalState next;
  // The refusal code when outcome == Refused ("" otherwise) — a convenience
  // mirror of the trailing refusal observation for callers/tests.
  std::string refusalCode;
};

// Evaluate one transition. Deterministic: same (coordinationPlan, state, input)
// yields a byte-identical trace and next state.
TransitionResult evaluateTransition(const CoordinationPlan &coordinationPlan,
                                    const EvalState &state,
                                    const TransitionInput &input);

// Deterministic 2-space pretty JSON (sorted keys) of {outcome, trace,
// nextState} — the FileCheck / diff surface for the coordination-trace target.
std::string transitionToText(const TransitionResult &result);

} // namespace neutrino

#endif // NEUTRINO_COORDINATION_EVAL_H
