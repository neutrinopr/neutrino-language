// SPDX-License-Identifier: Apache-2.0
//===- CoordinationEvalTest.cpp - the reference evaluator's semantics -----===//
//
// Direct C++ assertions on the one deterministic reference evaluator ():
// authorization, guarded ledger deltas, per-(ledger,party,currency) account
// identity, attestation gating, replay/idempotency, terminal-state rejection,
// totality (unknown kind / malformed operand / negative money / balance
// overflow all refuse), atomic rollback, and mutation sensitivity. These are
// the state-machine cases the target's happy-path lit fixture cannot express
// (the Scenario has no authorization / attestation / prior-state input); here
// we construct the transition input directly. The evaluator runs over a
// hand-built CoordinationPlan, so no MLIRContext / view is needed.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationEval.h"
#include "Neutrino/CoordinationEnvelope.h"
#include "Neutrino/Expr.h"

#include "gtest/gtest.h"

#include <limits>

using namespace neutrino;

namespace {

// A comparison guard `<a> <op> <b>` over two vars (untyped — evalGuard needs
// only the structure + operator, not the  dtype).
ExprPtr cmpGuard(const char *op, const char *a, const char *b) {
  auto n = std::make_unique<ExprNode>();
  n->kind = ExprNode::Cmp;
  n->name = op;
  n->lhs = std::make_unique<ExprNode>();
  n->lhs->kind = ExprNode::Var;
  n->lhs->name = a;
  n->rhs = std::make_unique<ExprNode>();
  n->rhs->kind = ExprNode::Var;
  n->rhs->name = b;
  return n;
}

PlanEffect eff(const char *name, const char *kind, const char *ledger,
               const char *amount, const char *party = "ref:payer") {
  PlanEffect e;
  e.name = name;
  e.kind = kind;
  e.ledger = ledger;
  e.amount = amount;
  e.currency = "ref:currency";
  e.party = party;
  return e;
}

// A balanced coordination: an unconditional (debit,credit) pair plus a guarded
// (debit,credit) pair keyed on `amount >= threshold`, all moving `amount`.
// Built fresh each call (the guard ExprPtr is move-only).
CoordinationPlan baseCoordinationPlan() {
  CoordinationPlan p;
  p.procedure = "probe";
  p.workflowKey = "flow_id";
  p.balanced = true;
  p.replay.key = "flow_id";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  // Declared, typed input inventory — the execution-claim payload is built from
  // this (not the raw transition maps), so `amount` participates in the claim.
  p.inputs = {{"flow_id", "string"}, {"payer", "party"},
              {"payee", "party"},    {"amount", "money"},
              {"threshold", "money"}, {"currency", "currency"}};
  p.effects.push_back(eff("pay_out", "debit", "a.src", "ref:amount"));
  p.effects.push_back(
      eff("pay_in", "credit", "b.dst", "ref:amount", "ref:payee"));
  PlanEffect bo = eff("bonus_out", "debit", "a.src", "ref:amount");
  bo.guard = cmpGuard(">=", "amount", "threshold");
  p.effects.push_back(std::move(bo));
  PlanEffect bi = eff("bonus_in", "credit", "b.dst", "ref:amount", "ref:payee");
  bi.guard = cmpGuard(">=", "amount", "threshold");
  p.effects.push_back(std::move(bi));
  return p;
}

// The standard invocation input: numeric amount/threshold + the symbolic party,
// currency, and workflow-key tokens the operands resolve through.
TransitionInput input(long long amount, long long threshold,
                      const char *key = "F-1") {
  TransitionInput in;
  in.numeric["amount"] = amount;
  in.numeric["threshold"] = threshold;
  in.symbols["flow_id"] = key;
  in.symbols["payer"] = "buyer-1";
  in.symbols["payee"] = "seller-1";
  in.symbols["currency"] = "EUR";
  in.authorized = true;
  return in;
}

long long bal(const EvalState &s, const char *ledger, const char *party,
              const char *currency = "EUR") {
  auto it = s.balances.find(Account{ledger, party, currency});
  return it == s.balances.end() ? 0 : it->second;
}

ExprPtr var(const char *name) {
  auto n = std::make_unique<ExprNode>();
  n->kind = ExprNode::Var;
  n->name = name;
  return n;
}

ExprPtr num(long long v) {
  auto n = std::make_unique<ExprNode>();
  n->kind = ExprNode::Num;
  n->num = v;
  return n;
}

// A compute `name = a <op> b` (untyped — evalExpr walks the structure).
PlanCompute binCompute(const char *name, char op, const char *a,
                       const char *b) {
  PlanCompute c;
  c.name = name;
  c.category = "money";
  auto n = std::make_unique<ExprNode>();
  n->kind = ExprNode::Bin;
  n->op = op;
  n->lhs = var(a);
  n->rhs = var(b);
  c.expr = std::move(n);
  c.deps = {a, b};
  return c;
}

// A minimal one-effect coordination carrying a single compute `x = a <op> b`,
// so a compute-fold arithmetic fault refuses before any effect stages.
CoordinationPlan arithCoordinationPlan(char op) {
  CoordinationPlan p;
  p.procedure = "arith";
  p.workflowKey = "flow_id";
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  p.computes.push_back(binCompute("x", op, "a", "b"));
  p.effects.push_back(eff("d", "debit", "L", "literal:1"));
  return p;
}

TransitionInput arithInput(long long a, long long b) {
  TransitionInput in;
  in.numeric["a"] = a;
  in.numeric["b"] = b;
  in.symbols["flow_id"] = "F-1";
  in.symbols["payer"] = "buyer-1";
  in.symbols["currency"] = "EUR";
  return in;
}

bool hasKind(const TransitionResult &r, const char *kind) {
  for (const auto &v : r.trace)
    if (const auto *o = v.getAsObject())
      if (o->getString("kind").value_or("") == kind)
        return true;
  return false;
}

// The load-bearing consistency invariant: every `terminal` observation's state
// must be a status the next state actually records for some key (so the trace
// never claims a terminal the state disagrees with).
void expectTerminalsAgreeWithStatus(const TransitionResult &r) {
  for (const auto &v : r.trace)
    if (const auto *o = v.getAsObject())
      if (o->getString("kind").value_or("") == "terminal") {
        std::string ts = o->getString("state").value_or("").str();
        bool found = false;
        for (const auto &kv : r.next.keyStatus)
          if (kv.second == ts)
            found = true;
        EXPECT_TRUE(found) << "terminal " << ts << " not in keyStatus";
      }
}

} // namespace

