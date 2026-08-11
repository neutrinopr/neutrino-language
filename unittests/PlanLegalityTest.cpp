// SPDX-License-Identifier: Apache-2.0
//===- PlanLegalityTest.cpp - semantic realization-legality () --------===//
//
// Direct C++ assertions on the ONE plan matcher: the requirement derivation
// (coordinationPlanRequirements), the closed registry, and checkPlanLegality's
// fail-closed behavior across profile sources (the built-in reference evaluator
// profile + constructed file-like profiles). Plans are hand-built, so no
// MLIRContext / view / JSON is needed.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/PlanLegality.h"
#include "Neutrino/SemanticRequirements.h"
#include "Neutrino/VersionInfo.h"

#include "Neutrino/Expr.h"

#include "gtest/gtest.h"

#include <climits>

using namespace neutrino;

namespace {

ExprPtr var(const char *n) {
  auto e = std::make_unique<ExprNode>();
  e->kind = ExprNode::Var;
  e->name = n;
  return e;
}

// A guard `a >= b` (a Cmp over two vars) — for the guard:conditional feature.
ExprPtr cmpGuard() {
  auto n = std::make_unique<ExprNode>();
  n->kind = ExprNode::Cmp;
  n->name = ">=";
  n->lhs = var("amount");
  n->rhs = var("threshold");
  return n;
}

// A left-nested `((… (a+1)+1) … )+1` of the given AST depth (>= 1).
ExprPtr deepExpr(int depth) {
  ExprPtr n = var("a");
  for (int i = 1; i < depth; ++i) {
    auto b = std::make_unique<ExprNode>();
    b->kind = ExprNode::Bin;
    b->op = '+';
    b->lhs = std::move(n);
    b->rhs = std::make_unique<ExprNode>();
    b->rhs->kind = ExprNode::Num;
    b->rhs->num = 1;
    n = std::move(b);
  }
  return n;
}

PlanEffect effect(const char *name, const char *kind, bool guarded = false) {
  PlanEffect e;
  e.name = name;
  e.kind = kind;
  e.ledger = "a.src";
  e.amount = "ref:amount";
  e.currency = "ref:currency";
  e.party = "ref:payer";
  if (guarded)
    e.guard = cmpGuard();
  return e;
}

// A full-featured balanced coordination: debit+credit (one guarded), an
// attestation policy, and success+aborted terminals.
CoordinationPlan fullPlan() {
  CoordinationPlan p;
  p.procedure = "probe";
  p.workflowKey = "flow_id";
  p.balanced = true;
  p.replay.key = "flow_id";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  p.terminal.aborted = "ABORTED";
  AttestationPolicy pol;
  pol.input = "ev";
  p.attestations.push_back(pol);
  p.effects.push_back(effect("pay_out", "debit", /*guarded=*/true));
  p.effects.push_back(effect("pay_in", "credit"));
  return p;
}

// A file-like profile: the full registry (optionally minus one feature) with a
// given expression-depth cap and generous other limits.
SemanticProfile fileProfile(const char *id, int maxDepth,
                            const char *without = nullptr) {
  SemanticProfile sp;
  sp.id = id;
  sp.versionPresent = true;
  sp.version = kSemanticProfileVersion;
  sp.features = knownSemanticFeatures();
  if (without)
    sp.features.erase(without);
  sp.limits = {maxDepth, 64, 64, 64, 64, 4096};
  return sp;
}

// A time-dependent coordination: fullPlan plus a declared temporal input.
CoordinationPlan timePlan() {
  CoordinationPlan p = fullPlan();
  p.inputs.push_back({"now", "timestamp"});
  return p;
}

// A wide-but-shallow coordination: `n` depth-2 computes (1 operation each) ->
// ~n operation steps at low expression depth, so the step cap fires where the
// structural depth cap does not.
CoordinationPlan wideOpsPlan(int n) {
  CoordinationPlan p = fullPlan();
  for (int i = 0; i < n; ++i) {
    PlanCompute c;
    c.name = "c";
    c.category = "money";
    auto b = std::make_unique<ExprNode>();
    b->kind = ExprNode::Bin;
    b->op = '+';
    b->lhs = var("a");
    b->rhs = var("b");
    c.expr = std::move(b);
    p.computes.push_back(std::move(c));
  }
  return p;
}

std::vector<std::string> codes(const std::vector<Diagnostic> &d) {
  std::vector<std::string> c;
  for (const Diagnostic &x : d)
    if (x.severity == "error")
      c.push_back(x.code);
  return c;
}

bool has(const std::vector<Diagnostic> &d, const char *code) {
  for (const Diagnostic &x : d)
    if (x.code == code && x.severity == "error")
      return true;
  return false;
}

} // namespace

