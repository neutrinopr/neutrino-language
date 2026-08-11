//===- CoordinationEval.cpp - the one deterministic reference evaluator ---===//
//
// evaluateTransition () is the semantic oracle: it interprets a normalized
// CoordinationPlan () against an explicit state + transition input and
// yields an ordered observation trace + next state. It is TOTAL over the closed
// vocabulary (every unsupported kind / malformed operand / overflow is a coded
// refusal, never a silent reinterpretation) and ATOMIC — all validation,
// including the balance-overflow check on a STAGED copy, precedes the single
// commit, so a refused / replayed transition returns the input state unchanged.
// Determinism comes from ordered iteration (coordination-plan effect order, the
// std::map/std::set sort in the state) and the sorted-key JSON printer.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationEval.h"

#include "Neutrino/CoordinationEnvelope.h"
#include "Neutrino/Expr.h"
#include "Neutrino/StrCase.h"
#include "Neutrino/ValueModel.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace neutrino {

namespace {

// A parsed operand identity "kind:value" (e.g. "ref:amount", "literal:100").
// `wellFormed` is false for anything that is not `ref:...` or `literal:...` —
// the evaluator refuses rather than guessing.
struct Operand {
  bool wellFormed = false;
  bool literal = false;
  std::string value;
};
Operand splitOperand(const std::string &id) {
  Operand op;
  auto pos = id.find(':');
  if (pos == std::string::npos)
    return op;
  std::string kind = id.substr(0, pos);
  if (kind != "ref" && kind != "literal")
    return op;
  op.wellFormed = true;
  op.literal = kind == "literal";
  op.value = id.substr(pos + 1);
  return op;
}

// Resolve a numeric (amount) operand to a non-negative minor-unit value.
// Returns a refusal code ("" on success). A ref must resolve in the env; a
// literal must be an in-range integer; money is non-negative by the value
// model.
std::string resolveAmount(const std::string &id,
                          const std::map<std::string, long long> &env,
                          long long &out) {
  Operand op = splitOperand(id);
  if (!op.wellFormed)
    return "operand.malformed";
  if (op.literal) {
    if (StringRef(op.value).getAsInteger(10, out))
      return "operand.malformed"; // non-integer or out of int64 range
  } else {
    auto it = env.find(op.value);
    if (it == env.end())
      return "operand.unresolved";
    out = it->second;
  }
  if (out < 0)
    return "amount.negative";
  return "";
}

// Resolve a symbolic (party / currency) operand to its token. Returns a refusal
// code ("" on success).
std::string resolveSymbol(const std::string &id,
                          const std::map<std::string, std::string> &symbols,
                          std::string &out) {
  Operand op = splitOperand(id);
  if (!op.wellFormed)
    return "operand.malformed";
  if (op.literal) {
    out = op.value;
  } else {
    auto it = symbols.find(op.value);
    if (it == symbols.end())
      return "operand.unresolved";
    out = it->second;
  }
  // An empty token (e.g. `literal:` or an input bound to "") is not a valid
  // posting-identity component — a balance under an empty account is refused.
  if (out.empty())
    return "operand.malformed";
  return "";
}

// The event label a backend emits for a firing leg — pascalCase(name) plus the
// posting suffix, matching eventChain's effect contribution so the trace's
// event projection lines up with the rendered choreography. The kind is
// validated to be exactly debit|credit before this is called.
std::string effectEvent(const PlanEffect &e) {
  return pascalCase(e.name) + (e.kind == "debit" ? "Debited" : "Credited");
}

json::Object obs(StringRef kind) { return json::Object{{"kind", kind}}; }

// True iff the guard is an accepted(<input>) quorum-acceptance predicate — a
// TEMPORAL group whose acceptance can land on a later transition. A comparison
// guard is deterministic on the (immutable) inputs, so it is not temporal.
bool isAcceptedGuard(const ExprNode &n) {
  return n.kind == ExprNode::Call && n.name == "accepted";
}

} // namespace