TEST(CoordinationEval, GuardedEffectsFireAndBalance) {
  // amount (1000) >= threshold (500): all four legs fire, conserving value.
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  // pay_out -1000, bonus_out -1000 => (a.src, buyer-1, EUR) = -2000.
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"), -2000);
  EXPECT_EQ(bal(r.next, "b.dst", "seller-1"), 2000);
  EXPECT_EQ(r.next.postedKeys.count("F-1"), 1u);
  EXPECT_EQ(r.next.keyStatus.at("F-1"), "CLOSED"); // advanced to its terminal
}

TEST(CoordinationEval, GuardFalseSuppressesGuardedLegs) {
  // amount (100) < threshold (500): only the unconditional pair posts.
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, input(100, 500));
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"), -100);
  EXPECT_EQ(bal(r.next, "b.dst", "seller-1"), 100);
}

TEST(CoordinationEval, DistinctPartiesOnSameLedgerStayDistinct) {
  // Two debits against the SAME ledger + currency but different parties must
  // not collapse into one balance, and their traces must be distinguishable.
  CoordinationPlan p;
  p.procedure = "split";
  p.workflowKey = "flow_id";
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  p.effects.push_back(eff("d1", "debit", "L", "literal:100", "ref:p1"));
  p.effects.push_back(eff("d2", "debit", "L", "literal:300", "ref:p2"));
  TransitionInput in;
  in.symbols["flow_id"] = "F-1";
  in.symbols["p1"] = "alice";
  in.symbols["p2"] = "bob";
  in.symbols["currency"] = "EUR";
  TransitionResult r = evaluateTransition(p, EvalState{}, in);
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  EXPECT_EQ(bal(r.next, "L", "alice"), -100);
  EXPECT_EQ(bal(r.next, "L", "bob"), -300);
  const std::string text = transitionToText(r);
  EXPECT_NE(text.find("\"alice\""), std::string::npos);
  EXPECT_NE(text.find("\"bob\""), std::string::npos);
}

TEST(CoordinationEval, AuthFailureRefusesWithoutMutation) {
  TransitionInput in = input(1000, 500);
  in.authorized = false;
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, in);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "auth.denied");
  EXPECT_TRUE(r.next.balances.empty()); // state unchanged
  EXPECT_TRUE(r.next.postedKeys.empty());
  EXPECT_TRUE(r.next.keyStatus.empty()); // not advanced — stays open
  // A refusal is not a state transition: no terminal observation claims
  // otherwise, and the (empty) status is consistent with that.
  EXPECT_FALSE(hasKind(r, "terminal"));
  expectTerminalsAgreeWithStatus(r);
}

TEST(CoordinationEval, AttestationGate) {
  auto gated = [] {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects[2].attestationInput = "ev"; // bonus_out
    p.effects[3].attestationInput = "ev"; // bonus_in
    return p;
  };
  // Rejected (policy absent from input) -> refused atomically, nothing posts.
  TransitionResult reject =
      evaluateTransition(gated(), EvalState{}, input(1000, 500));
  EXPECT_EQ(reject.outcome, Outcome::Refused);
  EXPECT_EQ(reject.refusalCode, "attestation.rejected");
  EXPECT_TRUE(reject.next.balances.empty());
  // Accepted -> all legs post.
  TransitionInput ok = input(1000, 500);
  ok.attestations["ev"] = true;
  TransitionResult accept = evaluateTransition(gated(), EvalState{}, ok);
  EXPECT_EQ(accept.outcome, Outcome::Terminal);
  EXPECT_EQ(bal(accept.next, "a.src", "buyer-1"), -2000);
}

// accepted(<input>) guard (): a quorum-acceptance predicate that SUPPRESSES
// its guarded legs (a balanced no-op) when unaccepted — distinct from the
// legacy atomic-refuse gate above.
static ExprPtr acceptedGuard(const char *input) {
  auto call = std::make_unique<ExprNode>();
  call->kind = ExprNode::Call;
  call->name = "accepted";
  auto arg = std::make_unique<ExprNode>();
  arg->kind = ExprNode::Var;
  arg->name = input;
  call->args.push_back(std::move(arg));
  return call;
}

// baseCoordinationPlan with the guarded bonus pair gated by accepted(ev) and an
// "ev" policy declared — a TEMPORAL coordination: an unconditional group (the
// pay pair) plus one accepted(ev) group (the bonus pair). The bonus group is
// required and stays PENDING until ev accepts.
static CoordinationPlan acceptedGatedCoordinationPlan() {
  CoordinationPlan p = baseCoordinationPlan();
  AttestationPolicy pol;
  pol.input = "ev";
  p.attestations.push_back(pol);
  p.effects[2].guard = acceptedGuard("ev"); // bonus_out
  p.effects[3].guard = acceptedGuard("ev"); // bonus_in
  // Normalization partitions effects into groups; hand-build the two groups the
  // temporal path commits over (group id = structural guardKey).
  PlanEffectGroup unc;
  unc.guardKey = "";
  unc.firstIndex = 0;
  unc.effectIndices = {0, 1};
  unc.mustBalance = true;
  unc.debitCount = 1;
  unc.creditCount = 1;
  PlanEffectGroup bonus;
  bonus.guardKey = "accepted:ev";
  bonus.firstIndex = 2;
  bonus.effectIndices = {2, 3};
  bonus.mustBalance = true;
  bonus.debitCount = 1;
  bonus.creditCount = 1;
  p.effectGroups = {unc, bonus};
  return p;
}

TEST(CoordinationEval, AcceptedGuardPostsGuardedLegsWhenAccepted) {
  TransitionInput in = input(1000, 500);
  in.attestations["ev"] = true; // quorum met
  TransitionResult r =
      evaluateTransition(acceptedGatedCoordinationPlan(), EvalState{}, in);
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  // Both groups commit; every required group is committed -> terminal.
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"), -2000);
  EXPECT_EQ(r.next.postedKeys.count("F-1"), 1u);
  EXPECT_EQ(r.next.committedGroups.at("F-1").size(), 2u);
}

