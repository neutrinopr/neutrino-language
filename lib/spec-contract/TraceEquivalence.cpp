//===- TraceEquivalence.cpp - normalized observable-trace comparison ------===//
//
// The semantic-agreement comparator the differential harness runs: each
// realization is projected to an ObservedTrace and compareTraces reports the
// first divergence. It compares observable MEANING (outcome, computed values,
// event choreography, net ledger, terminal, replay set), never artifact bytes —
// source equality is not a semantic proof. applyTamper proves the comparison is
// non-vacuous by breaking one defect-class at a time.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/TraceEquivalence.h"

#include "llvm/Support/JSON.h"

#include <utility>

using namespace llvm;

namespace neutrino {

ObservedTrace observedFromTransition(const TransitionResult &result) {
  ObservedTrace o;
  // Progress and Terminal both commit observable movement; NoProgress and
  // Replayed are non-committing no-ops. (Backends see a commit vs replay vs
  // refusal; the temporal Progress/Terminal split is a reference-side detail.)
  o.outcome = (result.outcome == Outcome::Terminal ||
               result.outcome == Outcome::Progress)
                  ? "committed"
              : (result.outcome == Outcome::Replayed ||
                 result.outcome == Outcome::NoProgress)
                  ? "replayed"
                  : "refused";
  o.refusalCode = result.refusalCode;
  // The coordination's terminal (the per-key statuses are all its one success
  // terminal); "" while still open.
  o.terminal = result.next.keyStatus.empty()
                   ? std::string()
                   : result.next.keyStatus.begin()->second;
  o.postedKeys = result.next.postedKeys;

  // Net the per-(ledger,party,currency) balances by ledger name — the
  // observable net movement a backend also reconciles to.
  for (const auto &kv : result.next.balances)
    o.ledger[kv.first.ledger] += kv.second;

  // Computed values + ordered events come from the trace observations.
  for (const json::Value &v : result.trace) {
    const json::Object *obs = v.getAsObject();
    if (!obs)
      continue;
    StringRef kind = obs->getString("kind").value_or("");
    if (kind == "compute")
      o.computed[obs->getString("name").value_or("").str()] =
          obs->getInteger("value").value_or(0);
    else if (kind == "event")
      o.events.push_back(obs->getString("name").value_or("").str());
  }
  return o;
}

bool parseTamperKind(StringRef token, TamperKind &out) {
  if (token == "drop_effect")
    out = TamperKind::DropEffect;
  else if (token == "alter_amount")
    out = TamperKind::AlterAmount;
  else if (token == "reorder_obs")
    out = TamperKind::ReorderObs;
  else if (token == "wrong_terminal")
    out = TamperKind::WrongTerminal;
  else if (token == "replay_omission")
    out = TamperKind::ReplayOmission;
  else if (token == "partial_commit")
    out = TamperKind::PartialCommit;
  else if (token == "alter_computed")
    out = TamperKind::AlterComputed;
  else if (token == "alter_outcome")
    out = TamperKind::AlterOutcome;
  else
    return false;
  return true;
}

void applyTamper(ObservedTrace &t, TamperKind kind) {
  switch (kind) {
  case TamperKind::DropEffect:
    if (!t.events.empty())
      t.events.pop_back();
    break;
  case TamperKind::AlterAmount:
    if (!t.ledger.empty())
      t.ledger.begin()->second += 1; // off-by-one on a net
    break;
  case TamperKind::ReorderObs:
    if (t.events.size() >= 2)
      std::swap(t.events[0], t.events[1]);
    break;
  case TamperKind::WrongTerminal:
    t.terminal += "_TAMPERED";
    break;
  case TamperKind::ReplayOmission:
    if (!t.postedKeys.empty())
      t.postedKeys.erase(t.postedKeys.begin());
    break;
  case TamperKind::PartialCommit:
    if (!t.ledger.empty())
      t.ledger.erase(t.ledger.begin()); // a leg's movement never committed
    break;
  case TamperKind::AlterComputed:
    if (!t.computed.empty())
      t.computed.begin()->second += 1; // a miscomputed derived value
    break;
  case TamperKind::AlterOutcome:
    t.outcome = t.outcome == "committed" ? "replayed" : "committed";
    break;
  }
}

namespace {
TraceDivergence diverge(std::string field, std::string locator,
                        std::string expected, std::string actual) {
  return {true, std::move(field), std::move(locator), std::move(expected),
          std::move(actual)};
}
} // namespace

TraceDivergence compareTraces(const ObservedTrace &reference,
                              const ObservedTrace &candidate) {
  if (reference.outcome != candidate.outcome)
    return diverge("outcome", "", reference.outcome, candidate.outcome);
  if (reference.refusalCode != candidate.refusalCode)
    return diverge("refusalCode", "", reference.refusalCode,
                   candidate.refusalCode);

  // Computed values (by name; a missing name is a divergence).
  for (const auto &kv : reference.computed) {
    auto it = candidate.computed.find(kv.first);
    if (it == candidate.computed.end())
      return diverge("computed", kv.first, std::to_string(kv.second),
                     "<absent>");
    if (it->second != kv.second)
      return diverge("computed", kv.first, std::to_string(kv.second),
                     std::to_string(it->second));
  }
  for (const auto &kv : candidate.computed)
    if (!reference.computed.count(kv.first))
      return diverge("computed", kv.first, "<absent>",
                     std::to_string(kv.second));

  // Events — order is load-bearing.
  if (reference.events.size() != candidate.events.size())
    return diverge("events", "count", std::to_string(reference.events.size()),
                   std::to_string(candidate.events.size()));
  for (size_t i = 0; i < reference.events.size(); ++i)
    if (reference.events[i] != candidate.events[i])
      return diverge("events", std::to_string(i), reference.events[i],
                     candidate.events[i]);

  // Net ledger movement (by ledger name; a missing/extra ledger diverges).
  for (const auto &kv : reference.ledger) {
    auto it = candidate.ledger.find(kv.first);
    if (it == candidate.ledger.end())
      return diverge("ledger", kv.first, std::to_string(kv.second), "<absent>");
    if (it->second != kv.second)
      return diverge("ledger", kv.first, std::to_string(kv.second),
                     std::to_string(it->second));
  }
  for (const auto &kv : candidate.ledger)
    if (!reference.ledger.count(kv.first))
      return diverge("ledger", kv.first, "<absent>", std::to_string(kv.second));

  if (reference.terminal != candidate.terminal)
    return diverge("terminal", "", reference.terminal, candidate.terminal);

  if (reference.postedKeys != candidate.postedKeys) {
    // Report the first key present in one but not the other.
    for (const std::string &k : reference.postedKeys)
      if (!candidate.postedKeys.count(k))
        return diverge("postedKeys", k, "present", "<absent>");
    for (const std::string &k : candidate.postedKeys)
      if (!reference.postedKeys.count(k))
        return diverge("postedKeys", k, "<absent>", "present");
  }

  return {}; // observable agreement
}

} // namespace neutrino
