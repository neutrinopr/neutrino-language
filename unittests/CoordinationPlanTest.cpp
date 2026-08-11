// SPDX-License-Identifier: Apache-2.0
//===- CoordinationPlanTest.cpp - assemblePlan normalization + checks -----===//
//
// Direct C++ assertions on the one normalization + verification seam ():
// assemblePlan resolves the workflow key, the effect->attestation binding, the
// per-group balance obligation, and the terminal projection, and fails BEFORE
// renderer dispatch on each malformed shape. The negatives here cannot be
// produced from valid MLIR (the dialect verifier rejects them first), so this
// tier guards the external-spec reconstruction path.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationPlan.h"

#include "llvm/Support/Error.h"
#include "gtest/gtest.h"

using namespace neutrino;

namespace {

LifecycleTransitionPolicy closeToClosed() {
  LifecycleTransitionPolicy close;
  close.name = "CLOSE";
  close.from = "OPEN";
  close.to = "CLOSED";
  close.idempotency = "reject";
  return close;
}

void addReachableClosedLifecycle(PlanInputs &in) {
  in.lifecycleInitialState = "OPEN";
  in.lifecycleStates = {"OPEN", "CLOSED"};
  in.lifecycleTransitions.push_back(closeToClosed());
}

// A minimal valid coordination: one balanced (debit,credit) pair keyed on "k",
// moving the same (amount, currency) so the group provably conserves value.
PlanInputs validBase() {
  PlanInputs in;
  in.procedure = "p";
  in.balanced = true;
  in.terminal.success = "CLOSED";
  addReachableClosedLifecycle(in);
  PlanEffectInput d;
  d.name = "pay";
  d.kind = "debit";
  d.idempotencyKind = "ref";
  d.idempotencyValue = "k";
  d.amount = "ref:amount";
  d.currency = "ref:currency";
  PlanEffectInput c;
  c.name = "settle";
  c.kind = "credit";
  c.idempotencyKind = "ref";
  c.idempotencyValue = "k";
  c.amount = "ref:amount";
  c.currency = "ref:currency";
  // PlanEffectInput owns a move-only guard ExprPtr, so build the vector by
  // move.
  in.effects.push_back(std::move(d));
  in.effects.push_back(std::move(c));
  return in;
}

// A fresh (debit, credit) pair moving `amount`/`currency`; for multi-leg tests.
PlanEffectInput leg(const char *name, const char *kind, const char *amount) {
  PlanEffectInput e;
  e.name = name;
  e.kind = kind;
  e.idempotencyKind = "ref";
  e.idempotencyValue = "k";
  e.amount = amount;
  e.currency = "ref:currency";
  return e;
}

AttestationPolicy policy(const std::string &input) {
  AttestationPolicy p;
  p.input = input;
  return p;
}

// A comparison guard `<a> <op> <b>` over two vars, for the semantic-key tests.
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

TEST(CoordinationPlan, SemanticKeyIsStructuralNotTextual) {
  // Two structurally-identical guards share a key regardless of source text;
  // a NULL guard keys to "".
  EXPECT_EQ(canonicalGuardKey(cmpGuard(">=", "amount", "threshold").get()),
            canonicalGuardKey(cmpGuard(">=", "amount", "threshold").get()));
  EXPECT_EQ(canonicalGuardKey(nullptr), "");
  EXPECT_EQ(canonicalGuardKey(cmpGuard(">=", "amount", "threshold").get()),
            "(>= $amount $threshold)");
}

TEST(CoordinationPlan, SemanticKeyDoesNotCommute) {
  // Counterexample proving the key is CONSERVATIVE: `a >= b` and the
  // algebraically-equal `b <= a` get DIFFERENT keys — the unsafe commutation is
  // NOT performed (it need not preserve meaning under rounding/overflow).
  EXPECT_NE(canonicalGuardKey(cmpGuard(">=", "a", "b").get()),
            canonicalGuardKey(cmpGuard("<=", "b", "a").get()));
}

std::string errMsg(llvm::Expected<CoordinationPlan> &&r) {
  EXPECT_FALSE(static_cast<bool>(r));
  return llvm::toString(r.takeError());
}

TEST(CoordinationPlan, ValidBaseNormalizes) {
  auto r = assemblePlan(validBase());
  ASSERT_TRUE(static_cast<bool>(r));
  EXPECT_EQ(r->workflowKey, "k");
  EXPECT_EQ(r->replay.key, "k");
  EXPECT_TRUE(r->replay.idempotent);
  ASSERT_EQ(r->effectGroups.size(), 1u);
  EXPECT_TRUE(r->effectGroups[0].mustBalance);
  EXPECT_EQ(r->effectGroups[0].debitCount, 1u);
  EXPECT_EQ(r->effectGroups[0].creditCount, 1u);
  EXPECT_EQ(r->terminal.success, "CLOSED");
}

TEST(CoordinationPlan, NoEffectsIsLenient) {
  // An effect-less procedure is a legitimate (non-renderable) spec; the plan
  // builds, the renderers reject it.
  PlanInputs in = validBase();
  in.effects.clear();
  auto r = assemblePlan(std::move(in));
  ASSERT_TRUE(static_cast<bool>(r));
  EXPECT_TRUE(r->effects.empty());
  EXPECT_EQ(r->workflowKey, "");
}

TEST(CoordinationPlan, AmbiguousWorkflowKeyFails) {
  PlanInputs in = validBase();
  in.effects[1].idempotencyValue = "other";
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("ambiguous workflow key"),
            std::string::npos);
}