TEST(CoordinationEval, UnacceptedGuardLeavesGroupPendingNotTerminal) {
  TransitionInput in = input(1000, 500);
  in.attestations["ev"] = false; // quorum NOT met (yet)
  TransitionResult r =
      evaluateTransition(acceptedGatedCoordinationPlan(), EvalState{}, in);
  // PENDING, not refused: the unconditional group commits (progress), the
  // accepted() bonus group awaits its quorum — so the coordination is OPEN, not
  // terminal, and the bonus legs have not posted.
  EXPECT_EQ(r.outcome, Outcome::Progress);
  EXPECT_NE(r.refusalCode, "attestation.rejected");
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"), -1000);
  EXPECT_TRUE(r.next.postedKeys.empty()); // not terminal
  EXPECT_EQ(r.next.committedGroups.at("F-1").count("accepted:ev"), 0u);
}

TEST(CoordinationEval, AcceptedGuardAbsentPolicyPendingNotMalformed) {
  // Absent from the attestation map = not accepted = the group stays pending
  // (the evidence.malformed refusal is reserved for evidence-only, ).
  TransitionResult r = evaluateTransition(acceptedGatedCoordinationPlan(),
                                          EvalState{}, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Progress);
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"), -1000);
  EXPECT_TRUE(r.next.postedKeys.empty());
}

// A purely per-policy temporal coordination: two independent accepted() groups
// (alpha, beta), no unconditional group — so BOTH must accept to reach terminal.
static CoordinationPlan twoPolicyPlan() {
  CoordinationPlan p;
  p.procedure = "settle";
  p.workflowKey = "flow_id";
  p.balanced = true;
  p.replay.key = "flow_id";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  p.inputs = {{"flow_id", "string"},
              {"payer", "party"},
              {"payee", "party"},
              {"amount", "money"},
              {"currency", "currency"}};
  AttestationPolicy a;
  a.input = "alpha";
  p.attestations.push_back(a);
  AttestationPolicy b;
  b.input = "beta";
  p.attestations.push_back(b);
  PlanEffect ad = eff("alpha_debit", "debit", "a.alpha", "ref:amount");
  ad.guard = acceptedGuard("alpha");
  PlanEffect ac = eff("alpha_credit", "credit", "b.alpha", "ref:amount", "ref:payee");
  ac.guard = acceptedGuard("alpha");
  PlanEffect bd = eff("beta_debit", "debit", "a.beta", "ref:amount");
  bd.guard = acceptedGuard("beta");
  PlanEffect bc = eff("beta_credit", "credit", "b.beta", "ref:amount", "ref:payee");
  bc.guard = acceptedGuard("beta");
  p.effects.push_back(std::move(ad));
  p.effects.push_back(std::move(ac));
  p.effects.push_back(std::move(bd));
  p.effects.push_back(std::move(bc));
  PlanEffectGroup ga;
  ga.guardKey = "accepted:alpha";
  ga.firstIndex = 0;
  ga.effectIndices = {0, 1};
  ga.mustBalance = true;
  ga.debitCount = 1;
  ga.creditCount = 1;
  PlanEffectGroup gb;
  gb.guardKey = "accepted:beta";
  gb.firstIndex = 2;
  gb.effectIndices = {2, 3};
  gb.mustBalance = true;
  gb.debitCount = 1;
  gb.creditCount = 1;
  p.effectGroups = {ga, gb};
  return p;
}

static TransitionInput twoPolicyInput(bool alpha, bool beta,
                                      const char *key = "K-1",
                                      long long amount = 1000) {
  TransitionInput in;
  in.symbols["flow_id"] = key;
  in.symbols["payer"] = "P";
  in.symbols["payee"] = "Q";
  in.symbols["currency"] = "EUR";
  in.numeric["amount"] = amount;
  in.attestations["alpha"] = alpha;
  in.attestations["beta"] = beta;
  in.authorized = true;
  return in;
}

TEST(CoordinationEval, TemporalEarlyAlphaThenLateBeta) {
  CoordinationPlan p = twoPolicyPlan();
  // T1: only alpha accepted — alpha commits, beta pending, NOT terminal.
  TransitionResult t1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, false));
  EXPECT_EQ(t1.outcome, Outcome::Progress);
  EXPECT_TRUE(t1.next.postedKeys.empty());
  EXPECT_EQ(t1.next.committedGroups.at("K-1").count("accepted:alpha"), 1u);
  EXPECT_EQ(t1.next.committedGroups.at("K-1").count("accepted:beta"), 0u);
  EXPECT_EQ(bal(t1.next, "a.alpha", "P"), -1000);
  EXPECT_EQ(bal(t1.next, "a.beta", "P"), 0);
  // T2: beta now accepts — beta commits, alpha is NOT replayed, now terminal.
  TransitionResult t2 =
      evaluateTransition(p, t1.next, twoPolicyInput(true, true));
  EXPECT_EQ(t2.outcome, Outcome::Terminal);
  EXPECT_EQ(t2.next.postedKeys.count("K-1"), 1u);
  EXPECT_EQ(t2.next.committedGroups.at("K-1").size(), 2u);
  EXPECT_EQ(bal(t2.next, "a.alpha", "P"), -1000); // posted exactly once
  EXPECT_EQ(bal(t2.next, "a.beta", "P"), -1000);
}

TEST(CoordinationEval, TemporalReverseOrderBetaThenAlpha) {
  CoordinationPlan p = twoPolicyPlan();
  TransitionResult t1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(false, true));
  EXPECT_EQ(t1.outcome, Outcome::Progress);
  EXPECT_TRUE(t1.next.postedKeys.empty());
  EXPECT_EQ(t1.next.committedGroups.at("K-1").count("accepted:beta"), 1u);
  TransitionResult t2 =
      evaluateTransition(p, t1.next, twoPolicyInput(true, true));
  EXPECT_EQ(t2.outcome, Outcome::Terminal);
  EXPECT_EQ(t2.next.postedKeys.count("K-1"), 1u);
  EXPECT_EQ(bal(t2.next, "a.alpha", "P"), -1000);
  EXPECT_EQ(bal(t2.next, "a.beta", "P"), -1000);
}