TransitionResult evaluateTransition(const CoordinationPlan &coordinationPlan,
                                    const EvalState &state,
                                    const TransitionInput &input) {
  TransitionResult r;
  r.next = state; // unchanged unless we reach the commit below

  auto refuse = [&](StringRef code, StringRef effect = "") -> TransitionResult {
    r.outcome = Outcome::Refused;
    r.refusalCode = code.str();
    json::Object o = obs("refusal");
    o["code"] = code;
    if (!effect.empty())
      o["effect"] = effect;
    r.trace.push_back(std::move(o));
    // A refusal is NOT a state transition: the state stays byte-for-byte
    // unchanged, so NO terminal observation is appended (the observations
    // produced before the fault remain), and the trace never claims a terminal
    // the state disagrees with — every `terminal` observation's state is a
    // recorded keyStatus by construction (see the invariant test).
    r.next = state; // ATOMIC: discard any staged work
    return std::move(r);
  };

  // 1. Authorization — an explicit input, recorded first.
  {
    json::Object o = obs("authorization");
    o["authorized"] = input.authorized;
    r.trace.push_back(std::move(o));
  }
  if (!input.authorized)
    return refuse("auth.denied");

  // 2. Resolve the workflow/idempotency key VALUE for this invocation.
  std::string keyVal;
  if (!coordinationPlan.workflowKey.empty()) {
    auto s = input.symbols.find(coordinationPlan.workflowKey);
    if (s != input.symbols.end())
      keyVal = s->second;
    else {
      auto n = input.numeric.find(coordinationPlan.workflowKey);
      if (n != input.numeric.end())
        keyVal = std::to_string(n->second);
    }
  }
  if (keyVal.empty())
    return refuse("key.unresolved");

  // 2b. The canonical execution claim (). Built from the DECLARED, TYPED
  // input inventory of the coordination (NOT the raw transition maps — so
  // undeclared extras never enter, and the value category is pinned for a rail
  // to reproduce), and scoped to the coordination identity so acceptance for
  // one coordination can never authorize another. Each declared input must be
  // present with a value in the map matching its category (a missing /
  // type-conflicting input is a refusal). Attestation verdicts are NOT payload
  // — a policy accepting later must not change the claim. Inputs are then
  // immutable per key: a later invocation on the same key presenting a
  // different payload does not match the claim established for that key and is
  // refused below.
  std::vector<ExecutionInput> typedInputs;
  for (const PlanInput &pi : coordinationPlan.inputs) {
    ValueCategory cat = classifyValueType(pi.type);
    auto ni = input.numeric.find(pi.name);
    auto si = input.symbols.find(pi.name);
    bool inNum = ni != input.numeric.end();
    bool inSym = si != input.symbols.end();
    // Exactly one representation: a name carried in BOTH maps is ambiguous (two
    // rails could resolve it differently) — refuse rather than pick.
    if (inNum && inSym)
      return refuse("claim.input", pi.name);
    std::string val;
    if (isNumericCategory(cat)) {
      // A governed numeric input must be carried numerically — absent or
      // symbolic-only is missing / type-conflicting.
      if (!inNum)
        return refuse("claim.input", pi.name);
      val = std::to_string(ni->second);
    } else if (isCanonicalCategory(cat)) {
      // A governed symbolic input (party/currency/evidence/string) must be
      // carried symbolically.
      if (!inSym)
        return refuse("claim.input", pi.name);
      val = si->second;
    } else if (inNum) {
      // Extension (non-governed, e.g. a timestamp): the one representation may
      // be either map.
      val = std::to_string(ni->second);
    } else if (inSym) {
      val = si->second;
    } else {
      return refuse("claim.input", pi.name);
    }
    typedInputs.push_back({pi.name, categoryName(cat).str(), val});
  }
  std::string claim = executionClaimHash(
      coordinationIdentityHash(coordinationPlan), keyVal, typedInputs);

  // Claim immutability (): any key already SEEN — partially committed
  // (temporal) or terminal — must present the SAME payload, so its established
  // claim must match. Established at the first commit; checked on every later
  // transition for that key.
  if (auto kc = state.keyClaim.find(keyVal);
      kc != state.keyClaim.end() && kc->second != claim)
    return refuse("claim.mismatch");

  // 3. Replay / idempotency — a re-post of an already-committed key is a
  // deterministic no-op that returns the coordination's EXISTING terminal (the
  // same operation, not a new invocation). A posted key always carries a
  // terminal status (commit sets both); a state that posted a key yet is still
  // open is inconsistent and is refused rather than fabricating a success
  // terminal that disagrees with the next status.
  if (coordinationPlan.replay.idempotent && state.postedKeys.count(keyVal)) {
    // Every posted key carries the claim established at its commit. A posted
    // key WITHOUT a recorded claim is an inconsistent state — refuse rather
    // than permit a replay of any payload (, fail closed).
    auto c = state.keyClaim.find(keyVal);
    if (c == state.keyClaim.end())
      return refuse("state.invalid");
    // A "replay" that presents a DIFFERENT payload than the claim established
    // for this key is not the same operation — it is an attempt to mutate the
    // committed instance. Refuse rather than silently no-op ().
    if (c->second != claim)
      return refuse("claim.mismatch");
    // A posted key must carry its terminal status; its absence is inconsistent.
    auto st = state.keyStatus.find(keyVal);
    if (st == state.keyStatus.end() || st->second.empty())
      return refuse("state.invalid");
    json::Object o = obs("replay");
    o["key"] = keyVal;
    r.trace.push_back(std::move(o));
    json::Object t = obs("terminal");
    t["state"] = st->second; // == this key's status (unchanged)
    r.trace.push_back(std::move(t));
    r.outcome = Outcome::Replayed;
    r.next = state; // unchanged
    return std::move(r);
  }

  // Temporal per-group commit (): a coordination whose effect groups
  // are gated by accepted() policies commits each group INDEPENDENTLY, once its
  // quorum accepts — so a partially-committed key stays OPEN (not terminal) and
  // a later transition can still post a pending group. A coordination WITHOUT
  // any accepted() group keeps the single-shot path below, unchanged.
  bool temporal = false;
  for (const PlanEffect &e : coordinationPlan.effects)
    if (e.guard && isAcceptedGuard(*e.guard)) {
      temporal = true;
      break;
    }

  // 4. Terminal status is PER KEY: a re-post of a terminal key is the replay
  // handled above, and a fresh key is a distinct instance not blocked by
  // another key's terminal (cross-key isolation). There is therefore no global
  // terminal-state gate.

  // 5. Fold computes in declared order into the numeric env (inputs first).
  std::map<std::string, long long> env = input.numeric;
  for (const PlanCompute &c : coordinationPlan.computes) {
    if (!c.expr)
      return refuse("expr.missing");
    long long val;
    try {
      val = evalExpr(*c.expr, env);
    } catch (const ExprError &e) {
      return refuse(e.code);
    }
    env[c.name] = val;
    json::Object o = obs("compute");
    o["name"] = c.name;
    o["value"] = val;
    r.trace.push_back(std::move(o));
  }

  // Seed quorum acceptance for accepted(x) `when` guards (): an effect's
  // guard reads "accepted:<x>" — accepted iff the policy input is present AND
  // true in the transition's attestation map. A false accepted() guard skips
  // its leg (a balanced no-op), so multiple policies each gate their own legs.
  // The
  // ":" prefix namespaces it away from any declared input.
  for (const AttestationPolicy &p : coordinationPlan.attestations) {
    auto a = input.attestations.find(p.input);
    env["accepted:" + p.input] =
        (a != input.attestations.end() && a->second) ? 1 : 0;
  }

  // Obligation observations (): a first-class undertaking is observed
  // eligible/fired/refused, DISTINCT from effect execution and WITHOUT any
  // backend knowledge — its eligibility is the SAME typed predicate the
  // coordination plan carries, evaluated over the SAME env; `fired` requires
  // eligibility AND that its authorized effects committed this transition.
  // Membership (not order) is sufficient HERE because assemblePlan already
  // rejected any obligation whose authorization order disagrees with the
  // executable coordination-plan order ( P1-4), so a committed authorized
  // set can only have posted in the authorized order. `committed` is the set of
  // effect names that posted (empty until commit).
  auto observeObligations = [&](const std::set<std::string> &committed) {
    for (const PlanObligation &o : coordinationPlan.obligations) {
      bool eligible = false;
      if (o.when) {
        try {
          eligible = evalGuard(*o.when, env);
        } catch (const ExprError &) {
          eligible = false;
        }
      }
      bool allFired = eligible;
      for (const std::string &en : o.effects)
        if (!committed.count(en))
          allFired = false;
      json::Object ob = obs("obligation");
      ob["name"] = o.name;
      ob["obligor"] = o.obligor;
      ob["eligible"] = eligible;
      ob["status"] = !eligible ? "refused" : (allFired ? "fired" : "eligible");
      r.trace.push_back(std::move(ob));
    }
  };

  // 5b. Evidence-only coordination: the transition IS the evidence-acceptance
  // action — no ledger effects. Each declared policy's evidence must be
  // presented (else malformed) and accepted (else rejected); on acceptance the
  // coordination commits with a zero-ledger acceptance event + success
  // terminal. Refusals leave state unchanged (clean rollback).
  if (coordinationPlan.effects.empty() &&
      !coordinationPlan.attestations.empty()) {
    for (const AttestationPolicy &p : coordinationPlan.attestations) {
      auto a = input.attestations.find(p.input);
      if (a == input.attestations.end())
        return refuse("evidence.malformed");
      json::Object o = obs("attestation");
      o["policy"] = p.input;
      o["accepted"] = a->second;
      r.trace.push_back(std::move(o));
      if (!a->second)
        return refuse("attestation.rejected");
    }
    json::Object ev = obs("event");
    ev["name"] = pascalCase(coordinationPlan.procedure) + "Accepted";
    r.trace.push_back(std::move(ev));
    json::Object t = obs("terminal");
    t["state"] = coordinationPlan.terminal.success;
    r.trace.push_back(std::move(t));
    r.next.postedKeys.insert(keyVal);
    r.next.keyClaim[keyVal] = claim;
    r.next.keyStatus[keyVal] = coordinationPlan.terminal.success;
    r.outcome = Outcome::Terminal;
    return std::move(r);
  }

  // 5c. TEMPORAL per-(key, group) commit (). Each effect group commits
  // AT MOST ONCE per key, and ONLY when its guard holds this transition (an
  // accepted() group's quorum has accepted; a comparison group's predicate is
  // true; an unconditional group always). A group whose accepted() quorum has
  // not landed stays PENDING and commits on a later transition. The
  // coordination reaches its success terminal only once every REQUIRED group
  // has committed; until then it is open. A transition that commits nothing new
  // is an explicit no-op (NoProgress), distinct from a replay of a fully
  // terminal key.
  if (temporal) {
    std::set<std::string> empty;
    const std::set<std::string> &committedSoFar =
        state.committedGroups.count(keyVal) ? state.committedGroups.at(keyVal)
                                            : empty;

    // Validate the reconstructed partial ledger BEFORE interpreting it (fail
    // closed): a key with committed groups MUST carry its established claim
    // (the claim-immutability check above only covers keys that have one), and
    // every committed group id must be a real group of THIS coordination.
    // Otherwise an externally-supplied state could splice an already-posted
    // group onto a different payload.
    if (!committedSoFar.empty()) {
      if (!state.keyClaim.count(keyVal))
        return refuse("state.invalid");
      std::set<std::string> known;
      for (const PlanEffectGroup &g : coordinationPlan.effectGroups)
        known.insert(g.guardKey);
      for (const std::string &gid : committedSoFar)
        if (!known.count(gid))
          return refuse("state.invalid");
    }

    // Classify each group: does its guard hold now, is it committable, and is
    // it REQUIRED for the terminal? A group's guard AST is shared by its
    // effects.
    struct GroupInfo {
      const PlanEffectGroup *g;
      bool holds;
      bool committable;
    };
    std::vector<GroupInfo> groups;
    std::set<std::string> required;
    for (const PlanEffectGroup &g : coordinationPlan.effectGroups) {
      const ExprNode *guard =
          coordinationPlan.effects[g.firstIndex].guard.get();
      bool isAccepted = guard && isAcceptedGuard(*guard);
      bool holds;
      if (!guard)
        holds = true;
      else {
        try {
          holds = evalGuard(*guard, env);
        } catch (const ExprError &ex) {
          return refuse(ex.code);
        }
      }
      // Required: an unconditional group, any accepted() group (temporal — it
      // must eventually accept), or a comparison group that holds for these
      // (immutable) inputs. A comparison group that is false is permanently
      // suppressed — not required, never blocks the terminal.
      if (!guard || isAccepted || holds)
        required.insert(g.guardKey);
      groups.push_back({&g, holds, holds && !committedSoFar.count(g.guardKey)});
    }

    // Stage the committable groups' effects onto a COPY of the balances — a
    // refusal (operand / overflow) rolls back cleanly, nothing partial.
    struct Pending {
      const PlanEffect *eff;
      Account account;
      long long delta;
    };
    std::vector<Pending> pending;
    std::set<std::string> committing;
    std::map<Account, long long> staged = state.balances;
    for (const GroupInfo &gp : groups) {
      const ExprNode *guard =
          coordinationPlan.effects[gp.g->firstIndex].guard.get();
      if (guard) {
        json::Object o = obs("guard");
        o["group"] = gp.g->guardKey;
        o["held"] = gp.holds;
        r.trace.push_back(std::move(o));
      }
      if (!gp.committable)
        continue;
      committing.insert(gp.g->guardKey);
      for (size_t idx : gp.g->effectIndices) {
        const PlanEffect &e = coordinationPlan.effects[idx];
        if (e.kind != "debit" && e.kind != "credit")
          return refuse("effect.kind", e.name);
        if (e.ledger.empty())
          return refuse("operand.malformed", e.name);
        long long value;
        if (std::string code = resolveAmount(e.amount, env, value);
            !code.empty())
          return refuse(code, e.name);
        Account acct;
        acct.ledger = e.ledger;
        if (std::string code =
                resolveSymbol(e.party, input.symbols, acct.party);
            !code.empty())
          return refuse(code, e.name);
        if (std::string code =
                resolveSymbol(e.currency, input.symbols, acct.currency);
            !code.empty())
          return refuse(code, e.name);
        long long delta = (e.kind == "credit") ? value : -value;
        long long cur = staged.count(acct) ? staged[acct] : 0;
        long long sum;
        if (__builtin_add_overflow(cur, delta, &sum))
          return refuse("balance.overflow", e.name);
        staged[acct] = sum;
        pending.push_back({&e, acct, delta});
      }
    }

    if (committing.empty()) {
      // No group could commit — a valid NO-PROGRESS no-op (a required group
      // awaits its quorum). No ledger movement; state unchanged.
      json::Object o = obs("no-progress");
      o["key"] = keyVal;
      r.trace.push_back(std::move(o));
      r.outcome = Outcome::NoProgress;
      r.next = state;
      return std::move(r);
    }

    // COMMIT the newly-committable groups: publish balances, emit their deltas
    // + events, record the group ids, and pin the key's claim.
    r.next.balances = std::move(staged);
    for (const Pending &p : pending) {
      json::Object o = obs("ledger-delta");
      o["effect"] = p.eff->name;
      o["ledger"] = p.account.ledger;
      o["party"] = p.account.party;
      o["currency"] = p.account.currency;
      o["delta"] = p.delta;
      r.trace.push_back(std::move(o));
    }
    for (const Pending &p : pending) {
      json::Object o = obs("event");
      o["name"] = effectEvent(*p.eff);
      r.trace.push_back(std::move(o));
    }
    std::set<std::string> &committed = r.next.committedGroups[keyVal];
    committed.insert(committing.begin(), committing.end());
    r.next.keyClaim[keyVal] = claim;

    // Terminal ONLY once every required group has committed.
    bool allDone = true;
    for (const std::string &gid : required)
      if (!committed.count(gid)) {
        allDone = false;
        break;
      }
    if (allDone) {
      json::Object ev = obs("event");
      ev["name"] = pascalCase(coordinationPlan.procedure) + "Reconciled";
      r.trace.push_back(std::move(ev));
      json::Object t = obs("terminal");
      t["state"] = coordinationPlan.terminal.success;
      r.trace.push_back(std::move(t));
      r.next.postedKeys.insert(keyVal);
      r.next.keyStatus[keyVal] = coordinationPlan.terminal.success;
    }
    // Terminal (last required group committed) vs Progress (a required group is
    // still pending) — an explicit disposition, not inferred from the trace.
    r.outcome = allDone ? Outcome::Terminal : Outcome::Progress;
    return std::move(r);
  }

  // 6. VALIDATE every effect and stage its delta into a COPY of the balances —
  // no observable state is mutated here, so any refusal below (including a
  // balance overflow) rolls back cleanly.
  struct Pending {
    const PlanEffect *eff;
    Account account;
    long long delta;
  };
  std::vector<Pending> pending;
  std::map<Account, long long> staged = state.balances;
  for (const PlanEffect &e : coordinationPlan.effects) {
    // Effect kind must be exactly debit|credit — an unknown kind is refused,
    // never silently treated as a debit.
    if (e.kind != "debit" && e.kind != "credit")
      return refuse("effect.kind", e.name);
    // Guard: a conditional leg posts iff its predicate holds.
    if (e.guard) {
      bool held;
      try {
        held = evalGuard(*e.guard, env);
      } catch (const ExprError &ex) {
        return refuse(ex.code, e.name);
      }
      json::Object o = obs("guard");
      o["effect"] = e.name;
      o["held"] = held;
      r.trace.push_back(std::move(o));
      if (!held)
        continue;
    }
    // Attestation gate: a firing gated leg requires its policy accepted, else
    // the whole transition is refused atomically (a balanced group cannot drop
    // one leg and still conserve value).
    if (!e.attestationInput.empty()) {
      auto it = input.attestations.find(e.attestationInput);
      bool accepted = it != input.attestations.end() && it->second;
      json::Object o = obs("attestation");
      o["effect"] = e.name;
      o["policy"] = e.attestationInput;
      o["accepted"] = accepted;
      r.trace.push_back(std::move(o));
      if (!accepted)
        return refuse("attestation.rejected", e.name);
    }
    // Resolve the ledger-delta operands: amount (numeric), party + currency
    // (symbolic). A malformed / unresolved operand is a coded refusal, as is an
    // empty ledger name (an empty posting-identity component).
    if (e.ledger.empty())
      return refuse("operand.malformed", e.name);
    long long value;
    if (std::string code = resolveAmount(e.amount, env, value); !code.empty())
      return refuse(code, e.name);
    Account acct;
    acct.ledger = e.ledger;
    if (std::string code = resolveSymbol(e.party, input.symbols, acct.party);
        !code.empty())
      return refuse(code, e.name);
    if (std::string code =
            resolveSymbol(e.currency, input.symbols, acct.currency);
        !code.empty())
      return refuse(code, e.name);
    // value >= 0 (checked above), so negation is in range.
    long long delta = (e.kind == "credit") ? value : -value;
    // Checked accumulation onto the STAGED balance — an overflow is refused
    // before any commit, so the observable state is never left inconsistent.
    long long cur = staged.count(acct) ? staged[acct] : 0;
    long long sum;
    if (__builtin_add_overflow(cur, delta, &sum))
      return refuse("balance.overflow", e.name);
    staged[acct] = sum;
    pending.push_back({&e, acct, delta});
  }

  // 7. COMMIT — publish the staged balances, emit the ledger deltas in order,
  // then the choreography and the verified success terminal. The ONLY mutation.
  r.next.balances = std::move(staged);
  for (const Pending &p : pending) {
    json::Object o = obs("ledger-delta");
    o["effect"] = p.eff->name;
    o["ledger"] = p.account.ledger;
    o["party"] = p.account.party;
    o["currency"] = p.account.currency;
    o["delta"] = p.delta;
    r.trace.push_back(std::move(o));
  }
  for (const Pending &p : pending) {
    json::Object o = obs("event");
    o["name"] = effectEvent(*p.eff);
    r.trace.push_back(std::move(o));
  }
  // Obligation lifecycle (): observed AFTER the effects it authorizes, so
  // an eligible obligation whose ordered effects all posted is `fired`,
  // distinct from the effect deltas themselves.
  {
    std::set<std::string> committedEffects;
    for (const Pending &p : pending)
      committedEffects.insert(p.eff->name);
    observeObligations(committedEffects);
  }
  {
    json::Object o = obs("event");
    o["name"] = pascalCase(coordinationPlan.procedure) + "Reconciled";
    r.trace.push_back(std::move(o));
  }
  {
    json::Object o = obs("terminal");
    o["state"] = coordinationPlan.terminal.success;
    r.trace.push_back(std::move(o));
  }
  r.next.postedKeys.insert(keyVal);
  r.next.keyClaim[keyVal] = claim;
  r.next.keyStatus[keyVal] = coordinationPlan.terminal.success;
  // A single-shot (non-temporal) coordination completes in one commit.
  r.outcome = Outcome::Terminal;
  return std::move(r);
}

