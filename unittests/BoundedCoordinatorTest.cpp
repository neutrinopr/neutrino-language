// SPDX-License-Identifier: Apache-2.0
//===- BoundedCoordinatorTest.cpp - bounded dynamic realization () ----===//
//
// Adversarial + property assertions on the shared bounded coordinator: it is
// trace-equivalent to the reference evaluator (S4), admission rejects an
// out-of-subset coordinationPlan BEFORE any state mutation, the
// statically-derived step / storage bounds are enforced at runtime, and
// instances are isolated (a transition on one cannot read or mutate another).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/BoundedCoordinator.h"
#include "Neutrino/Expr.h"
#include "Neutrino/TraceEquivalence.h"

#include "gtest/gtest.h"

using namespace neutrino;

namespace {

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
               const char *party) {
  PlanEffect e;
  e.name = name;
  e.kind = kind;
  e.ledger = ledger;
  e.amount = "ref:amount";
  e.currency = "ref:currency";
  e.party = party;
  return e;
}

// The fixed-subset coordinationPlan: one attested, guarded, balanced
// debit/credit pair.
CoordinationPlan settlementCoordinationPlan() {
  CoordinationPlan p;
  p.procedure = "settle";
  p.workflowKey = "sid";
  p.balanced = true;
  p.replay.key = "sid";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  AttestationPolicy pol;
  pol.input = "proof";
  p.attestations.push_back(pol);
  PlanEffect d = eff("payer_debit", "debit", "payer.wallet", "ref:payer");
  d.attestationInput = "proof";
  d.guard = cmpGuard(">=", "amount", "threshold");
  PlanEffect c = eff("payee_credit", "credit", "payee.wallet", "ref:payee");
  c.attestationInput = "proof";
  c.guard = cmpGuard(">=", "amount", "threshold");
  p.effects.push_back(std::move(d));
  p.effects.push_back(std::move(c));
  return p;
}

TransitionInput input(const char *key = "S-1", bool accepted = true,
                      long long amount = 1000) {
  TransitionInput in;
  in.numeric["amount"] = amount;
  in.numeric["threshold"] = 500;
  in.symbols["sid"] = key;
  in.symbols["payer"] = "payer-a";
  in.symbols["payee"] = "payee-b";
  in.symbols["currency"] = "EUR";
  in.attestations["proof"] = accepted;
  in.authorized = true;
  return in;
}

long long bal(const EvalState &s, const char *ledger, const char *party) {
  auto it = s.balances.find(Account{ledger, party, "EUR"});
  return it == s.balances.end() ? 0 : it->second;
}

} // namespace

TEST(BoundedCoordinator, AdmitsFixedSubsetAndDerivesBounds) {
  auto b = admitBounded(settlementCoordinationPlan());
  ASSERT_TRUE(static_cast<bool>(b));
  EXPECT_EQ(b->maxSteps, 11);       // 3 + 0 computes + 4*2 effects
  EXPECT_EQ(b->maxStorageSlots, 6); // 2 + 2*2 effects
}

TEST(BoundedCoordinator,
     AdmissionRejectsOversizedCoordinationPlanBeforeInstance) {
  CoordinationPlan p = settlementCoordinationPlan();
  for (int i = 0; i < kBoundedMaxEffects; ++i)
    p.effects.push_back(eff("extra", "debit", "x", "ref:payer"));
  auto b = admitBounded(p);
  EXPECT_FALSE(static_cast<bool>(b));
  EXPECT_NE(toString(b.takeError()).find("effect cap"), std::string::npos);
  // create() fails closed — no coordinator, so no instance can run.
  EXPECT_FALSE(static_cast<bool>(SharedCoordinator::create(p)));
}

TEST(BoundedCoordinator, AdmissionRejectsUnsupportedInstruction) {
  CoordinationPlan p = settlementCoordinationPlan();
  p.effects[0].kind = "mint"; // not in the supported {debit, credit}
  auto b = admitBounded(p);
  EXPECT_FALSE(static_cast<bool>(b));
  EXPECT_NE(toString(b.takeError()).find("unsupported effect kind"),
            std::string::npos);
}