TEST(CoordinationEval, TemporalMixedAcceptanceIsNoProgress) {
  CoordinationPlan p = twoPolicyPlan();
  TransitionResult t1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, false));
  ASSERT_EQ(t1.outcome, Outcome::Progress);
  // T2: nothing new can commit (alpha already done, beta still unaccepted).
  TransitionResult t2 =
      evaluateTransition(p, t1.next, twoPolicyInput(true, false));
  EXPECT_EQ(t2.outcome, Outcome::NoProgress);
  EXPECT_EQ(bal(t2.next, "a.alpha", "P"), -1000); // no double post
  EXPECT_TRUE(t2.next.postedKeys.empty());
}

TEST(CoordinationEval, TemporalDuplicateReplayAfterTerminal) {
  CoordinationPlan p = twoPolicyPlan();
  TransitionResult t1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, true));
  ASSERT_EQ(t1.next.postedKeys.count("K-1"), 1u); // terminal
  // Re-presenting the terminal key is a clean replay, no double post.
  TransitionResult t2 =
      evaluateTransition(p, t1.next, twoPolicyInput(true, true));
  EXPECT_EQ(t2.outcome, Outcome::Replayed);
  EXPECT_EQ(bal(t2.next, "a.alpha", "P"), -1000);
  EXPECT_EQ(bal(t2.next, "a.beta", "P"), -1000);
}

TEST(CoordinationEval, TemporalChangedPayloadRefusesClaimMismatch) {
  CoordinationPlan p = twoPolicyPlan();
  TransitionResult t1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, false, "K-1", 1000));
  ASSERT_EQ(t1.outcome, Outcome::Progress);
  // A later transition on the same key with a DIFFERENT amount is not the same
  // instance — inputs are immutable per key ().
  TransitionResult t2 = evaluateTransition(
      p, t1.next, twoPolicyInput(true, true, "K-1", 2000));
  EXPECT_EQ(t2.outcome, Outcome::Refused);
  EXPECT_EQ(t2.refusalCode, "claim.mismatch");
  EXPECT_EQ(bal(t2.next, "a.alpha", "P"), -1000); // unchanged
}

TEST(CoordinationEval, TemporalCrossKeyIsolation) {
  CoordinationPlan p = twoPolicyPlan();
  // Key K-1 commits alpha; key K-2 (a distinct instance) commits alpha against
  // the same state — the commit ledgers are independent.
  TransitionResult k1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, false, "K-1"));
  TransitionResult k2 =
      evaluateTransition(p, k1.next, twoPolicyInput(true, false, "K-2"));
  EXPECT_EQ(k2.outcome, Outcome::Progress);
  EXPECT_EQ(k2.next.committedGroups.at("K-1").size(), 1u);
  EXPECT_EQ(k2.next.committedGroups.at("K-2").size(), 1u);
  EXPECT_EQ(k2.next.committedGroups.at("K-1").count("accepted:beta"), 0u);
  EXPECT_TRUE(k2.next.postedKeys.empty()); // neither is terminal
}

TEST(CoordinationEval, TemporalTerminalKeyDoesNotLeakToPartialKey) {
  // Per-key terminal (the P1.1 case): K1 completes, then K2 partially commits —
  // K2 stays OPEN (no keyStatus) while K1 remains terminal, then K2 completes.
  CoordinationPlan p = twoPolicyPlan();
  TransitionResult k1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, true, "K1"));
  ASSERT_EQ(k1.outcome, Outcome::Terminal);
  ASSERT_EQ(k1.next.keyStatus.at("K1"), "CLOSED");

  TransitionResult k2a =
      evaluateTransition(p, k1.next, twoPolicyInput(true, false, "K2"));
  EXPECT_EQ(k2a.outcome, Outcome::Progress);
  EXPECT_EQ(k2a.next.keyStatus.count("K2"), 0u);      // K2 is NOT terminal
  EXPECT_EQ(k2a.next.keyStatus.at("K1"), "CLOSED");   // K1 unchanged
  EXPECT_EQ(k2a.next.postedKeys.count("K2"), 0u);

  TransitionResult k2b =
      evaluateTransition(p, k2a.next, twoPolicyInput(true, true, "K2"));
  EXPECT_EQ(k2b.outcome, Outcome::Terminal);
  EXPECT_EQ(k2b.next.keyStatus.at("K2"), "CLOSED");
}

TEST(CoordinationEval, TemporalCommittedGroupsWithoutClaimIsInvalid) {
  // A reconstructed partial state with committed groups but NO claim could
  // splice an already-posted group onto a different payload — refuse.
  CoordinationPlan p = twoPolicyPlan();
  EvalState bad;
  bad.committedGroups["K-1"].insert("accepted:alpha"); // committed, no keyClaim
  TransitionResult r =
      evaluateTransition(p, bad, twoPolicyInput(false, true, "K-1"));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "state.invalid");
}

TEST(CoordinationEval, TemporalUnknownCommittedGroupIsInvalid) {
  // A committed group id that is not a real group of this coordination is an
  // invalid state — refuse before interpreting the ledger.
  CoordinationPlan p = twoPolicyPlan();
  TransitionResult t1 =
      evaluateTransition(p, EvalState{}, twoPolicyInput(true, false, "K-1"));
  ASSERT_EQ(t1.outcome, Outcome::Progress);
  EvalState tampered = t1.next; // valid claim + committed alpha
  tampered.committedGroups["K-1"].insert("accepted:ghost"); // inject a fake group
  TransitionResult r =
      evaluateTransition(p, tampered, twoPolicyInput(true, false, "K-1"));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "state.invalid");
}