TEST(PlanLegality, DerivesRequirementsAndMetrics) {
  PlanRequirements r = coordinationPlanRequirements(fullPlan());
  std::set<std::string> feats;
  for (const SemanticRequirement &sr : r.features)
    feats.insert(sr.feature);
  EXPECT_TRUE(feats.count("authorization:explicit"));
  EXPECT_TRUE(feats.count("effect:debit"));
  EXPECT_TRUE(feats.count("effect:credit"));
  EXPECT_TRUE(feats.count("guard:conditional"));
  EXPECT_TRUE(feats.count("invariant:balanced"));
  EXPECT_TRUE(feats.count("attestation:quorum"));
  EXPECT_TRUE(feats.count("terminal:success"));
  EXPECT_TRUE(feats.count("terminal:aborted"));
  EXPECT_TRUE(feats.count("replay:idempotent"));
  EXPECT_FALSE(feats.count("terminal:contested"));  // not declared
  EXPECT_FALSE(feats.count("time:explicit_input")); // no temporal input
  EXPECT_EQ(r.metrics.effectCount, 2);
  EXPECT_EQ(r.metrics.attestationCount, 1);
  EXPECT_EQ(r.metrics.expressionDepth, 2); // the `a >= b` guard
  EXPECT_EQ(r.metrics.operationSteps, 1);  // one comparison operation
}

TEST(PlanLegality, TimeDependentPlanDerivesTimeFeature) {
  // A declared temporal input yields time:explicit_input; an
  // otherwise-identical numeric coordination derives no such requirement.
  PlanRequirements t = coordinationPlanRequirements(timePlan());
  std::set<std::string> tf;
  for (const SemanticRequirement &r : t.features)
    tf.insert(r.feature);
  EXPECT_TRUE(tf.count("time:explicit_input"));
  PlanRequirements n = coordinationPlanRequirements(fullPlan());
  std::set<std::string> nf;
  for (const SemanticRequirement &r : n.features)
    nf.insert(r.feature);
  EXPECT_FALSE(nf.count("time:explicit_input"));
}

TEST(PlanLegality, TimeProfileSupportAndRefusal) {
  // The reference evaluator and both time-realizing built-in profiles accept a
  // time-dependent coordination; a profile that omits time refuses it.
  EXPECT_TRUE(
      planIsLegal(checkPlanLegality(timePlan(), referenceEvaluatorProfile())));
  SemanticProfile noTime =
      fileProfile("target.evm.v1", 32, /*without=*/"time:explicit_input");
  std::vector<Diagnostic> d = checkPlanLegality(timePlan(), noTime);
  EXPECT_FALSE(planIsLegal(d));
  EXPECT_TRUE(has(d, "legality.unsupported_feature"));
  EXPECT_TRUE(
      builtinSemanticProfile("solidity").features.count("time:explicit_input"));
  EXPECT_TRUE(
      builtinSemanticProfile("postgres").features.count("time:explicit_input"));
}

TEST(PlanLegality, OperationStepLimitRefused) {
  // A wide-but-shallow coordination (many operations, low depth) is refused by
  // a tight maxOperationSteps cap but accepted by a generous one — a genuine
  // step-cost bound distinct from the structural depth limit.
  CoordinationPlan p = wideOpsPlan(30); // ~31 ops, depth 2
  SemanticProfile tight = fileProfile("t.evm.v1", 32);
  tight.limits.maxOperationSteps = 10;
  std::vector<Diagnostic> d = checkPlanLegality(p, tight);
  EXPECT_FALSE(planIsLegal(d));
  EXPECT_TRUE(has(d, "legality.limit_exceeded"));
  SemanticProfile generous = fileProfile("t.pg.v1", 32);
  generous.limits.maxOperationSteps = 4096;
  EXPECT_TRUE(planIsLegal(checkPlanLegality(p, generous)));
}

TEST(PlanLegality, ReferenceEvaluatorAcceptsFullPlan) {
  std::vector<Diagnostic> d =
      checkPlanLegality(fullPlan(), referenceEvaluatorProfile());
  EXPECT_TRUE(planIsLegal(d)) << (codes(d).empty() ? "" : codes(d)[0]);
}

TEST(PlanLegality, EvaluatorVocabularyDoesNotDrift) {
  // The evaluator's INDEPENDENTLY-declared support (not aliased to the
  // registry) must cover EXACTLY the closed registry — a registry addition the
  // evaluator has not claimed here fails this pin, catching evaluator lag.
  EXPECT_EQ(evaluatorSupportedFeatures(), knownSemanticFeatures());
  EXPECT_EQ(referenceEvaluatorProfile().features, evaluatorSupportedFeatures());
}