std::string transitionToText(const TransitionResult &result) {
  const char *outcome = result.outcome == Outcome::Terminal     ? "terminal"
                        : result.outcome == Outcome::Progress   ? "progress"
                        : result.outcome == Outcome::NoProgress ? "no-progress"
                        : result.outcome == Outcome::Replayed   ? "replayed"
                                                                : "refused";
  json::Array balances;
  for (const auto &kv : result.next.balances)
    balances.push_back(json::Object{{"ledger", kv.first.ledger},
                                    {"party", kv.first.party},
                                    {"currency", kv.first.currency},
                                    {"balance", kv.second}});
  json::Array keys;
  for (const std::string &k : result.next.postedKeys)
    keys.push_back(k);
  // The per-key execution claim is load-bearing semantic state ():
  // serialize it so two states that differ only by their established claim are
  // NOT byte-identical to the differential/FileCheck oracle. Deterministic
  // (sorted by key via std::map). A realization that omits claim persistence
  // diverges here.
  json::Object keyClaim;
  for (const auto &kv : result.next.keyClaim)
    keyClaim[kv.first] = kv.second;
  // The temporal commit ledger is load-bearing semantic state (): key
  // -> the ordered set of committed group ids. Serialized so a partially- vs
  // fully-committed key is observable, and a realization that omits per-group
  // commit tracking diverges here. Deterministic (std::map/std::set sorted).
  json::Object committedGroups;
  for (const auto &kv : result.next.committedGroups) {
    json::Array gids;
    for (const std::string &gid : kv.second)
      gids.push_back(gid);
    committedGroups[kv.first] = std::move(gids);
  }
  // Per-key terminal status: a terminal K1 never makes a still-open K2 read as
  // terminal (the observable lifecycle is keyed, like the commit ledger).
  json::Object keyStatus;
  for (const auto &kv : result.next.keyStatus)
    keyStatus[kv.first] = kv.second;

  // json::Array is move-only into a Value; copy the trace for a const arg.
  json::Array trace;
  for (const json::Value &v : result.trace)
    trace.push_back(v);

  json::Value root = json::Object{
      {"outcome", outcome},
      {"trace", std::move(trace)},
      {"nextState",
       json::Object{{"keyStatus", std::move(keyStatus)},
                    {"balances", std::move(balances)},
                    {"keyClaim", std::move(keyClaim)},
                    {"committedGroups", std::move(committedGroups)},
                    {"postedKeys", std::move(keys)}}}};
  std::string text;
  raw_string_ostream os(text);
  os << formatv("{0:2}", root) << "\n";
  os.flush();
  return text;
}

} // namespace neutrino