TEST(CoordinationEval, ReplayIsIdempotentNoOp) {
  // Establish the committed key by a real first commit (so it carries its
  // claim), then re-present the SAME payload: a clean no-op, no double post.
  TransitionResult first =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, input(1000, 500));
  ASSERT_EQ(first.outcome, Outcome::Terminal);
  long long committed = bal(first.next, "a.src", "buyer-1");
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), first.next, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Replayed);
  EXPECT_EQ(r.refusalCode, ""); // a clean no-op, not a refusal
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"),
            committed); // unchanged — no double post
  EXPECT_NE(transitionToText(r).find("\"CLOSED\""), std::string::npos);
}

TEST(CoordinationEnvelope, ClaimIsOrderIdentityKeyCategoryAndValueSensitive) {
  std::vector<ExecutionInput> a = {{"amount", "money", "1000"},
                                   {"payer", "party", "A"}};
  std::vector<ExecutionInput> reordered = {{"payer", "party", "A"},
                                           {"amount", "money", "1000"}};
  std::vector<ExecutionInput> changedVal = {{"amount", "money", "1001"},
                                            {"payer", "party", "A"}};
  std::vector<ExecutionInput> changedCat = {{"amount", "number", "1000"},
                                            {"payer", "party", "A"}};
  EXPECT_EQ(executionClaimHash("C", "K", a),
            executionClaimHash("C", "K", reordered));
  EXPECT_NE(executionClaimHash("C", "K", a),
            executionClaimHash("C", "K", changedVal));
  EXPECT_NE(executionClaimHash("C", "K", a),
            executionClaimHash("C", "K", changedCat)); // the type tag is bound
  EXPECT_NE(executionClaimHash("C", "K", a),
            executionClaimHash("C", "K2", a)); // key-separated
  EXPECT_NE(executionClaimHash("C", "K", a),
            executionClaimHash("C2", "K", a)); // coordination-separated
}

TEST(CoordinationEnvelope, ClaimDigestIsPinned) {
  // A fixed expected digest so a rail reimplementing the framing/hash cannot
  // silently drift (order-independence alone would not catch that).
  std::vector<ExecutionInput> in = {{"amount", "money", "1000"},
                                    {"flow_id", "string", "F-1"}};
  EXPECT_EQ(
      executionClaimHash("coord-id", "F-1", in),
      "f08e38690b06cf6770ea204af8ce6039c6b990aca51d6702e0df119e35632325");
}

TEST(CoordinationEval, CommitRecordsExecutionClaimForKey) {
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, input(1000, 500));
  ASSERT_EQ(r.outcome, Outcome::Terminal);
  ASSERT_TRUE(r.next.keyClaim.count("F-1"));
  EXPECT_FALSE(r.next.keyClaim.at("F-1").empty());
}

TEST(CoordinationEval, ClaimIsScopedToCoordinationIdentity) {
  // Same key + payload, DIFFERENT coordination -> a different claim, so
  // acceptance for one coordination can never authorize another.
  CoordinationPlan a = baseCoordinationPlan();
  CoordinationPlan b = baseCoordinationPlan();
  b.procedure = "other_probe";
  TransitionResult ra = evaluateTransition(a, EvalState{}, input(1000, 500));
  TransitionResult rb = evaluateTransition(b, EvalState{}, input(1000, 500));
  ASSERT_EQ(ra.outcome, Outcome::Terminal);
  ASSERT_EQ(rb.outcome, Outcome::Terminal);
  EXPECT_NE(ra.next.keyClaim.at("F-1"), rb.next.keyClaim.at("F-1"));
}

TEST(CoordinationEnvelope, CoordinationIdentityBindsSemanticCore) {
  // A behavior-changing mutation to ANY part of the normalized semantic core
  // must change the identity — else two coordinations that execute differently
  // could share one identity (cross-coordination authorization).
  const std::string id = coordinationIdentityHash(baseCoordinationPlan());
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.procedure = "other";
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.terminal.aborted = "GONE"; // a non-success terminal is semantic too
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.replay.idempotent = false; // replay semantics
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.inputs.push_back({"extra", "money"}); // input inventory
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects[0].ledger = "z.other"; // a posting identity
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects[2].guard = cmpGuard(">", "amount", "threshold"); // guard structure
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    PlanCompute c;
    c.name = "k";
    c.category = "number";
    p.computes.push_back(std::move(c)); // a compute
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
  {
    CoordinationPlan p = baseCoordinationPlan();
    AttestationPolicy a;
    a.input = "proof";
    a.quorum = 2;
    a.observerSet = "o";
    a.timeout = "PT1H"; // a policy field (timeout/fallback/etc.)
    p.attestations.push_back(a);
    EXPECT_NE(id, coordinationIdentityHash(p));
  }
}

TEST(CoordinationEnvelope, CoordinationIdentityDigestIsPinned) {
  // A fixed digest over a COMPREHENSIVE coordination (typed compute + guard +
  // effect group + lifecycle/replay + a full attestation policy) so the wire
  // encoding cannot drift and a rail can reproduce the identity byte-for-byte.
  CoordinationPlan p;
  p.procedure = "pinned";
  p.workflowKey = "k";
  p.explicitInstanceKey = "k";
  p.balanced = true;
  p.replay.key = "k";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  p.terminal.contested = "CONTESTED";
  p.inputs = {{"k", "string"}, {"amt", "money"}, {"proof", "evidence"}};
  {
    PlanCompute c;
    c.name = "dbl";
    c.category = "number";
    c.deps = {"amt"};
    auto e = std::make_unique<ExprNode>();
    e->kind = ExprNode::Bin;
    e->op = '+';
    e->lhs = std::make_unique<ExprNode>();
    e->lhs->kind = ExprNode::Var;
    e->lhs->name = "amt";
    e->rhs = std::make_unique<ExprNode>();
    e->rhs->kind = ExprNode::Num;
    e->rhs->num = 1;
    c.expr = std::move(e);
    p.computes.push_back(std::move(c));
  }
  {
    PlanEffect e = eff("d", "debit", "a.src", "ref:amt");
    e.guardKey = "cmp(amt>=zero)";
    e.attestationInput = "proof";
    e.guard = cmpGuard(">=", "amt", "zero");
    p.effects.push_back(std::move(e));
  }
  {
    PlanEffectGroup g;
    g.guardKey = "cmp(amt>=zero)";
    g.attestationInput = "proof";
    g.mustBalance = true;
    g.debitCount = 1;
    g.creditCount = 1;
    p.effectGroups.push_back(g);
  }
  {
    AttestationPolicy a;
    a.input = "proof";
    a.quorum = 2;
    a.observerSet = "obs";
    a.observerRole = "role";
    a.canonicalization = "exact";
    a.timeout = "PT1H";
    a.fallback = "abort";
    a.assurance = "A2";
    a.independence = "independent";
    p.attestations.push_back(a);
  }
  EXPECT_EQ(
      coordinationIdentityHash(p),
      "a2d36719eec002a21b43e9ccf723b8f793e0a012c272eef5c8077284167ff2ba");
}