TEST(CoordinationPlan, NonRefKeyFails) {
  PlanInputs in = validBase();
  in.effects[0].idempotencyKind = "literal";
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("must reference an input"),
            std::string::npos);
}

TEST(CoordinationPlan, UnbalancedGroupFails) {
  PlanInputs in = validBase();
  in.effects.pop_back(); // leave one debit, no matching credit
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("unbalanced guard group"),
            std::string::npos);
}

TEST(CoordinationPlan, MismatchedCurrencyFails) {
  // debit 100 EUR "balanced" by credit 1 USD: counts match but value does not.
  PlanInputs in = validBase();
  in.effects[0].amount = "literal:100";
  in.effects[0].currency = "literal:EUR";
  in.effects[1].amount = "literal:1";
  in.effects[1].currency = "literal:USD";
  EXPECT_NE(errMsg(assemblePlan(std::move(in)))
                .find("does not provably conserve value"),
            std::string::npos);
}

TEST(CoordinationPlan, MismatchedAmountFails) {
  // Same currency, different amount identity — not conserved.
  PlanInputs in = validBase();
  in.effects[0].amount = "ref:gross";
  in.effects[1].amount = "ref:net";
  EXPECT_NE(errMsg(assemblePlan(std::move(in)))
                .find("does not provably conserve value"),
            std::string::npos);
}

TEST(CoordinationPlan, MultiLegConservationHolds) {
  // Two debits + two credits with a matching (amount, currency) multiset.
  PlanInputs in;
  in.procedure = "p";
  in.balanced = true;
  in.terminal.success = "CLOSED";
  addReachableClosedLifecycle(in);
  in.effects.push_back(leg("pay", "debit", "ref:amount"));
  in.effects.push_back(leg("settle", "credit", "ref:amount"));
  in.effects.push_back(leg("fee_debit", "debit", "ref:fee"));
  in.effects.push_back(leg("fee_credit", "credit", "ref:fee"));
  EXPECT_TRUE(static_cast<bool>(assemblePlan(std::move(in))));
}

TEST(CoordinationPlan, UnbalancedGroupAllowedWhenNotBalanced) {
  PlanInputs in = validBase();
  in.balanced = false;
  in.effects.pop_back();
  EXPECT_TRUE(static_cast<bool>(assemblePlan(std::move(in))));
}

TEST(CoordinationPlan, SinglePolicyBindsEveryEffect) {
  PlanInputs in = validBase();
  in.attestations = {policy("evidence")};
  auto r = assemblePlan(std::move(in));
  ASSERT_TRUE(static_cast<bool>(r));
  for (const PlanEffect &e : r->effects)
    EXPECT_EQ(e.attestationInput, "evidence");
}

