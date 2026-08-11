//===- CoordinationPlan.cpp - the one normalization + verification seam ---===//
//
// assemblePlan is the single place the coordination plan is normalized and
// VERIFIED (): both builders — normalizePlan from the verified MLIR view
// and planFromSpec from a capability-spec — gather raw inputs and hand them
// here, so the two paths cannot diverge and the checks live once. Failures are
// surfaced as llvm::Error (the  ratchet forbids new throws in the compiler
// core), BEFORE renderer dispatch.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationPlan.h"

#include "Neutrino/Expr.h"
#include "Neutrino/ValueModel.h"
#include "llvm/Support/Error.h"

#include <map>
#include <set>
#include <utility>

using namespace llvm;

namespace neutrino {

// The obligation lifecycle vocabulary, DERIVED from the representation version
// ( P1-3) — see the header. Kept beside assemblePlan so the derivation and
// the version check that guards it live in one file.
std::vector<std::string> obligationStatusVocabulary(int version) {
  if (version == kObligationPlanVersion)
    return {"eligible", "fired", "refused"};
  return {};
}

namespace {
Error planError(const Twine &msg) {
  return createStringError(inconvertibleErrorCode(),
                           "coordination plan: " + msg);
}

// An explicit instance key must be an opaque string identity — never a numeric
// value (money/decimal) or an unclassified extension type.
bool isInstanceKeyType(llvm::StringRef type) {
  return classifyValueType(type) == ValueCategory::String;
}

// The operand's identity, "kind:value" (e.g. "ref:amount", "literal:100"), used
// to compare moved values by identity for the per-group conservation check.
std::string operandKey(const json::Object *o) {
  if (!o)
    return "";
  return o->getString("kind").value_or("").str() + ":" +
         o->getString("value").value_or("").str();
}

bool isDeclaredPolicy(const std::vector<AttestationPolicy> &policies,
                      const std::string &input) {
  for (const AttestationPolicy &p : policies)
    if (p.input == input)
      return true;
  return false;
}

bool isLifecycleEffect(StringRef effect) {
  return effect == "post" || effect == "compensate" || effect == "reserve" ||
         effect == "consume" || effect == "release";
}

bool isLifecycleGuardKind(StringRef kind) {
  return kind == "participant" || kind == "deadline" || kind == "sequence";
}

bool isLifecycleEvidenceStyle(StringRef style) {
  return style == "single_hash" || style == "batched_root";
}

} // namespace

// The SEMANTIC canonical key of a guard predicate ( amendment 4): a
// deterministic STRUCTURAL serialization. CONSERVATIVE by construction — it
// preserves operator, operand order, and shape exactly, performing NO algebraic
// folding, commutation, or reassociation — so two guards share a key iff they
// are structurally identical (source-text spacing aside), never merely "equal
// by a rewrite that rounding/division/overflow might not preserve". "" for an
// unconditional effect.
std::string canonicalGuardKey(const ExprNode *n) {
  if (!n)
    return "";
  switch (n->kind) {
  case ExprNode::Num:
    return "#" + std::to_string(n->num);
  case ExprNode::Var:
    return "$" + n->name;
  case ExprNode::Bin:
    return "(" + std::string(1, n->op) + " " + canonicalGuardKey(n->lhs.get()) +
           " " + canonicalGuardKey(n->rhs.get()) + ")";
  case ExprNode::Cmp:
    return "(" + n->name + " " + canonicalGuardKey(n->lhs.get()) + " " +
           canonicalGuardKey(n->rhs.get()) + ")";
  case ExprNode::Call: {
    std::string s = "(" + n->name;
    for (const auto &a : n->args)
      s += " " + canonicalGuardKey(a.get());
    return s + ")";
  }
  }
  return "";
}

Expected<CoordinationPlan> assemblePlan(PlanInputs in) {
  // An effect-less procedure (e.g. an anchor-only spec) and a spec with no
  // success terminal are legitimate capability-specs that are simply NOT a
  // renderable coordination — the backend renderers reject them. So the plan is
  // built leniently for those; the hard errors below are corruption the MLIR
  // verifier prevents on a valid source and that only a crafted external spec
  // can carry (a non-ref/ambiguous key, an undeclared/inconsistent binding, an
  // unbalanced guard group) — those still fail here, before renderer dispatch.
  CoordinationPlan plan;
  plan.procedure = in.procedure;
  plan.invokedEvent = in.invokedEvent;
  plan.balanced = in.balanced;
  plan.inputs = std::move(in.inputs); // the declared input inventory
  plan.participants = std::move(in.participants);
  plan.allowedOrgPairs = std::move(in.allowedOrgPairs);
  plan.attestations = in.attestations;
  plan.computes = std::move(in.computes); // owns the typed compute expressions

  if (plan.participants.size() > kMaxCanonicalAuthorizationParticipants)
    return planError("authorization participant count " +
                     Twine(plan.participants.size()) +
                     " exceeds canonical topology limit " +
                     Twine(kMaxCanonicalAuthorizationParticipants));

  std::set<std::string> participantNames;
  std::set<std::pair<std::string, std::string>> actorIdentities;
  for (const PlanParticipant &participant : plan.participants) {
    if (participant.name.empty())
      return planError("authorization participant has an empty identity");
    if (!participantNames.insert(participant.name).second)
      return planError("duplicate authorization participant '" +
                       participant.name + "'");
    if (!participant.org.empty() &&
        !actorIdentities.insert({participant.org, participant.role}).second)
      return planError("ambiguous authorization identity for organization '" +
                       participant.org + "' and role '" + participant.role +
                       "'");
  }

  auto endpointCount = [&](const std::string &org) {
    size_t count = 0;
    for (const PlanParticipant &participant : plan.participants)
      if (participant.org == org)
        ++count;
    return count;
  };
  std::set<std::pair<std::pair<std::string, std::string>,
                     std::pair<std::string, std::string>>>
      topologyEdges;
  for (const PlanOrgPolicy &edge : plan.allowedOrgPairs) {
    if (edge.orgA.empty() || edge.orgB.empty())
      return planError("allowed organization edge has an empty endpoint");
    size_t countA = endpointCount(edge.orgA);
    size_t countB = endpointCount(edge.orgB);
    if (countA == 0)
      return planError("allowed organization edge endpoint '" + edge.orgA +
                       "' does not resolve to a declared authorization actor");
    if (countB == 0)
      return planError("allowed organization edge endpoint '" + edge.orgB +
                       "' does not resolve to a declared authorization actor");
    auto a = std::make_pair(edge.orgA, edge.roleA);
    auto b = std::make_pair(edge.orgB, edge.roleB);
    if (b < a)
      std::swap(a, b);
    if (!topologyEdges.insert({a, b}).second)
      return planError("duplicate allowed organization edge between '" +
                       edge.orgA + "' and '" + edge.orgB + "'");
  }

  // Resolve THE workflow key. An explicit procedure-level instance-key
  // declaration is target-neutral and WINS: it must name a declared,
  // string-category input, and any effects must agree with it. Otherwise the
  // key is derived the legacy way — every effect's idempotencyKey must
  // reference the same input (byte-identical for effectful procedures that
  // declare no explicit key). A missing / literal / ambiguous key fails here,
  // before dispatch.
  std::string workflowKey;
  if (!in.explicitInstanceKey.empty()) {
    const PlanInput *ki = nullptr;
    for (const PlanInput &pi : plan.inputs)
      if (pi.name == in.explicitInstanceKey) {
        ki = &pi;
        break;
      }
    if (!ki)
      return planError("instance key '" + in.explicitInstanceKey +
                       "' names no declared input");
    if (!isInstanceKeyType(ki->type))
      return planError("instance key '" + in.explicitInstanceKey +
                       "' has non-string type '" + ki->type + "'");
    workflowKey = in.explicitInstanceKey;
    // Every effect must key on the SAME declared instance — a ref to it. A
    // literal effect key, or a ref to a different input, is ambiguous identity;
    // it fails here rather than being silently rewritten to the declared key.
    for (size_t i = 0; i < in.effects.size(); ++i) {
      const PlanEffectInput &e = in.effects[i];
      if (e.idempotencyKind != "ref" || e.idempotencyValue != workflowKey)
        return planError("ambiguous instance key — effect " + Twine(i) +
                         " does not key on the declared instance key '" +
                         workflowKey + "' (effect key: " +
                         (e.idempotencyKind == "ref"
                              ? "ref '" + e.idempotencyValue + "'"
                              : "literal") +
                         ")");
    }
  } else {
    for (size_t i = 0; i < in.effects.size(); ++i) {
      const PlanEffectInput &e = in.effects[i];
      if (e.idempotencyKind != "ref" || e.idempotencyValue.empty())
        return planError("effect " + Twine(i) +
                         " idempotencyKey must reference an input (kind='" +
                         e.idempotencyKind + "')");
      if (workflowKey.empty())
        workflowKey = e.idempotencyValue;
      else if (workflowKey != e.idempotencyValue)
        return planError("ambiguous workflow key — effect " + Twine(i) +
                         " keys on '" + e.idempotencyValue +
                         "' but earlier effects key on '" + workflowKey + "'");
    }
  }
  plan.workflowKey = workflowKey;
  plan.explicitInstanceKey = in.explicitInstanceKey;
  plan.replay.key = workflowKey;
  plan.replay.idempotent = true;

  // Effectless-coordination legality: an effectless plan is a renderable/
  // evaluable coordination ONLY as an evidence-acceptance action — an
  // attestation policy, an explicit instance key, and a success terminal. (A
  // bare anchor-only spec with no attestation is still assembled leniently; it
  // is simply not a coordination the evaluator or renderers accept.)
  plan.evidenceOnly = in.effects.empty() && !in.attestations.empty();
  if (plan.evidenceOnly) {
    if (in.explicitInstanceKey.empty())
      return planError("evidence-only coordination requires an explicit "
                       "instance key");
    if (in.terminal.success.empty())
      return planError(
          "evidence-only coordination requires a success terminal");
  } else if (in.effects.empty() && !in.explicitInstanceKey.empty()) {
    return planError("an effectless coordination must declare an "
                     "attestation/evidence acceptance action");
  }

  // Resolve + VERIFY the effect->attestation binding (). An accepted(x)
  // guard binds the effect to policy x with SUPPRESS semantics — a false quorum
  // skips the leg (a balanced no-op), per-policy, so MULTIPLE policies each
  // gate their own legs at the plan + reference-evaluator level. A single
  // declared policy with no accepted() guard is the legacy global gate
  // (atomic refuse when unaccepted). A binding that names an UNDECLARED policy
  // is a hard error. (The backend render is still single-policy until
  // slice 3 — the per-policy Solidity/PostgreSQL realization;
  // requireSingleAttestationPolicy fails closed there, not here.)
  for (size_t i = 0; i < in.effects.size(); ++i) {
    PlanEffectInput &e = in.effects[i];
    if (!plan.participants.empty() && e.participant.empty())
      return planError("effect " + Twine(i) + " (" + e.name +
                       ") is missing its authorization participant");
    if (!e.participant.empty() && !participantNames.count(e.participant))
      return planError("effect " + Twine(i) + " (" + e.name +
                       ") references undeclared authorization participant '" +
                       e.participant + "'");
    // An effect gates on evidence in one of two ways:
    //   accepted(x) guard (): SUPPRESS semantics — a false quorum skips the
    //     leg (balanced no-op) via the `when` guard; per-policy, so multiple
    //     policies each gate their own legs. NOT the atomic-refuse gate, so
    //     attestationInput stays "".
    //   legacy single declared policy: the global gate — atomically REFUSES
    //     every effect when unaccepted (attestationInput set).
    // The referenced policy must be declared in either case.
    std::string bound;
    PlanGateMode gateMode = PlanGateMode::None;
    std::string gatePolicy;
    if (!e.guardAcceptedInput.empty()) {
      if (!isDeclaredPolicy(in.attestations, e.guardAcceptedInput))
        return planError("effect " + Twine(i) + " (" + e.name +
                         ") gates on undeclared attestation policy '" +
                         e.guardAcceptedInput + "'");
      // accepted(x) binds per-policy suppress: the gate mode and policy are
      // resolved here, so a target legalizer consumes the binding and never
      // inspects the guard AST.
      gateMode = PlanGateMode::TemporalSuppress;
      gatePolicy = e.guardAcceptedInput;
    } else if (in.attestations.size() == 1) {
      bound = in.attestations.front().input;
      gateMode = PlanGateMode::AtomicRefuse;
      gatePolicy = bound;
    }
    PlanEffect pe;
    pe.index = i;
    pe.name = e.name;
    pe.kind = e.kind;
    pe.participant = e.participant;
    pe.canonicalGuard = e.canonicalGuard;
    pe.guardKey = canonicalGuardKey(e.guard.get()); // structural partition key
    pe.attestationInput = bound;
    pe.gateMode = gateMode;
    pe.gatePolicy = gatePolicy;
    // The ledger-delta operands the reference evaluator resolves ().
    pe.ledger = e.ledger;
    pe.party = e.party;
    pe.amount = e.amount;
    pe.currency = e.currency;
    pe.memo = e.memo;
    pe.guard = std::move(e.guard); // owns the typed guard predicate
    plan.effects.push_back(std::move(pe));
  }

  // Per-policy binding completeness (): when ANY effect gates on an
  // accepted(x) policy, the coordination is in per-policy mode — every DECLARED
  // policy must then be bound by some accepted() guard, else it is a declared
  // quorum that gates nothing (fail-open). Target-neutral, so every rail
  // legalizes the same verified binding rather than rediscovering it. (A
  // coordination with no accepted() guard keeps the legacy single-gate rule.)
  std::set<std::string> acceptedBound;
  for (const PlanEffect &pe : plan.effects)
    if (pe.gateMode == PlanGateMode::TemporalSuppress)
      acceptedBound.insert(pe.gatePolicy);
  if (!acceptedBound.empty())
    for (const AttestationPolicy &p : plan.attestations)
      if (!acceptedBound.count(p.input))
        return planError("[attest.policy.unbound] attestation policy '" +
                         p.input +
                         "' is declared but no effect gates on accepted(" +
                         p.input + ") — a per-policy coordination must bind " +
                         "every declared quorum");

  // Once any effect selects temporal per-policy suppression, every effect must
  // be authorized by its own accepted() policy. Otherwise the per-policy commit
  // ledger would coexist with an effect that can commit outside an accepted
  // execution claim. Establish this legality once before target dispatch.
  if (!acceptedBound.empty())
    for (const PlanEffect &pe : plan.effects)
      if (pe.gateMode != PlanGateMode::TemporalSuppress)
        return planError(
            "[attest.temporal.mixed] effect '" + pe.name +
            "' is not gated on an accepted() policy, but the coordination has "
            "accepted() groups — a temporal per-policy coordination must gate "
            "every effect on accepted(); mixing per-policy and "
            "ordinary/unconditional effects is unsupported");

  // Partition effects by the SEMANTIC guard key — canonical STRUCTURE, not raw
  // source text ( amendment 4; group order = first appearance) — and derive
  // + VERIFY the per-group balance obligation and binding consistency.
  for (const PlanEffect &pe : plan.effects) {
    PlanEffectGroup *g = nullptr;
    for (PlanEffectGroup &cand : plan.effectGroups)
      if (cand.guardKey == pe.guardKey) {
        g = &cand;
        break;
      }
    if (!g) {
      PlanEffectGroup ng;
      ng.canonicalGuard = pe.canonicalGuard;
      ng.guardKey = pe.guardKey;
      ng.attestationInput = pe.attestationInput;
      ng.gateMode = pe.gateMode;
      ng.gatePolicy = pe.gatePolicy;
      ng.firstIndex = pe.index;
      ng.mustBalance = plan.balanced;
      plan.effectGroups.push_back(std::move(ng));
      g = &plan.effectGroups.back();
    }
    // Effects sharing a guard must agree on their policy binding. The gate
    // mode/policy is a function of the guard partition (guardKey encodes the
    // accepted() argument), so it is uniform within a group by construction —
    // we carry it from the first effect (above) and verify the legacy
    // atomic-refuse input here, which is the field that can vary independently
    // of the guard.
    if (g->attestationInput != pe.attestationInput)
      return planError("inconsistent guard group '" + pe.canonicalGuard +
                       "' — effect '" + pe.name + "' binds policy '" +
                       pe.attestationInput + "' but the group binds '" +
                       g->attestationInput + "'");
    g->effectIndices.push_back(pe.index);
    if (pe.kind == "debit")
      ++g->debitCount;
    else if (pe.kind == "credit")
      ++g->creditCount;
  }

  // A balanced group must PROVABLY conserve value where its guard holds: the
  // multiset of (amount, currency) operands debited must equal the multiset
  // credited. Comparing identities (not just debit/credit counts) rejects a
  // debit of 100 EUR "balanced" by a credit of 1 USD — or by a credit of a
  // different symbolic amount — and subsumes the "needs a debit and a credit"
  // check (an all-debit or all-credit group has unequal multisets).
  for (const PlanEffectGroup &g : plan.effectGroups) {
    if (!g.mustBalance)
      continue;
    std::multiset<std::pair<std::string, std::string>> debited, credited;
    for (size_t idx : g.effectIndices) {
      const PlanEffectInput &e = in.effects[idx];
      auto value = std::make_pair(e.amount, e.currency);
      (e.kind == "debit" ? debited : credited).insert(value);
    }
    if (debited != credited)
      return planError(
          "unbalanced guard group '" + g.canonicalGuard +
          "' — the debited (amount, currency) multiset does not equal the "
          "credited one; the group does not provably conserve value");
  }

  // The lifecycle->backend terminal projection (the renderers fail closed on a
  // missing success terminal; the plan carries whatever the lifecycle
  // declares).
  plan.terminal = in.terminal;
  std::set<std::string> lifecycleStates(in.lifecycleStates.begin(),
                                        in.lifecycleStates.end());
  if (lifecycleStates.size() != in.lifecycleStates.size())
    return planError("[spec.bad_transition] lifecycle states must be unique");
  if (!in.lifecycleTransitions.empty() && lifecycleStates.empty())
    return planError("[spec.bad_transition] lifecycle transitions require a "
                     "non-empty lifecycle states set");
  if (!in.lifecycleTransitions.empty() && in.lifecycleInitialState.empty())
    return planError(
        "[spec.bad_transition] lifecycle initial state is missing");
  if (!in.lifecycleInitialState.empty() &&
      !lifecycleStates.count(in.lifecycleInitialState))
    return planError("[spec.bad_transition] lifecycle initial state '" +
                     in.lifecycleInitialState + "' is undeclared");
  for (const auto &[kind, state] :
       {std::pair<const char *, const std::string &>{"success",
                                                     in.terminal.success},
        {"aborted", in.terminal.aborted},
        {"contested", in.terminal.contested}})
    if (!state.empty() && !lifecycleStates.count(state))
      return planError("[spec.bad_transition] lifecycle " + Twine(kind) +
                       " terminal state '" + state + "' is undeclared");
  for (const LifecycleTransitionPolicy &t : in.lifecycleTransitions) {
    if (t.name.empty() || t.from.empty() || t.to.empty())
      return planError("[spec.bad_transition] lifecycle transition must "
                       "declare non-empty name/from/to");
    if (t.idempotency != "reject" && t.idempotency != "noop_on_identical")
      return planError("[spec.transition_idempotency] lifecycle transition '" +
                       t.name + "' declares unsupported idempotency '" +
                       t.idempotency + "'");
    for (const std::string &effect : t.effects)
      if (!isLifecycleEffect(effect))
        return planError("[spec.transition_effect] lifecycle transition '" +
                         t.name + "' declares unsupported effect '" + effect +
                         "'");
    for (const LifecycleTransitionGuardPolicy &guard : t.guards) {
      if (guard.kind.empty())
        return planError("[spec.transition_guard] lifecycle transition '" +
                         t.name + "' guard is missing kind");
      if (!isLifecycleGuardKind(guard.kind))
        return planError("[spec.transition_guard] lifecycle transition '" +
                         t.name + "' declares unsupported guard kind '" +
                         guard.kind + "'");
    }
    if (t.evidence && !isLifecycleEvidenceStyle(t.evidence->style))
      return planError("[spec.transition_evidence] lifecycle transition '" +
                       t.name + "' declares unsupported evidence style '" +
                       t.evidence->style + "'");
    if (!lifecycleStates.count(t.from))
      return planError("[spec.bad_transition] lifecycle transition '" + t.name +
                       "' has undeclared from state '" + t.from + "'");
    if (!lifecycleStates.count(t.to))
      return planError("[spec.bad_transition] lifecycle transition '" + t.name +
                       "' has undeclared to state '" + t.to + "'");
  }
  plan.lifecycleInitialState = std::move(in.lifecycleInitialState);
  plan.lifecycleStates = std::move(in.lifecycleStates);
  plan.lifecycleTransitions = std::move(in.lifecycleTransitions);

  // Obligations (): resolve each undertaking's obligor/scope against the
  // declared participants and its ORDERED effect references against the plan's
  // effects, WITHOUT flattening it into an anonymous guard + effects. Re-run
  // here (not only in the MLIR verifier) so a crafted external spec that
  // bypassed the verifier is rejected too — same rationale as the
  // effect/participant checks above. The registered [kernel.obligation.*] codes
  // mirror the op verifier; the version axis fails closed plainly.
  {
    std::set<std::string> effectNames;
    std::map<std::string, size_t>
        effectPos; // executable order position by name
    std::map<std::string, std::string>
        effectGuardKey; // structural guard key by name
    for (size_t i = 0; i < plan.effects.size(); ++i) {
      effectNames.insert(plan.effects[i].name);
      effectPos[plan.effects[i].name] = i;
      effectGuardKey[plan.effects[i].name] = plan.effects[i].guardKey;
    }
    std::set<std::string> obligationNames;
    for (PlanObligationInput &o : in.obligations) {
      if (o.version != kObligationPlanVersion)
        return planError("obligation '" + o.name +
                         "' declares unknown version " + Twine(o.version) +
                         " (expected " + Twine(kObligationPlanVersion) + ")");
      if (o.name.empty())
        return planError("[kernel.obligation.identity] obligation declares an "
                         "empty identity");
      if (!obligationNames.insert(o.name).second)
        return planError("[kernel.obligation.identity] duplicate obligation '" +
                         o.name + "'");
      if (o.obligor.empty() || !participantNames.count(o.obligor))
        return planError("[kernel.obligation.obligor] obligation '" + o.name +
                         "' obligor '" + o.obligor +
                         "' does not resolve to a declared participant");
      for (const auto &scope : {std::make_pair("beneficiary", o.beneficiary),
                                std::make_pair("authority", o.authority)})
        if (scope.second.empty() || !participantNames.count(scope.second))
          return planError("[kernel.obligation.scope] obligation '" + o.name +
                           "' " + scope.first + " '" + scope.second +
                           "' does not resolve to a declared participant");
      if (!o.when || o.canonicalGuard.empty())
        return planError("[kernel.obligation.predicate] obligation '" + o.name +
                         "' is missing its activation predicate");
      if (o.effects.empty())
        return planError("[kernel.obligation.effects_empty] obligation '" +
                         o.name + "' authorizes no value effects");
      // AUTHORIZATION coherence ( R1b, architect F1): the obligation
      // "authorizes" its effects, so its activation predicate must be exactly
      // the guard those effects post under. The reference evaluator observes
      // the obligation on its OWN predicate while effects post on THEIR guards;
      // if the two differ, the effects can post while the obligation reports
      // `refused` (or vice-versa) and "authorizes" is false. For this selected
      // vertical we require each referenced effect's structural guardKey to
      // EQUAL the obligation's, so authorization is coherent by construction
      // and a pre-N consumer that drops obligations[] never loses a gate no
      // effect independently carries. Plain (uncoded) planError — the
      // [kernel.obligation.*] family is full against the frozen taxonomy.
      const std::string obGuardKey = canonicalGuardKey(o.when.get());
      std::set<std::string> seenEffects;
      size_t lastPos = 0;
      bool havePrev = false;
      for (const std::string &en : o.effects) {
        if (!seenEffects.insert(en).second)
          return planError("[kernel.obligation.duplicate_effect] obligation '" +
                           o.name + "' declares effect '" + en +
                           "' more than once");
        auto pos = effectPos.find(en);
        if (pos == effectPos.end())
          return planError("[kernel.obligation.not_an_effect] obligation '" +
                           o.name + "' effect '" + en +
                           "' does not resolve to a declared value effect");
        if (effectGuardKey[en] != obGuardKey)
          return planError("obligation '" + o.name +
                           "' predicate does not match the guard "
                           "of authorized effect '" +
                           en + "' (effect guardKey '" + effectGuardKey[en] +
                           "' != obligation guardKey '" + obGuardKey +
                           "') — the obligation would not gate this effect");
        // The obligation's authorization order MUST agree with the executable
        // coordination-plan order ( P1-4): the declared effect references
        // must appear in strictly increasing plan position. Otherwise a
        // reversed authorization would still be honored as membership while
        // execution posts the opposite order — so the ordered authorization the
        // identity hashes is not the order that runs. Fail closed rather than
        // silently reorder. A plain (uncoded) planError, like the version check
        // above — the registered [kernel.obligation.*] family is full against
        // the frozen taxonomy boundary, and this order rule is a realization
        // (R1b) refinement of the same not_an_effect surface.
        if (havePrev && pos->second <= lastPos)
          return planError("obligation '" + o.name + "' authorizes effect '" +
                           en +
                           "' out of executable coordination-plan order (the "
                           "authorized order is not the order that runs)");
        lastPos = pos->second;
        havePrev = true;
      }
      PlanObligation po;
      po.version = o.version;
      po.name = o.name;
      po.obligor = o.obligor;
      po.beneficiary = o.beneficiary;
      po.authority = o.authority;
      po.canonicalGuard = o.canonicalGuard;
      po.guardKey = obGuardKey;
      po.when = std::move(o.when);
      po.effects = o.effects; // ORDERED — order is part of obligation identity
      // Statuses are DERIVED from the version (not carried on the wire), so a
      // spec cannot present an unsupported vocabulary ( P1-3).
      po.statuses = obligationStatusVocabulary(po.version);
      plan.obligations.push_back(std::move(po));
    }
  }

  return plan;
}

namespace {
// accepted(x) detection on a serialized guard AST: a Call named "accepted"
// whose single argument is a Var — returns x, or "" for any other guard shape.
std::string acceptedInputFromAst(const json::Object *ast) {
  if (!ast)
    return "";
  if (ast->getString("kind").value_or("") != "call")
    return "";
  if (ast->getString("name").value_or("") != "accepted")
    return "";
  const json::Array *args = ast->getArray("args");
  if (!args || args->size() != 1)
    return "";
  const json::Object *arg = (*args)[0].getAsObject();
  if (!arg || arg->getString("kind").value_or("") != "var")
    return "";
  return arg->getString("name").value_or("").str();
}
} // namespace

namespace {
// Type + VERIFY an EXTERNAL spec's structured expressions ONCE, RETAINING the
// typed trees ( P1). It re-runs the SAME inference the IR verifier runs on
// the authoring path, and — because an ingested spec's `category`/`deps` are
// untrusted input — proves each compute's declared category and dep set match
// its inferred expression, so nothing is laundered past the AST. `computeTrees`
// is filled in compute order (null when a compute has no ast); `guardTrees`
// maps an effect index to its typed guard predicate. Fail-closed with a coded
// diagnostic.
Error typeSpecExprs(const json::Object &spec,
                    std::vector<ExprPtr> &computeTrees,
                    std::map<size_t, ExprPtr> &guardTrees,
                    std::map<size_t, ExprPtr> &obligationTrees) {
  std::map<std::string, ValueCategory> env;
  if (const json::Array *ins = spec.getArray("inputs"))
    for (const json::Value &v : *ins)
      if (const json::Object *o = v.getAsObject())
        env[o->getString("name").value_or("").str()] =
            classifyValueType(o->getString("type").value_or(""));
  try {
    if (const json::Array *comps = spec.getArray("computes"))
      for (const json::Value &v : *comps) {
        const json::Object *o = v.getAsObject();
        ExprPtr node;
        if (o)
          if (const json::Value *ast = o->get("ast")) {
            node = exprFromJson(*ast);
            typeExpr(*node, env);
            env[o->getString("name").value_or("").str()] = node->dtype;
          }
        computeTrees.push_back(std::move(node));
      }
    if (const json::Array *effs = spec.getArray("effects")) {
      size_t i = 0;
      for (const json::Value &v : *effs) {
        if (const json::Object *o = v.getAsObject())
          if (const json::Object *w = o->getObject("when"))
            if (const json::Value *ast = w->get("ast")) {
              ExprPtr node = exprFromJson(*ast);
              typeGuard(*node, env);
              guardTrees[i] = std::move(node);
            }
        ++i;
      }
    }
    // Obligation activation predicates (): re-typed like an effect guard,
    // so an ingested spec's obligation predicate is proven well-typed, not
    // trusted.
    if (const json::Array *obs = spec.getArray("obligations")) {
      size_t i = 0;
      for (const json::Value &v : *obs) {
        if (const json::Object *o = v.getAsObject())
          if (const json::Object *w = o->getObject("when"))
            if (const json::Value *ast = w->get("ast")) {
              ExprPtr node = exprFromJson(*ast);
              typeGuard(*node, env);
              obligationTrees[i] = std::move(node);
            }
        ++i;
      }
    }
  } catch (const ExprError &e) {
    return createStringError(inconvertibleErrorCode(),
                             "coordination plan: [" + e.code + "] " + e.what());
  }

  // The ingested `category`/`deps` are UNTRUSTED — prove each matches the
  // inferred AST (no throw; return the coded Error directly).
  auto err = [](const Twine &m) {
    return createStringError(inconvertibleErrorCode(),
                             "coordination plan: " + m);
  };
  if (const json::Array *comps = spec.getArray("computes")) {
    size_t i = 0;
    for (const json::Value &v : *comps) {
      const json::Object *o = v.getAsObject();
      if (o && i < computeTrees.size() && computeTrees[i]) {
        const ExprNode &node = *computeTrees[i];
        std::string name = o->getString("name").value_or("").str();
        std::string declared = o->getString("category").value_or("").str();
        if (declared != categoryName(node.dtype).str())
          return err("[expr.type] compute '" + name + "' declares category '" +
                     declared + "' but its expression infers '" +
                     categoryName(node.dtype).str() + "'");
        std::set<std::string> declaredDeps, astVars;
        if (const json::Array *deps = o->getArray("deps"))
          for (const json::Value &d : *deps)
            if (auto s = d.getAsString())
              declaredDeps.insert(s->str());
        for (const std::string &vn : exprVars(node))
          astVars.insert(vn);
        if (declaredDeps != astVars)
          return err("[expr.deps] compute '" + name +
                     "' deps do not match its expression's variable set");
      }
      ++i;
    }
  }
  return Error::success();
}
} // namespace

Expected<CoordinationPlan> planFromSpec(const json::Object &spec) {
  std::vector<ExprPtr> computeTrees;
  std::map<size_t, ExprPtr> guardTrees;
  std::map<size_t, ExprPtr> obligationTrees;
  if (Error e = typeSpecExprs(spec, computeTrees, guardTrees, obligationTrees))
    return std::move(e);

  PlanInputs in;
  in.procedure = spec.getString("procedure").value_or("").str();
  in.invokedEvent = spec.getString("trigger").value_or("").str();
  in.attestations = attestationPoliciesFromSpec(spec);

  // The declared input inventory {name, type} in declaration order.
  if (const json::Array *ins = spec.getArray("inputs"))
    for (const json::Value &v : *ins)
      if (const json::Object *o = v.getAsObject())
        in.inputs.push_back({o->getString("name").value_or("").str(),
                             o->getString("type").value_or("").str()});

  const json::Value *participantsValue = spec.get("participants");
  if (!participantsValue)
    return planError("authorization participants array is missing");
  const json::Array *participants = participantsValue->getAsArray();
  if (!participants)
    return planError("authorization participants must be an array");
  for (const json::Value &v : *participants) {
    const json::Object *participant = v.getAsObject();
    if (!participant)
      return planError("authorization participants must contain only objects");
    std::string org;
    if (const json::Value *orgValue = participant->get("org")) {
      if (!orgValue->getAsNull()) {
        auto orgString = orgValue->getAsString();
        if (!orgString)
          return planError("authorization participant organization must be "
                           "a string or null");
        org = orgString->str();
      }
    }
    in.participants.push_back(
        {participant->getString("name").value_or("").str(),
         participant->getString("role").value_or("").str(), std::move(org)});
  }

  const json::Object *topology = spec.getObject("topology");
  if (!topology)
    return planError("authorization topology object is missing");
  const json::Value *pairsValue = topology->get("allowedOrgPairs");
  if (!pairsValue)
    return planError("allowed organization edges array is missing");
  const json::Array *pairs = pairsValue->getAsArray();
  if (!pairs)
    return planError("allowed organization edges must be an array");
  for (const json::Value &v : *pairs) {
    const json::Object *edge = v.getAsObject();
    if (!edge)
      return planError("allowed organization edges must contain only objects");
    in.allowedOrgPairs.push_back({edge->getString("orgA").value_or("").str(),
                                  edge->getString("orgB").value_or("").str(),
                                  edge->getString("roleA").value_or("").str(),
                                  edge->getString("roleB").value_or("").str()});
  }

  const json::Array *effectsA = spec.getArray("effects");
  if (!effectsA)
    return planError("spec declares no effects");
  size_t effIdx = 0;
  for (const json::Value &v : *effectsA) {
    const json::Object *eo = v.getAsObject();
    if (!eo)
      return planError("an effect is not a JSON object");
    PlanEffectInput e;
    e.name = eo->getString("name").value_or("").str();
    e.kind = eo->getString("kind").value_or("").str();
    const json::Value *participantValue = eo->get("participant");
    if (!participantValue)
      return planError("effect " + Twine(effIdx) +
                       " is missing its participant field");
    if (!participantValue->getAsNull()) {
      auto participant = participantValue->getAsString();
      if (!participant)
        return planError("effect " + Twine(effIdx) +
                         " participant must be a string or null");
      e.participant = participant->str();
    }
    if (const json::Object *idem = eo->getObject("idempotencyKey")) {
      e.idempotencyKind = idem->getString("kind").value_or("").str();
      e.idempotencyValue = idem->getString("value").value_or("").str();
    }
    if (const json::Object *w = eo->getObject("when")) {
      e.canonicalGuard = w->getString("expr").value_or("").str();
      e.guardAcceptedInput = acceptedInputFromAst(w->getObject("ast"));
      // Move in the ONE validated typed guard predicate ( P1).
      auto it = guardTrees.find(effIdx);
      if (it != guardTrees.end())
        e.guard = std::move(it->second);
    }
    e.amount = operandKey(eo->getObject("amount"));
    e.currency = operandKey(eo->getObject("currency"));
    e.ledger = eo->getString("ledger").value_or("").str();
    e.party = operandKey(eo->getObject("party"));
    e.memo = eo->getString("memo").value_or("").str();
    in.effects.push_back(std::move(e));
    ++effIdx;
  }

  // Obligations (): parsed ONLY when the spec declares them, so a spec
  // WITHOUT obligations rebuilds an obligation-free coordination plan
  // byte-identically. assemblePlan resolves obligor/scope/effects + fails
  // closed; the version is carried through so an unknown version is rejected
  // there. A PRESENT but non-array `obligations` fails closed ( P1-3): it
  // must never be silently dropped as if the spec carried none.
  if (spec.get("obligations") && !spec.getArray("obligations"))
    return planError("[kernel.obligation.identity] 'obligations' must be an "
                     "array when present");
  if (const json::Array *obsA = spec.getArray("obligations")) {
    size_t oIdx = 0;
    for (const json::Value &v : *obsA) {
      const json::Object *oo = v.getAsObject();
      if (!oo)
        return planError("an obligation is not a JSON object");
      PlanObligationInput po;
      po.version = (int)oo->getInteger("version").value_or(0);
      po.name = oo->getString("name").value_or("").str();
      po.obligor = oo->getString("obligor").value_or("").str();
      po.beneficiary = oo->getString("beneficiary").value_or("").str();
      po.authority = oo->getString("authority").value_or("").str();
      if (const json::Object *w = oo->getObject("when"))
        po.canonicalGuard = w->getString("expr").value_or("").str();
      if (auto it = obligationTrees.find(oIdx); it != obligationTrees.end())
        po.when = std::move(it->second);
      if (const json::Array *effs = oo->getArray("effects"))
        for (const json::Value &e : *effs)
          if (auto s = e.getAsString())
            po.effects.push_back(s->str());
      in.obligations.push_back(std::move(po));
      ++oIdx;
    }
  }

  if (const json::Array *comps = spec.getArray("computes")) {
    size_t cIdx = 0;
    for (const json::Value &v : *comps) {
      if (const json::Object *co = v.getAsObject()) {
        PlanCompute pc;
        pc.name = co->getString("name").value_or("").str();
        pc.category = co->getString("category").value_or("").str();
        if (const json::Array *deps = co->getArray("deps"))
          for (const json::Value &d : *deps)
            if (auto s = d.getAsString())
              pc.deps.push_back(s->str());
        // The ONE validated typed compute expression ( P1).
        if (cIdx < computeTrees.size())
          pc.expr = std::move(computeTrees[cIdx]);
        in.computes.push_back(std::move(pc));
      }
      ++cIdx;
    }
  }

  if (const json::Array *inv = spec.getArray("invariants"))
    for (const json::Value &v : *inv)
      if (const json::Object *io = v.getAsObject())
        if (io->getString("kind").value_or("") == "balanced")
          in.balanced = true;

  if (const json::Object *life = spec.getObject("lifecycle")) {
    in.lifecycleInitialState =
        life->getString("initialState").value_or("").str();
    if (const json::Array *states = life->getArray("states"))
      for (const json::Value &v : *states)
        if (const json::Object *so = v.getAsObject())
          in.lifecycleStates.push_back(
              so->getString("name").value_or("").str());
    if (const json::Object *term = life->getObject("terminalStates")) {
      in.terminal.success = term->getString("success").value_or("").str();
      in.terminal.aborted = term->getString("aborted").value_or("").str();
      in.terminal.contested = term->getString("contested").value_or("").str();
    }
    // The explicit instance-key declaration, when the spec carries one
    // (additive; absent for a legacy effect-keyed coordination).
    if (const json::Object *ik = life->getObject("instanceKey"))
      in.explicitInstanceKey = ik->getString("declared").value_or("").str();
    const json::Value *transitionsValue = life->get("transitions");
    if (!transitionsValue)
      return planError(
          "[spec.bad_transition] lifecycle transitions array is missing");
    const json::Array *transitions = transitionsValue->getAsArray();
    if (!transitions)
      return planError(
          "[spec.bad_transition] lifecycle transitions must be an array");
    if (transitions->empty())
      return planError("[spec.bad_transition] lifecycle transitions must be a "
                       "non-empty array");
    for (const json::Value &v : *transitions) {
      const json::Object *to = v.getAsObject();
      if (!to)
        return planError("[spec.bad_transition] lifecycle transitions must "
                         "contain only objects");
      std::string name = to->getString("name").value_or("").str();
      std::vector<std::string> effects;
      const json::Value *effectsValue = to->get("effects");
      if (!effectsValue)
        return planError("[spec.transition_effect] lifecycle transition '" +
                         name + "' is missing effects array");
      const json::Array *arr = effectsValue->getAsArray();
      if (!arr)
        return planError("[spec.transition_effect] lifecycle transition '" +
                         name + "' effects must be an array");
      for (const json::Value &ev : *arr) {
        auto effect = ev.getAsString();
        if (!effect)
          return planError("[spec.transition_effect] lifecycle transition '" +
                           name + "' effects must be an array of strings");
        effects.push_back(effect->str());
      }
      std::vector<LifecycleTransitionGuardPolicy> guards;
      const json::Value *guardsValue = to->get("guards");
      if (!guardsValue)
        return planError("[spec.transition_guard] lifecycle transition '" +
                         name + "' is missing guards array");
      const json::Array *guardsArray = guardsValue->getAsArray();
      if (!guardsArray)
        return planError("[spec.transition_guard] lifecycle transition '" +
                         name + "' guards must be an array");
      for (const json::Value &gv : *guardsArray) {
        const json::Object *guard = gv.getAsObject();
        if (!guard)
          return planError("[spec.transition_guard] lifecycle transition '" +
                           name + "' guards must contain only objects");
        auto kind = guard->getString("kind");
        if (!kind)
          return planError("[spec.transition_guard] lifecycle transition '" +
                           name + "' guard kind must be a string");
        const json::Value *detailValue = guard->get("detail");
        std::string detail;
        if (detailValue) {
          auto detailString = detailValue->getAsString();
          if (!detailString)
            return planError("[spec.transition_guard] lifecycle transition '" +
                             name + "' guard detail must be a string");
          detail = detailString->str();
        }
        guards.push_back({kind->str(), std::move(detail)});
      }
      std::optional<LifecycleTransitionEvidencePolicy> evidence;
      if (const json::Value *evidenceValue = to->get("evidence")) {
        if (!evidenceValue->getAsNull()) {
          const json::Object *evidenceObject = evidenceValue->getAsObject();
          if (!evidenceObject)
            return planError(
                "[spec.transition_evidence] lifecycle transition '" + name +
                "' evidence must be null or an object");
          auto style = evidenceObject->getString("style");
          if (!style)
            return planError(
                "[spec.transition_evidence] lifecycle transition '" + name +
                "' evidence style must be a string");
          auto chained = evidenceObject->getBoolean("chained");
          if (!chained)
            return planError(
                "[spec.transition_evidence] lifecycle transition '" + name +
                "' evidence chained must be a boolean");
          evidence = LifecycleTransitionEvidencePolicy{style->str(), *chained};
        }
      }
      in.lifecycleTransitions.push_back(
          {std::move(name), to->getString("from").value_or("").str(),
           to->getString("to").value_or("").str(), std::move(effects),
           std::move(guards), to->getString("idempotency").value_or("").str(),
           std::move(evidence)});
    }
  }

  return assemblePlan(std::move(in));
}

} // namespace neutrino