TEST(CoordinationEval, AmbiguousDuplicateInputRefuses) {
  // A declared numeric input ALSO present in the symbol map is ambiguous — two
  // rails could resolve it differently. Refuse rather than pick.
  TransitionInput dup = input(1000, 500);
  dup.symbols["amount"] = "1000"; // amount is a governed numeric declared input
  TransitionResult r = evaluateTransition(baseCoordinationPlan(), EvalState{}, dup);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "claim.input");
}

TEST(CoordinationEval, SymbolicInputAlsoInNumericMapRefuses) {
  // The converse: a governed symbolic input (party) also present numerically.
  TransitionInput dup = input(1000, 500);
  dup.numeric["payer"] = 7;
  TransitionResult r = evaluateTransition(baseCoordinationPlan(), EvalState{}, dup);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "claim.input");
}

TEST(CoordinationEval, GovernedNumericProvidedOnlySymbolicallyRefuses) {
  // A money input provided only in the symbol map is a type conflict.
  TransitionInput bad = input(1000, 500);
  bad.numeric.erase("amount");
  bad.symbols["amount"] = "1000";
  TransitionResult r = evaluateTransition(baseCoordinationPlan(), EvalState{}, bad);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "claim.input");
}

TEST(CoordinationEval, UndeclaredExtraInputIsExcludedFromClaim) {
  // An input not in the declared inventory does not enter the claim — the claim
  // is identical with or without it.
  TransitionResult base =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, input(1000, 500));
  TransitionInput extra = input(1000, 500);
  extra.numeric["undeclared_extra"] = 999;
  TransitionResult withExtra =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, extra);
  ASSERT_EQ(base.outcome, Outcome::Terminal);
  ASSERT_EQ(withExtra.outcome, Outcome::Terminal);
  EXPECT_EQ(base.next.keyClaim.at("F-1"), withExtra.next.keyClaim.at("F-1"));
}

TEST(CoordinationEval, PostedKeyWithoutClaimIsStateInvalid) {
  // A posted key MUST carry the claim established at its commit; a posted key
  // with no recorded claim is inconsistent — refuse, do not permit a payload
  // replay (fail closed).
  EvalState state;
  state.postedKeys.insert("F-1");
  state.keyStatus["F-1"] = "CLOSED";
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), state, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "state.invalid");
}

TEST(CoordinationEval, ReplayChangedPayloadRefusesClaimMismatch) {
  // A re-post on the SAME key with a DIFFERENT payload (amount) is not the same
  // operation — inputs are immutable per workflow key (), so one instance
  // can never combine two payloads. Refused, state unchanged.
  TransitionResult first =
      evaluateTransition(baseCoordinationPlan(), EvalState{}, input(1000, 500));
  ASSERT_EQ(first.outcome, Outcome::Terminal);
  EvalState before = first.next;
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), before, input(999999, 500));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "claim.mismatch");
  EXPECT_EQ(r.next.postedKeys, before.postedKeys);
  EXPECT_EQ(r.next.keyStatus, before.keyStatus);
  // No double post: the committed balance is untouched by the refused re-post.
  EXPECT_EQ(bal(r.next, "a.src", "buyer-1"), bal(before, "a.src", "buyer-1"));
}

TEST(CoordinationEval, NewKeyOnTerminalStateIsIndependentInstance) {
  // Terminal status is PER KEY: a NEW key on a state where another key (F-1) is
  // terminal is a distinct instance and commits independently — it is not
  // blocked by F-1's terminal (cross-key isolation).
  EvalState state;
  state.postedKeys.insert("F-1");
  state.keyStatus["F-1"] = "CLOSED";
  state.keyClaim["F-1"] = "prior-claim";
  TransitionResult r = evaluateTransition(baseCoordinationPlan(), state,
                                          input(1000, 500, "F-9"));
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  EXPECT_EQ(r.next.postedKeys.count("F-9"), 1u);
  EXPECT_EQ(r.next.postedKeys.count("F-1"), 1u); // F-1 untouched
  EXPECT_EQ(r.next.keyStatus.at("F-9"), "CLOSED");
}

TEST(CoordinationEval, UnresolvedOperandRefusesBeforeMutation) {
  // A later leg references a value absent from the env: validation fails BEFORE
  // the commit, so the earlier legs' would-be deltas never apply (atomicity).
  CoordinationPlan p = baseCoordinationPlan();
  p.effects.push_back(eff("bad", "debit", "a.src", "ref:missing"));
  TransitionResult r = evaluateTransition(p, EvalState{}, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "operand.unresolved");
  EXPECT_TRUE(r.next.balances.empty()); // atomic rollback: nothing posted
}

TEST(CoordinationEval, UnknownEffectKindRefused) {
  CoordinationPlan p = baseCoordinationPlan();
  p.effects[0].kind = "transfer"; // not debit|credit
  TransitionResult r = evaluateTransition(p, EvalState{}, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "effect.kind");
  EXPECT_TRUE(r.next.balances.empty());
}

TEST(CoordinationEval, MalformedAndNegativeOperandsRefused) {
  // A malformed operand identity (no kind:value form) refuses.
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects[0].amount = "garbage";
    TransitionResult r = evaluateTransition(p, EvalState{}, input(1000, 500));
    EXPECT_EQ(r.refusalCode, "operand.malformed");
    EXPECT_TRUE(r.next.balances.empty());
  }
  // A negative money literal (incl. LLONG_MIN) refuses before any negation UB.
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects[0].amount = "literal:-9223372036854775808"; // LLONG_MIN
    TransitionResult r = evaluateTransition(p, EvalState{}, input(1000, 500));
    EXPECT_EQ(r.refusalCode, "amount.negative");
    EXPECT_TRUE(r.next.balances.empty());
  }
}