TEST(CoordinationPlan, MultiPolicyWithoutAcceptedLeavesUnbound) {
  // The plan does not guess a policy for a multi-policy spec — it leaves the
  // effects unbound; the single-policy render rule refuses such a spec
  // gracefully (capability-spec emission of both policies still succeeds).
  PlanInputs in = validBase();
  in.attestations = {policy("a"), policy("b")};
  auto r = assemblePlan(std::move(in));
  ASSERT_TRUE(static_cast<bool>(r));
  for (const PlanEffect &e : r->effects)
    EXPECT_EQ(e.attestationInput, "");
}

TEST(CoordinationPlan, AcceptedGuardSuppressesWithoutAtomicGate) {
  // accepted() effects () SUPPRESS via their guard — they do NOT set the
  // atomic-refuse attestationInput, and DIFFERENT policies per effect are now
  // allowed (real per-policy multi-policy binding). The referenced policy is
  // still verified declared.
  PlanInputs in = validBase();
  in.attestations = {policy("a"), policy("b")};
  in.effects[0].guardAcceptedInput = "a";
  in.effects[0].canonicalGuard = "accepted(a)";
  in.effects[1].guardAcceptedInput = "b";
  in.effects[1].canonicalGuard = "accepted(b)";
  auto r = assemblePlan(std::move(in));
  ASSERT_TRUE(static_cast<bool>(r));
  EXPECT_EQ(r->effects[0].attestationInput, "");
  EXPECT_EQ(r->effects[1].attestationInput, "");
}

TEST(CoordinationPlan, UndeclaredPolicyBindingFails) {
  PlanInputs in = validBase();
  in.attestations = {policy("a")};
  in.effects[0].guardAcceptedInput = "ghost"; // not a declared policy
  in.effects[0].canonicalGuard = "accepted(ghost)";
  EXPECT_NE(
      errMsg(assemblePlan(std::move(in))).find("undeclared attestation policy"),
      std::string::npos);
}

TEST(CoordinationPlan, UnboundPolicyInPerPolicyModeFailsCleanly) {
  // Regression for  at the shared normalization seam: two declared
  // policies, but a balanced pair bound only to `alpha`. Repeating the
  // rejection also exercises destruction of every owned PlanInputs member on
  // the error path; the result must remain an ordinary llvm::Error.
  for (int attempt = 0; attempt < 32; ++attempt) {
    PlanInputs in = validBase();
    in.attestations = {policy("alpha_proof"), policy("beta_proof")};
    in.lifecycleStates = {"OPEN", "CLOSED"};
    LifecycleTransitionPolicy transition;
    transition.name = "commit";
    transition.from = "OPEN";
    transition.to = "CLOSED";
    transition.effects = {"post"};
    transition.idempotency = "reject";
    in.lifecycleTransitions.push_back(std::move(transition));
    for (PlanEffectInput &effect : in.effects) {
      effect.guardAcceptedInput = "alpha_proof";
      effect.canonicalGuard = "accepted(alpha_proof)";
    }
    std::string msg = errMsg(assemblePlan(std::move(in)));
    EXPECT_NE(msg.find("[attest.policy.unbound]"), std::string::npos);
    EXPECT_NE(msg.find("beta_proof"), std::string::npos);
  }
}

// (The pre- "inconsistent guard-group binding" check is now structurally
// unreachable: an accepted() effect's policy IS its guard, so effects sharing a
// guard-partition key share the policy, and the legacy single-policy gate binds
// every effect to the one policy. The suppress model above covers per-policy
// binding.)

TEST(CoordinationPlan, NoSuccessTerminalIsLenient) {
  // No success terminal is a non-renderable spec (the renderers fail closed);
  // the plan still carries the empty projection.
  PlanInputs in = validBase();
  in.terminal.success = "";
  auto r = assemblePlan(std::move(in));
  ASSERT_TRUE(static_cast<bool>(r));
  EXPECT_EQ(r->terminal.success, "");
}

// ---- explicit instance key + evidence-only coordination --------------------

// validBase, with the declared inputs an explicit instance key resolves
// against: a string identity `id` and (for the non-string case) a `amount`.
PlanInputs withKeyInputs(PlanInputs in) {
  in.inputs.push_back({"id", "string"});
  in.inputs.push_back({"amount", "money"});
  return in;
}