TEST(PlanLegality, EvaluatorLagRefusesUntilFeatureClaimed) {
  // If the evaluator has NOT claimed a registered feature, a coordination plan
  // needing it is refused (unsupported_feature) — the drift guard is enforced,
  // not cosmetic: the support declaration gates realization independently.
  CoordinationPlan p = fullPlan();
  p.terminal.contested = "DISPUTED"; // needs terminal:contested (registered)
  SemanticProfile lagging = referenceEvaluatorProfile();
  lagging.features.erase("terminal:contested"); // un-implemented in this build
  std::vector<Diagnostic> d = checkPlanLegality(p, lagging);
  EXPECT_FALSE(planIsLegal(d));
  EXPECT_TRUE(has(d, "legality.unsupported_feature"));
}

TEST(PlanLegality, BuiltinProfilesAreMandatoryDefaults) {
  // Every rigid target has an authoritative built-in default (the no-profile
  // gate source); an unknown target fails closed (no version).
  EXPECT_TRUE(
      builtinSemanticProfile("solidity").features.count("terminal:contested"));
  EXPECT_FALSE(
      builtinSemanticProfile("postgres").features.count("terminal:contested"));
  EXPECT_EQ(builtinSemanticProfile("solidity").limits.maxExpressionDepth, 16);
  EXPECT_EQ(builtinSemanticProfile("postgres").limits.maxExpressionDepth, 32);
  EXPECT_EQ(builtinSemanticProfile("coordination-trace").features,
            evaluatorSupportedFeatures());
  EXPECT_FALSE(builtinSemanticProfile("zzz").versionPresent);
  EXPECT_TRUE(has(checkPlanLegality(fullPlan(), builtinSemanticProfile("zzz")),
                  "legality.unknown_profile_version"));
}

TEST(PlanLegality, UnknownRequirementFailsClosedEvenForEvaluator) {
  // An unregistered effect kind (a future plan node) yields effect:reserve —
  // outside the closed registry — so even the reference evaluator refuses it.
  CoordinationPlan p = fullPlan();
  p.effects.push_back(effect("resv", "reserve"));
  std::vector<Diagnostic> d = checkPlanLegality(p, referenceEvaluatorProfile());
  EXPECT_FALSE(planIsLegal(d));
  EXPECT_TRUE(has(d, "legality.unknown_requirement"));
  // A file-backed profile refuses it the same way (one matcher, many sources).
  EXPECT_TRUE(has(checkPlanLegality(p, fileProfile("target.evm.v1", 16)),
                  "legality.unknown_requirement"));
}

TEST(PlanLegality, MissingAndUnknownVersionFailClosed) {
  SemanticProfile noVer = fileProfile("target.evm.v1", 16);
  noVer.versionPresent = false;
  EXPECT_TRUE(has(checkPlanLegality(fullPlan(), noVer),
                  "legality.unknown_profile_version"));

  SemanticProfile badVer = fileProfile("target.evm.v1", 16);
  badVer.version = kSemanticProfileVersion + 99;
  EXPECT_TRUE(has(checkPlanLegality(fullPlan(), badVer),
                  "legality.unknown_profile_version"));
}

TEST(PlanLegality, UnsupportedTerminalShapeRefused) {
  // A plan projecting a contested terminal is refused by a profile that does
  // not realize that shape (the PostgreSQL-only refusal), but accepted by one
  // that does (Solidity).
  CoordinationPlan p = fullPlan();
  p.terminal.contested = "DISPUTED";
  SemanticProfile pg =
      fileProfile("target.postgres.v1", 32, /*without=*/"terminal:contested");
  std::vector<Diagnostic> pgd = checkPlanLegality(p, pg);
  EXPECT_FALSE(planIsLegal(pgd));
  EXPECT_TRUE(has(pgd, "legality.unsupported_feature"));
  SemanticProfile sol = fileProfile("target.evm.v1", 32); // has contested
  EXPECT_TRUE(planIsLegal(checkPlanLegality(p, sol)));
}