TEST(CoordinationEval, BalanceOverflowRefusesWithoutMutation) {
  CoordinationPlan p;
  p.procedure = "of";
  p.workflowKey = "flow_id";
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  p.effects.push_back(eff("c", "credit", "L", "literal:1", "ref:payer"));
  EvalState state;
  state.balances[Account{"L", "buyer-1", "EUR"}] =
      std::numeric_limits<long long>::max();
  TransitionInput in;
  in.symbols["flow_id"] = "F-1";
  in.symbols["payer"] = "buyer-1";
  in.symbols["currency"] = "EUR";
  TransitionResult r = evaluateTransition(p, state, in);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "balance.overflow");
  EXPECT_EQ(bal(r.next, "L", "buyer-1"),
            std::numeric_limits<long long>::max()); // unchanged
}

TEST(CoordinationEval, Deterministic) {
  // Same (coordinationPlan, state, input) -> byte-identical serialization.
  std::string a = transitionToText(evaluateTransition(
      baseCoordinationPlan(), EvalState{}, input(1000, 500)));
  std::string b = transitionToText(evaluateTransition(
      baseCoordinationPlan(), EvalState{}, input(1000, 500)));
  EXPECT_EQ(a, b);
}

TEST(CoordinationEval, LedgerDeltaMutationsChangeTheTrace) {
  // The trace observes each ledger delta's order, multiplicity, and value, so a
  // drop / reorder / duplicate / change of a delta perturbs the serialization.
  const std::string base = transitionToText(evaluateTransition(
      baseCoordinationPlan(), EvalState{}, input(1000, 500)));

  // DROP the last effect.
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects.pop_back();
    EXPECT_NE(base, transitionToText(
                        evaluateTransition(p, EvalState{}, input(1000, 500))));
  }
  // REORDER: swap the first two effects.
  {
    CoordinationPlan p = baseCoordinationPlan();
    std::swap(p.effects[0], p.effects[1]);
    EXPECT_NE(base, transitionToText(
                        evaluateTransition(p, EvalState{}, input(1000, 500))));
  }
  // DUPLICATE the first effect.
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects.push_back(eff("pay_out", "debit", "a.src", "ref:amount"));
    EXPECT_NE(base, transitionToText(
                        evaluateTransition(p, EvalState{}, input(1000, 500))));
  }
  // CHANGE a delta's amount operand (ref:amount -> literal:1).
  {
    CoordinationPlan p = baseCoordinationPlan();
    p.effects[0].amount = "literal:1";
    EXPECT_NE(base, transitionToText(
                        evaluateTransition(p, EvalState{}, input(1000, 500))));
  }
}

TEST(CoordinationEval, CheckedComputeArithmeticRefuses) {
  const long long MAX = std::numeric_limits<long long>::max();
  const long long MIN = std::numeric_limits<long long>::min();
  struct Case {
    char op;
    long long a, b;
    const char *code;
  };
  // Each arithmetic fault in a compute fold is a coded refusal (not host UB),
  // taken before any effect stages — the input state stays empty.
  for (const Case &c :
       {Case{'+', MAX, 1, "expr.overflow"}, Case{'-', MIN, 1, "expr.overflow"},
        Case{'*', MAX, 2, "expr.overflow"},
        Case{'/', 10, 0, "expr.divide_by_zero"},
        Case{'/', MIN, -1, "expr.overflow"}}) {
    TransitionResult r = evaluateTransition(arithCoordinationPlan(c.op),
                                            EvalState{}, arithInput(c.a, c.b));
    EXPECT_EQ(r.outcome, Outcome::Refused) << c.op;
    EXPECT_EQ(r.refusalCode, c.code) << c.op;
    EXPECT_TRUE(r.next.balances.empty()) << c.op;
    EXPECT_FALSE(hasKind(r, "terminal")) << c.op;
  }
}

TEST(CoordinationEval, CheckedGuardArithmeticRefuses) {
  // The same checked arithmetic guards a GUARD operand: `(a / b) > 0` with b ==
  // 0 refuses before staging rather than trapping.
  CoordinationPlan p;
  p.procedure = "gof";
  p.workflowKey = "flow_id";
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  PlanEffect e = eff("d", "debit", "L", "literal:1");
  auto cmp = std::make_unique<ExprNode>();
  cmp->kind = ExprNode::Cmp;
  cmp->name = ">";
  auto div = std::make_unique<ExprNode>();
  div->kind = ExprNode::Bin;
  div->op = '/';
  div->lhs = var("a");
  div->rhs = var("b");
  cmp->lhs = std::move(div);
  cmp->rhs = num(0);
  e.guard = std::move(cmp);
  p.effects.push_back(std::move(e));
  TransitionResult r = evaluateTransition(p, EvalState{}, arithInput(10, 0));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "expr.divide_by_zero");
  EXPECT_TRUE(r.next.balances.empty());
}

TEST(CoordinationEval, EmptyAccountComponentRefused) {
  // An empty ledger / party / currency posting-identity component is malformed.
  for (int which = 0; which < 3; ++which) {
    CoordinationPlan p = baseCoordinationPlan();
    if (which == 0)
      p.effects[0].ledger = "";
    else if (which == 1)
      p.effects[0].party = "literal:"; // empty party token
    else
      p.effects[0].currency = "literal:"; // empty currency token
    TransitionResult r = evaluateTransition(p, EvalState{}, input(1000, 500));
    EXPECT_EQ(r.outcome, Outcome::Refused) << which;
    EXPECT_EQ(r.refusalCode, "operand.malformed") << which;
    EXPECT_TRUE(r.next.balances.empty()) << which;
  }
}

TEST(CoordinationEval, ReplayFromInconsistentStateRefused) {
  // A posted key with an OPEN status is an inconsistent state — refused
  // state.invalid rather than fabricating a success terminal.
  EvalState state;
  state.postedKeys.insert("F-1");
  // posted key with no keyClaim: an inconsistent reconstructed state
  TransitionResult r =
      evaluateTransition(baseCoordinationPlan(), state, input(1000, 500));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "state.invalid");
  EXPECT_FALSE(hasKind(r, "terminal"));
}