TEST(BoundedCoordinator, TraceEquivalentToReferenceEvaluator) {
  CoordinationPlan p = settlementCoordinationPlan();
  auto coord = SharedCoordinator::create(p);
  ASSERT_TRUE(static_cast<bool>(coord));
  TransitionResult ref = evaluateTransition(p, EvalState{}, input());
  TransitionResult got = coord->run("S-1", input());
  TraceDivergence d =
      compareTraces(observedFromTransition(ref), observedFromTransition(got));
  EXPECT_FALSE(d.diverged) << d.field << " " << d.locator;
  EXPECT_EQ(got.outcome, Outcome::Terminal);
}

TEST(BoundedCoordinator, TamperedRealizationDiverges) {
  // The non-vacuity check: perturb the coordinator's observed trace and the S4
  // comparator must catch it.
  CoordinationPlan p = settlementCoordinationPlan();
  TransitionResult ref = evaluateTransition(p, EvalState{}, input());
  ObservedTrace tampered = observedFromTransition(ref);
  applyTamper(tampered, TamperKind::AlterAmount);
  EXPECT_TRUE(compareTraces(observedFromTransition(ref), tampered).diverged);
}

TEST(BoundedCoordinator, RuntimeStepBoundEnforced) {
  CoordinationPlan p = settlementCoordinationPlan();
  SharedCoordinator coord(p, BoundedBounds{/*maxSteps=*/2, /*slots=*/16});
  TransitionResult r = coord.run("S-1", input());
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "bounds.step_exceeded");
  EXPECT_TRUE(coord.stateOf("S-1")->keyStatus.empty()); // rolled back, nothing committed
}

TEST(BoundedCoordinator, RuntimeStorageBoundEnforced) {
  CoordinationPlan p = settlementCoordinationPlan();
  SharedCoordinator coord(p, BoundedBounds{/*maxSteps=*/32, /*slots=*/1});
  TransitionResult r = coord.run("S-1", input());
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "bounds.storage_exceeded");
}

TEST(BoundedCoordinator, InstancesAreIsolated) {
  CoordinationPlan p = settlementCoordinationPlan();
  auto coord = SharedCoordinator::create(p);
  ASSERT_TRUE(static_cast<bool>(coord));

  // Run instance A; B has never been touched.
  coord->run("A", input("A-1"));
  EXPECT_EQ(coord->stateOf("B"), nullptr);
  EXPECT_FALSE(coord->stateOf("A")->keyStatus.empty());
  EXPECT_EQ(bal(*coord->stateOf("A"), "payer.wallet", "payer-a"), -1000);

  // Run instance B on the SAME ledger/party — its balance is its OWN, not
  // combined with A's (a single shared EvalState would show -2000).
  coord->run("B", input("B-1"));
  EXPECT_EQ(bal(*coord->stateOf("B"), "payer.wallet", "payer-a"), -1000);
  EXPECT_EQ(bal(*coord->stateOf("A"), "payer.wallet", "payer-a"), -1000);
  EXPECT_EQ(coord->instanceCount(), 2);
}

TEST(BoundedCoordinator, ReplayWithinInstanceIsIdempotent) {
  CoordinationPlan p = settlementCoordinationPlan();
  auto coord = SharedCoordinator::create(p);
  ASSERT_TRUE(static_cast<bool>(coord));
  EXPECT_EQ(coord->run("A", input("A-1")).outcome, Outcome::Terminal);
  TransitionResult again = coord->run("A", input("A-1"));
  EXPECT_EQ(again.outcome, Outcome::Replayed);
  EXPECT_EQ(bal(*coord->stateOf("A"), "payer.wallet", "payer-a"), -1000);
}

TEST(BoundedCoordinator, AttestationRejectionRefusesWithoutMutation) {
  // Admission is topology/shape; a REJECTED evidence quorum refuses the
  // transition (the reference semantics) with no instance mutation.
  CoordinationPlan p = settlementCoordinationPlan();
  auto coord = SharedCoordinator::create(p);
  ASSERT_TRUE(static_cast<bool>(coord));
  TransitionResult r = coord->run("A", input("A-1", /*accepted=*/false));
  EXPECT_EQ(r.outcome, Outcome::Refused);
  EXPECT_EQ(r.refusalCode, "attestation.rejected");
  EXPECT_TRUE(coord->stateOf("A")->keyStatus.empty());
}