TEST(PlanLegality, ExceededLimitRefused) {
  // A deep expression is refused by a tight expression-depth cap (the
  // Solidity-only refusal), but accepted by a generous one (PostgreSQL).
  CoordinationPlan p = fullPlan();
  PlanCompute c;
  c.name = "deep";
  c.category = "money";
  c.expr = deepExpr(20); // depth 20
  p.computes.push_back(std::move(c));
  SemanticProfile sol = fileProfile("target.evm.v1", 16);
  std::vector<Diagnostic> sd = checkPlanLegality(p, sol);
  EXPECT_FALSE(planIsLegal(sd));
  EXPECT_TRUE(has(sd, "legality.limit_exceeded"));
  SemanticProfile pg = fileProfile("target.postgres.v1", 32);
  EXPECT_TRUE(planIsLegal(checkPlanLegality(p, pg)));
}

TEST(PlanLegality, Deterministic) {
  std::vector<Diagnostic> a =
      checkPlanLegality(fullPlan(), fileProfile("t.evm.v1", 16));
  std::vector<Diagnostic> b =
      checkPlanLegality(fullPlan(), fileProfile("t.evm.v1", 16));
  EXPECT_EQ(codes(a), codes(b));
}

// ---- explicit instance key + evidence-only coordination --------------------

// An effectless evidence-only coordination: an explicit instance key + one
// attestation policy + a success terminal, no ledger effects.
static CoordinationPlan evidenceOnlyCoordination() {
  CoordinationPlan p;
  p.procedure = "anchor";
  p.workflowKey = "claim_ref";
  p.explicitInstanceKey = "claim_ref";
  p.evidenceOnly = true;
  p.replay.key = "claim_ref";
  p.replay.idempotent = true;
  p.terminal.success = "CLOSED";
  AttestationPolicy pol;
  pol.input = "proof";
  p.attestations.push_back(pol);
  return p;
}

TEST(PlanLegality, ExplicitKeyAndEvidenceFeaturesInRegistry) {
  EXPECT_EQ(knownSemanticFeatures().count("identity:explicit_instance_key"),
            1u);
  EXPECT_EQ(knownSemanticFeatures().count("coordination:evidence_acceptance"),
            1u);
}

TEST(PlanLegality, ExplicitKeyPlanDerivesIdentityFeature) {
  auto has = [](const PlanRequirements &r, const char *f) {
    for (const SemanticRequirement &x : r.features)
      if (x.feature == f)
        return true;
    return false;
  };
  // The default fullPlan derives its key from effects — no identity feature.
  EXPECT_FALSE(has(coordinationPlanRequirements(fullPlan()),
                   "identity:explicit_instance_key"));
  CoordinationPlan p = fullPlan();
  p.explicitInstanceKey = "flow_id";
  EXPECT_TRUE(
      has(coordinationPlanRequirements(p), "identity:explicit_instance_key"));
}

TEST(PlanLegality, EvidenceOnlyPlanDerivesEvidenceFeature) {
  PlanRequirements r = coordinationPlanRequirements(evidenceOnlyCoordination());
  bool ident = false, ev = false;
  for (const SemanticRequirement &x : r.features) {
    ident |= x.feature == "identity:explicit_instance_key";
    ev |= x.feature == "coordination:evidence_acceptance";
  }
  EXPECT_TRUE(ident);
  EXPECT_TRUE(ev);
}

TEST(PlanLegality, EvidenceOnlyAcceptedByReferenceAndBackends) {
  // : the reference evaluator AND both rigid lowerings now realize
  // evidence-only coordination, so it passes legality on every target.
  EXPECT_TRUE(planIsLegal(checkPlanLegality(evidenceOnlyCoordination(),
                                            referenceEvaluatorProfile())));
  for (const char *target : {"solidity", "postgres"}) {
    std::vector<Diagnostic> d = checkPlanLegality(
        evidenceOnlyCoordination(), builtinSemanticProfile(target));
    EXPECT_TRUE(planIsLegal(d)) << target;
    // and NO unsupported-feature diagnostic mentions the evidence feature.
    for (const Diagnostic &x : d)
      EXPECT_EQ(x.message.find("coordination:evidence_acceptance"),
                std::string::npos)
          << target << ": " << x.message;
  }
}

TEST(PlanLegality, BackendsAdvertiseEvidenceAcceptance) {
  // : both rails advertise evidence_acceptance (they realize it), parity
  // with the reference evaluator.
  for (const char *target : {"solidity", "postgres"}) {
    const std::set<std::string> &f = builtinSemanticProfile(target).features;
    EXPECT_EQ(f.count("identity:explicit_instance_key"), 1u) << target;
    EXPECT_EQ(f.count("coordination:evidence_acceptance"), 1u) << target;
  }
  const std::set<std::string> &ref = referenceEvaluatorProfile().features;
  EXPECT_EQ(ref.count("identity:explicit_instance_key"), 1u);
  EXPECT_EQ(ref.count("coordination:evidence_acceptance"), 1u);
}