TEST(CoordinationEval, TerminalObservationsAgreeWithNextStatus) {
  // Across commit, replay, and refusal, every terminal observation agrees with
  // nextState.status — the trace never claims a terminal the state disagrees
  // on.
  TransitionResult committed = evaluateTransition(
      baseCoordinationPlan(), EvalState{}, input(1000, 500));
  expectTerminalsAgreeWithStatus(committed);

  // Replay from the committed (terminal) state: the replay terminal obs agrees.
  expectTerminalsAgreeWithStatus(evaluateTransition(
      baseCoordinationPlan(), committed.next, input(1000, 500)));

  // A refusal appends no terminal observation at all.
  TransitionInput denied = input(1000, 500);
  denied.authorized = false;
  expectTerminalsAgreeWithStatus(
      evaluateTransition(baseCoordinationPlan(), EvalState{}, denied));
}

// ---- evidence-only coordination (no ledger effects) --------------------------

// An effectless evidence-acceptance coordination: one attestation policy on an
// evidence input, keyed on an explicit instance key, no debit/credit.
static CoordinationPlan evidenceOnlyCoordination() {
  CoordinationPlan p;
  p.procedure = "anchor";
  p.workflowKey = "claim_ref";
  p.explicitInstanceKey = "claim_ref";
  p.evidenceOnly = true;
  p.replay.key = "claim_ref";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "REJECTED";
  AttestationPolicy pol;
  pol.input = "proof";
  pol.quorum = 2;
  p.attestations.push_back(pol);
  return p;
}

static TransitionInput evidenceInput(bool accepted, const char *key = "C-1") {
  TransitionInput in;
  in.symbols["claim_ref"] = key;
  in.symbols["proof"] = "sha256:abcd";
  in.attestations["proof"] = accepted;
  in.authorized = true;
  return in;
}

static std::string kindAt(const TransitionResult &r, size_t i) {
  return r.trace[i].getAsObject()->getString("kind").value_or("").str();
}

TEST(CoordinationEval, EvidenceOnlyAcceptsWithZeroLedgerDelta) {
  TransitionResult r =
      evaluateTransition(evidenceOnlyCoordination(), EvalState{}, evidenceInput(true));
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  EXPECT_TRUE(r.next.balances.empty()); // no ledger movement
  EXPECT_EQ(r.next.keyStatus.at("C-1"), "CLOSED");
  EXPECT_EQ(r.next.postedKeys.count("C-1"), 1u);
  // Observations: authorization, attestation, acceptance event, terminal — and
  // no ledger-delta.
  bool sawAttestation = false, sawEvent = false, sawTerminal = false,
       sawLedger = false;
  for (size_t i = 0; i < r.trace.size(); ++i) {
    std::string k = kindAt(r, i);
    sawAttestation |= k == "attestation";
    sawEvent |= k == "event";
    sawTerminal |= k == "terminal";
    sawLedger |= k == "ledger-delta";
  }
  EXPECT_TRUE(sawAttestation);
  EXPECT_TRUE(sawEvent);
  EXPECT_TRUE(sawTerminal);
  EXPECT_FALSE(sawLedger);
}

TEST(CoordinationEval, EvidenceOnlyRejectsUnacceptedEvidence) {
  // Evidence presented but not accepted -> coded refusal, state unchanged.
  TransitionResult r =
      evaluateTransition(evidenceOnlyCoordination(), EvalState{}, evidenceInput(false));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "attestation.rejected");
  EXPECT_TRUE(r.next.balances.empty());
  EXPECT_TRUE(r.next.keyStatus.empty());          // rollback: no terminal
  EXPECT_TRUE(r.next.postedKeys.empty());      // rollback: key not posted
}

TEST(CoordinationEval, EvidenceOnlyRefusesMalformedEvidence) {
  // The evidence input is not presented at all -> malformed, refused.
  TransitionInput in = evidenceInput(true);
  in.attestations.erase("proof");
  TransitionResult r = evaluateTransition(evidenceOnlyCoordination(), EvalState{}, in);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "evidence.malformed");
  EXPECT_TRUE(r.next.postedKeys.empty());
}

TEST(CoordinationEval, EvidenceOnlyReplayIsIdempotent) {
  // The same instance already accepted -> idempotent replay, no re-acceptance.
  // Establish the committed instance first so it carries its execution claim.
  TransitionResult first = evaluateTransition(evidenceOnlyCoordination(),
                                              EvalState{}, evidenceInput(true));
  ASSERT_EQ(first.outcome, Outcome::Terminal);
  TransitionResult r = evaluateTransition(evidenceOnlyCoordination(), first.next,
                                          evidenceInput(true));
  EXPECT_EQ(r.outcome, Outcome::Replayed);
  EXPECT_EQ(r.next.keyStatus.at("C-1"), "CLOSED");
  EXPECT_EQ(r.next.postedKeys.count("C-1"), 1u);
}

TEST(CoordinationEval, EvidenceOnlyDistinctInstanceIsIndependent) {
  // A different instance key is a fresh coordination even if one is posted.
  EvalState posted;
  posted.postedKeys.insert("C-1");
  posted.keyStatus["C-1"] = "CLOSED";
  // A fresh state for the distinct key (the posted one is terminal only for
  // C-1); evaluate the distinct instance against open state.
  TransitionResult r = evaluateTransition(evidenceOnlyCoordination(), EvalState{},
                                          evidenceInput(true, "C-2"));
  EXPECT_EQ(r.outcome, Outcome::Terminal);
  EXPECT_EQ(r.next.postedKeys.count("C-2"), 1u);
}

TEST(CoordinationEval, EvidenceOnlyMissingKeyRefusesBeforeAcceptance) {
  // An unresolved instance key refuses before any attestation observation.
  TransitionInput in = evidenceInput(true);
  in.symbols.erase("claim_ref");
  TransitionResult r = evaluateTransition(evidenceOnlyCoordination(), EvalState{}, in);
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "key.unresolved");
}