// An effectless evidence-only coordination: one attestation, an explicit
// string instance key, a success terminal, no effects.
PlanInputs evidenceOnlyBase() {
  PlanInputs in;
  in.procedure = "anchor";
  in.terminal.success = "CLOSED";
  addReachableClosedLifecycle(in);
  in.inputs.push_back({"claim_ref", "string"});
  in.inputs.push_back({"proof", "evidence"});
  in.attestations.push_back(policy("proof"));
  in.explicitInstanceKey = "claim_ref";
  return in;
}

TEST(CoordinationPlan, ExplicitInstanceKeyWins) {
  PlanInputs in = withKeyInputs(validBase());
  in.explicitInstanceKey = "id";
  in.effects[0].idempotencyValue = "id";
  in.effects[1].idempotencyValue = "id";
  auto r = assemblePlan(std::move(in));
  ASSERT_TRUE(static_cast<bool>(r));
  EXPECT_EQ(r->workflowKey, "id");
  EXPECT_EQ(r->explicitInstanceKey, "id");
  EXPECT_FALSE(r->evidenceOnly);
}

TEST(CoordinationPlan, UndeclaredInstanceKeyFails) {
  PlanInputs in = withKeyInputs(validBase());
  in.explicitInstanceKey = "nope";
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("names no declared input"),
            std::string::npos);
}

TEST(CoordinationPlan, NonStringInstanceKeyFails) {
  PlanInputs in = withKeyInputs(validBase());
  in.explicitInstanceKey = "amount"; // money, not a string identity
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("non-string type"),
            std::string::npos);
}

TEST(CoordinationPlan, AmbiguousInstanceKeyFails) {
  // The explicit key disagrees with an effect's own idempotency ref.
  PlanInputs in = withKeyInputs(validBase());
  in.explicitInstanceKey = "id"; // effects still key on "k"
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("ambiguous instance key"),
            std::string::npos);
}

TEST(CoordinationPlan, LiteralEffectKeyWithExplicitKeyFails) {
  // A literal effect key is NOT a ref to the declared instance key — it must
  // fail, not be silently rewritten to the declared key.
  PlanInputs in = withKeyInputs(validBase());
  in.explicitInstanceKey = "id";
  in.effects[0].idempotencyValue = "id"; // agrees
  in.effects[1].idempotencyKind = "literal";
  in.effects[1].idempotencyValue = "literal-key";
  std::string msg = errMsg(assemblePlan(std::move(in)));
  EXPECT_NE(msg.find("ambiguous instance key"), std::string::npos);
  EXPECT_NE(msg.find("literal"), std::string::npos);
}

TEST(CoordinationPlan, EvidenceOnlyNormalizes) {
  auto r = assemblePlan(evidenceOnlyBase());
  ASSERT_TRUE(static_cast<bool>(r));
  EXPECT_TRUE(r->effects.empty());
  EXPECT_TRUE(r->evidenceOnly);
  EXPECT_EQ(r->workflowKey, "claim_ref");
  EXPECT_EQ(r->explicitInstanceKey, "claim_ref");
}

TEST(CoordinationPlan, EvidenceOnlyRequiresExplicitKey) {
  PlanInputs in = evidenceOnlyBase();
  in.explicitInstanceKey = "";
  EXPECT_NE(
      errMsg(assemblePlan(std::move(in))).find("requires an explicit instance"),
      std::string::npos);
}

TEST(CoordinationPlan, EvidenceOnlyRequiresSuccessTerminal) {
  PlanInputs in = evidenceOnlyBase();
  in.terminal.success = "";
  EXPECT_NE(errMsg(assemblePlan(std::move(in))).find("requires a success"),
            std::string::npos);
}

TEST(CoordinationPlan, EffectlessWithoutAttestationActionFails) {
  // An effectless plan that declares a key but no attestation action is not a
  // coordination (distinct from the lenient anchor-only, keyless case).
  PlanInputs in = evidenceOnlyBase();
  in.attestations.clear();
  EXPECT_NE(errMsg(assemblePlan(std::move(in)))
                .find("must declare an attestation/evidence"),
            std::string::npos);
}

} // namespace
