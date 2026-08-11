// SPDX-License-Identifier: Apache-2.0
//===- BackendProjectionTest.cpp - complete projection graph () -------===//
//
// Direct C++ assertions on projectBackendGraph's COMPLETE §2 projection (the
//  P1-A contract): every node family and every §3 typed edge, with the
// verifier establishing exact cardinalities. Also the P1-B contract that no
// internally-invalid projection escapes as a successful graph. Field values
// mirror the pinned trace fixtures (docs/process/m6_backend_projection_traces
// .json); the end-to-end comparison against all three bound traces + the waist
// round-trip lives in test/ir/backend/backend_projection_graph.test.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProjectionCodec.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/Support/Error.h"

#include "gtest/gtest.h"

#include <algorithm>

using namespace neutrino;
using namespace neutrino::projection;

namespace {

// Unwrap the projector's `Expected` for the success-expected tests: an
// unexpected verifier failure is a loud test failure (with its stable
// diagnostic), never a silent empty graph.
BackendProjectionGraph project(const CoordinationPlan &coordinationPlan) {
  llvm::Expected<BackendProjectionGraph> g =
      projectBackendGraph(coordinationPlan);
  if (!g) {
    ADD_FAILURE() << "projectBackendGraph failed: "
                  << llvm::toString(g.takeError());
    return BackendProjectionGraph{};
  }
  return std::move(*g);
}

const ExecutionIdentity *execOf(const BackendProjectionGraph &g) {
  return g.executionIdentities.empty() ? nullptr
                                       : &g.executionIdentities.front();
}
const QuorumPolicy *policyByThreshold(const BackendProjectionGraph &g, int t) {
  for (const auto &p : g.quorumPolicies)
    if (p.threshold == t)
      return &p;
  return nullptr;
}
const LifecycleState *stateByName(const BackendProjectionGraph &g,
                                  const std::string &name) {
  for (const auto &s : g.lifecycleStates)
    if (s.name == name)
      return &s;
  return nullptr;
}
bool hasEdge(const BackendProjectionGraph &g, const std::string &name,
             const std::string &from, const std::string &to) {
  for (const auto &e : g.edges)
    if (e.name == name && e.from == from && e.to == to)
      return true;
  return false;
}
int edgeCount(const BackendProjectionGraph &g, const std::string &name,
              const std::string &from) {
  int n = 0;
  for (const auto &e : g.edges)
    if (e.name == name && e.from == from)
      ++n;
  return n;
}

llvm::json::Value parseEncoded(const BackendProjectionGraph &graph) {
  llvm::Expected<std::string> encoded = encodeFinalizedProjection(graph);
  if (!encoded) {
    ADD_FAILURE() << "encodeFinalizedProjection failed: "
                  << llvm::toString(encoded.takeError());
    return llvm::json::Object{};
  }
  llvm::Expected<llvm::json::Value> parsed = llvm::json::parse(*encoded);
  if (!parsed) {
    ADD_FAILURE() << "encoded finalized projection did not parse: "
                  << llvm::toString(parsed.takeError());
    return llvm::json::Object{};
  }
  return std::move(*parsed);
}

void expectDecodeBytesError(llvm::StringRef wire, llvm::StringRef needle) {
  llvm::Expected<BackendProjectionGraph> decoded =
      decodeFinalizedProjection(wire);
  ASSERT_FALSE(static_cast<bool>(decoded));
  EXPECT_NE(llvm::toString(decoded.takeError()).find(needle.str()),
            std::string::npos);
}

void expectDecodeError(llvm::json::Value wire, llvm::StringRef needle) {
  expectDecodeBytesError(compactJson(wire), needle);
}

LifecycleTransitionPolicy closeToClosed() {
  LifecycleTransitionPolicy close;
  close.name = "CLOSE";
  close.from = "OPEN";
  close.to = "CLOSED";
  close.idempotency = "reject";
  return close;
}

// evidence-only-acceptance trace: one policy, terminal CLOSED, no effects.
CoordinationPlan evidenceOnly() {
  CoordinationPlan p;
  p.procedure = "shipment_evidence_anchor";
  p.workflowKey = "shipment_ref";
  p.evidenceOnly = true;
  p.terminal.success = "CLOSED";
  p.lifecycleTransitions.push_back(closeToClosed());
  AttestationPolicy a;
  a.input = "input:1";
  a.quorum = 2;
  a.observerSet = "0";
  a.canonicalization = "exact";
  a.timeout = "PT48H";
  a.fallback = "abort";
  p.attestations.push_back(a);
  return p;
}

// balanced-ledger-effect trace: one atomic-refuse policy, a balanced debit +
// credit group, a COMMIT transition that posts it.
CoordinationPlan balancedAtomic() {
  CoordinationPlan p;
  p.procedure = "oracle_delivery";
  p.workflowKey = "order_id";
  p.balanced = true;
  p.terminal.success = "CLOSED";
  AttestationPolicy a;
  a.input = "input:4";
  a.quorum = 2;
  a.observerSet = "0";
  a.canonicalization = "exact";
  a.timeout = "PT24H";
  a.fallback = "abort";
  p.attestations.push_back(a);
  auto mkEffect = [](size_t idx, const std::string &kind,
                     const std::string &ledger, const std::string &party) {
    PlanEffect e;
    e.index = idx;
    e.kind = kind;
    e.ledger = ledger;
    e.party = party;
    e.amount = "ref:input:2";
    e.currency = "ref:input:3";
    e.gateMode = PlanGateMode::AtomicRefuse;
    e.gatePolicy = "input:4";
    return e;
  };
  p.effects.push_back(mkEffect(0, "debit", "0", "ref:input:1"));
  p.effects.push_back(mkEffect(1, "credit", "1", "ref:input:5"));
  PlanEffectGroup grp;
  grp.effectIndices = {0, 1};
  grp.firstIndex = 0;
  grp.mustBalance = true;
  grp.gateMode = PlanGateMode::AtomicRefuse;
  grp.gatePolicy = "input:4";
  p.effectGroups = {grp};
  LifecycleTransitionPolicy t;
  t.name = "COMMIT";
  t.from = "QUORUM_MET";
  t.to = "CLOSED";
  t.effects = {"post"};
  p.lifecycleTransitions = {t};
  return p;
}

// multi-policy-partial-execution trace: two temporal-suppress policies, each
// gating its own balanced group.
CoordinationPlan multiPolicyTemporal() {
  CoordinationPlan p;
  p.procedure = "accepted_multi_policy";
  p.workflowKey = "settlement_id";
  p.balanced = true;
  p.terminal.success = "CLOSED";
  auto mkPolicy = [](const std::string &in, int q, const std::string &obs) {
    AttestationPolicy a;
    a.input = in;
    a.quorum = q;
    a.observerSet = obs;
    a.canonicalization = "exact";
    a.fallback = "abort";
    return a;
  };
  p.attestations = {mkPolicy("input:4", 2, "0"), mkPolicy("input:5", 3, "1")};
  auto mkEffect = [](size_t idx, const std::string &kind,
                     const std::string &ledger, const std::string &pol) {
    PlanEffect e;
    e.index = idx;
    e.kind = kind;
    e.ledger = ledger;
    e.party = "ref:input:1";
    e.amount = "ref:input:2";
    e.currency = "ref:input:3";
    e.gateMode = PlanGateMode::TemporalSuppress;
    e.gatePolicy = pol;
    return e;
  };
  p.effects.push_back(mkEffect(0, "debit", "0", "input:4"));
  p.effects.push_back(mkEffect(1, "debit", "1", "input:5"));
  p.effects.push_back(mkEffect(2, "credit", "2", "input:4"));
  p.effects.push_back(mkEffect(3, "credit", "3", "input:5"));
  auto mkGroup = [](std::vector<size_t> idxs, size_t first,
                    const std::string &pol) {
    PlanEffectGroup grp;
    grp.effectIndices = std::move(idxs);
    grp.firstIndex = first;
    grp.mustBalance = true;
    grp.gateMode = PlanGateMode::TemporalSuppress;
    grp.gatePolicy = pol;
    return grp;
  };
  p.effectGroups = {mkGroup({0, 2}, 0, "input:4"),
                    mkGroup({1, 3}, 1, "input:5")};
  p.lifecycleTransitions.push_back(closeToClosed());
  return p;
}

CoordinationPlan codecTemporal() {
  CoordinationPlan p = multiPolicyTemporal();
  const std::string original[] = {"input:4", "input:5"};
  const std::string identifiers[] = {"policyAlpha", "policyBeta"};
  for (size_t index = 0; index < p.attestations.size(); ++index)
    p.attestations[index].input = identifiers[index];
  for (PlanEffect &effect : p.effects)
    for (size_t index = 0; index < 2; ++index)
      if (effect.gatePolicy == original[index])
        effect.gatePolicy = identifiers[index];
  for (PlanEffectGroup &group : p.effectGroups)
    for (size_t index = 0; index < 2; ++index)
      if (group.gatePolicy == original[index])
        group.gatePolicy = identifiers[index];
  return p;
}

// A coordination carrying declared inputs + a compute (the §2.4 param / compute
// family, which the three trace fixtures do not exercise).
CoordinationPlan withComputes() {
  CoordinationPlan p = balancedAtomic();
  PlanInput amount, rate; // CoordinationPlan input values.
  amount.name = "amount";
  amount.type = "money";
  rate.name = "rate";
  rate.type = "number";
  p.inputs = {amount, rate};
  PlanCompute fee;
  fee.name = "fee";
  fee.category = "money";
  fee.deps = {"amount", "rate"}; // depends on two declared inputs
  fee.expr = parseExpr("amount + rate");
  typeExpr(*fee.expr, {{"amount", ValueCategory::Money},
                       {"rate", ValueCategory::Decimal}});
  p.computes.push_back(std::move(fee));
  return p;
}

TEST(BackendProjection, TypedParamAndComputeFamily) {
  BackendProjectionGraph g = project(withComputes());

  // §2.4 TypedParam — one per declared input, identity is the canonical label.
  ASSERT_EQ(g.typedParams.size(), 2u);
  bool sawMoney = false, sawNumber = false;
  for (const auto &tp : g.typedParams) {
    EXPECT_EQ(tp.name.rfind("input:", 0), 0u); // canonical, not a display name
    EXPECT_FALSE(tp.bindingValue.empty());
    sawMoney |= tp.type == "money";
    sawNumber |= tp.type == "number";
  }
  EXPECT_TRUE(sawMoney);
  EXPECT_TRUE(sawNumber);

  // §2.4 ComputeNode — one per compute; operandRefs resolve to its two deps.
  ASSERT_EQ(g.computeNodes.size(), 1u);
  const ComputeNode &cn = g.computeNodes[0];
  EXPECT_EQ(cn.dtype, "money");
  EXPECT_EQ(cn.bindingValue, "fee");
  EXPECT_FALSE(cn.expression.empty());
  EXPECT_EQ(edgeCount(g, "operandRefs", cn.id), 2);
  // each operandRefs target is a real TypedOperand carrying a canonical ref.
  for (const auto &e : g.edges)
    if (e.name == "operandRefs" && e.from == cn.id) {
      bool found = false;
      for (const auto &op : g.typedOperands)
        if (op.id == e.to) {
          found = true;
          EXPECT_EQ(op.value.rfind("ref:input:", 0), 0u);
        }
      EXPECT_TRUE(found);
    }
}

TEST(BackendProjection, TypedValueConsumerPreservesOrderNamesAndExpression) {
  BackendProjectionGraph g = project(withComputes());
  auto values = consumeTypedValueProjection(g);
  if (!values)
    FAIL() << llvm::toString(values.takeError());
  ASSERT_EQ(values->params.size(), 2u);
  EXPECT_EQ(values->params[0].name, "amount");
  EXPECT_EQ(values->params[1].name, "rate");
  ASSERT_EQ(values->computes.size(), 1u);
  EXPECT_EQ(values->computes[0].name, "fee");
  EXPECT_EQ(toSql(*values->computes[0].expression), "(amount + rate)");
}

// A coordination whose declared inputs include the instance-key input (the
// validated workflowKey), so the §2.4 instance-key role has a param to bind
// (). `withComputes()` alone keys on "order_id" but declares no such input.
CoordinationPlan withInstanceKeyParam() {
  CoordinationPlan p = withComputes(); // workflowKey == "order_id"
  PlanInput key;
  key.name = "order_id";
  key.type = "string";
  p.inputs.push_back(key);
  return p;
}

// : the closed instance-key role is projected onto exactly the workflowKey
// param (graph role) AND exposed by the finalized view as a dedicated exact-one
// association a recipe binds DIRECTLY — no scan or per-element predicate.
TEST(BackendProjection, InstanceKeyParamRoleProjectedAndExposed) {
  BackendProjectionGraph g = project(withInstanceKeyParam());
  int graphRoles = 0;
  for (const auto &tp : g.typedParams) {
    if (tp.bindingValue == "order_id") {
      EXPECT_TRUE(tp.isInstanceKey);
      ++graphRoles;
    } else {
      EXPECT_FALSE(tp.isInstanceKey);
    }
  }
  EXPECT_EQ(graphRoles, 1);

  auto values = consumeTypedValueProjection(g);
  if (!values)
    FAIL() << llvm::toString(values.takeError());
  // Retrieved DIRECTLY from the dedicated accessor — no loop, no predicate.
  ASSERT_TRUE(values->instanceKeyParam.has_value());
  EXPECT_EQ(values->instanceKeyParam->name, "order_id");
  EXPECT_EQ(values->instanceKeyParam->type, "string");
}

// : the accessor is empty when the instance key is NOT carried by a typed
// param — the CANONICAL evidence coordination, not an invalid state. The pinned
// evidence-only-acceptance trace has instanceKey="shipment_ref" with ZERO typed
// params (the key is a coordination-level identity on the ExecutionIdentity,
// not a declared value input), so a non-empty instance key with no bound param
// is a valid graph and the exact-0/1 accessor is correctly empty. (This is why
// the role is an iff over the params, not a converse cardinality keyed to a
// non-empty instanceKey: that converse would reject this canonical rail.)
TEST(BackendProjection, InstanceKeyParamAbsentWhenKeyIsNotATypedParam) {
  BackendProjectionGraph g = project(evidenceOnly());
  ASSERT_FALSE(g.executionIdentities.empty());
  EXPECT_EQ(g.executionIdentities.front().instanceKey, "shipment_ref");
  EXPECT_TRUE(g.typedParams.empty()); // key present, but carried by no param
  auto values = consumeTypedValueProjection(g);
  if (!values)
    FAIL() << llvm::toString(values.takeError());
  EXPECT_FALSE(values->instanceKeyParam.has_value());
}

// : the graph verifier enforces the role as an exact fact — a key param
// left unmarked, or a non-key param marked, fails closed.
TEST(BackendProjection, VerifierBitesInstanceKeyRoleMutations) {
  BackendProjectionGraph roleMissing = project(withInstanceKeyParam());
  for (auto &tp : roleMissing.typedParams)
    if (tp.bindingValue == "order_id")
      tp.isInstanceKey = false;
  EXPECT_EQ(verifyAndOrder(roleMissing),
            "diag:TypedParam:instance-key-role-missing");

  BackendProjectionGraph roleUnbound = project(withInstanceKeyParam());
  for (auto &tp : roleUnbound.typedParams)
    if (tp.bindingValue == "amount")
      tp.isInstanceKey = true;
  EXPECT_EQ(verifyAndOrder(roleUnbound),
            "diag:TypedParam:instance-key-role-unbound");
}

TEST(BackendProjection, FinalizedSequenceOwnsRailAndAssociationSelection) {
  BackendProjectionGraph evidence = project(evidenceOnly());
  auto evidenceSequence = consumeFinalizedProjectionSequence(evidence);
  if (!evidenceSequence)
    FAIL() << llvm::toString(evidenceSequence.takeError());
  EXPECT_EQ(evidenceSequence->executionMode, ExecutionMode::Evidence);
  EXPECT_EQ(evidenceSequence->attestationKind,
            FinalizedAttestationKind::Single);
  EXPECT_TRUE(evidenceSequence->postings.empty());

  BackendProjectionGraph atomic = project(balancedAtomic());
  auto atomicSequence = consumeFinalizedProjectionSequence(atomic);
  if (!atomicSequence)
    FAIL() << llvm::toString(atomicSequence.takeError());
  EXPECT_EQ(atomicSequence->executionMode, ExecutionMode::Effectful);
  EXPECT_EQ(atomicSequence->attestationKind, FinalizedAttestationKind::Single);
  ASSERT_EQ(atomicSequence->effectGroups.size(), 1u);
  EXPECT_EQ(atomicSequence->effectGroups.front().postings.size(), 2u);
  EXPECT_EQ(atomicSequence->postings.size(), 2u);
  EXPECT_EQ(atomicSequence->postings[0].posting->effectIndex, 0);
  EXPECT_EQ(atomicSequence->postings[1].posting->effectIndex, 1);

  BackendProjectionGraph temporal = project(multiPolicyTemporal());
  auto temporalSequence = consumeFinalizedProjectionSequence(temporal);
  if (!temporalSequence)
    FAIL() << llvm::toString(temporalSequence.takeError());
  EXPECT_EQ(temporalSequence->executionMode, ExecutionMode::Temporal);
  EXPECT_EQ(temporalSequence->attestationKind,
            FinalizedAttestationKind::PerPolicy);
  ASSERT_EQ(temporalSequence->effectGroups.size(), 2u);
  for (const FinalizedEffectGroupProjection &group :
       temporalSequence->effectGroups) {
    EXPECT_TRUE(group.guard.present);
    EXPECT_EQ(group.guard.guardKind, "attested");
    EXPECT_EQ(group.guard.applicationMode, "temporal-suppress");
    EXPECT_FALSE(group.guard.policyInputBinding.empty());
  }
}

TEST(BackendProjection, FinalizedSequenceBitesRailAndGuardMutations) {
  BackendProjectionGraph wrongRail = project(balancedAtomic());
  for (ProjectedLifecycleRole &role : wrongRail.projectedLifecycleRoles)
    role.mode = ExecutionMode::Temporal;
  auto wrongRailSequence = consumeFinalizedProjectionSequence(wrongRail);
  ASSERT_FALSE(wrongRailSequence);
  EXPECT_EQ(llvm::toString(wrongRailSequence.takeError()),
            "diag:FinalizedProjectionSequence:execution-rail");

  BackendProjectionGraph wrongGuard = project(multiPolicyTemporal());
  wrongGuard.guardObligations.front().applicationMode = "atomic-refuse";
  auto wrongGuardSequence = consumeFinalizedProjectionSequence(wrongGuard);
  ASSERT_FALSE(wrongGuardSequence);
  EXPECT_EQ(llvm::toString(wrongGuardSequence.takeError()),
            "diag:FinalizedProjectionSequence:temporal-group-guard");
}

//  memo-variant witness: a balanced coordination whose procedure, ledger,
// posting name (entry), and one posting's memo all contain a single quote. It
// proves (1) the per-posting typed `memoPresence` variant (Absent vs Present),
// and (2) that the RAW leaf spellings survive VERBATIM in the finalized view —
// no escaping happens here (SQL-literal escaping is the target's own
// `string.escape` leaf hook under the  contract, exercised at B's consumer
// seam, not in this target-blind projection).
CoordinationPlan balancedAtomicQuoted() {
  CoordinationPlan p = balancedAtomic();
  p.procedure = "o'racle";
  p.effects[0].name = "deb'it";     // entry (posting name) with a quote
  p.effects[0].ledger = "as'set";   // ledger with a quote; no memo -> Absent
  p.effects[1].name = "cred'it";
  p.effects[1].ledger = "lia'bility";
  p.effects[1].memo = "m'x";        // memoPresence Present
  return p;
}

TEST(BackendProjection, PostingMemoVariantAndRawValuesPreserved) {
  BackendProjectionGraph g = project(balancedAtomicQuoted());
  auto seqOr = consumeFinalizedProjectionSequence(g);
  if (!seqOr)
    FAIL() << llvm::toString(seqOr.takeError());
  const FinalizedProjectionSequence &seq = *seqOr;

  // The raw procedure name survives verbatim (unescaped) in the finalized view.
  EXPECT_EQ(seq.executionIdentity.procedureNamespace, "o'racle");
  // Any posting carries a memo -> the coordination table has the memo column.
  EXPECT_EQ(seq.postingsSchemaKind, FinalizedPostingsSchemaKind::WithMemo);

  ASSERT_EQ(seq.postings.size(), 2u);
  const FinalizedPostingProjection &debit = seq.postings[0];
  const FinalizedPostingProjection &credit = seq.postings[1];
  ASSERT_EQ(debit.posting->effectIndex, 0);
  ASSERT_EQ(credit.posting->effectIndex, 1);

  // Debit posting: no memo -> Absent variant; raw leaf spellings verbatim.
  EXPECT_EQ(debit.memoPresence, FinalizedPostingMemo::Absent);
  EXPECT_FALSE(debit.memo.has_value());
  EXPECT_EQ(debit.posting->ledger, "as'set"); // RAW, unescaped
  EXPECT_EQ(debit.posting->name, "deb'it");   // RAW entry, unescaped

  // Credit posting: memo present -> Present variant; raw memo verbatim.
  EXPECT_EQ(credit.memoPresence, FinalizedPostingMemo::Present);
  ASSERT_TRUE(credit.memo.has_value());
  EXPECT_EQ(*credit.memo, "m'x");                // RAW, unescaped
  EXPECT_EQ(credit.posting->ledger, "lia'bility");
  EXPECT_EQ(credit.posting->name, "cred'it");
}

TEST(BackendProjection, VerifierBitesTypedBindingAndExpressionMutations) {
  BackendProjectionGraph missingBinding = project(withComputes());
  missingBinding.typedParams.front().bindingValue.clear();
  EXPECT_EQ(verifyAndOrder(missingBinding),
            "diag:TypedParam:bindingValue-missing");

  BackendProjectionGraph badExpression = project(withComputes());
  badExpression.computeNodes.front().expression =
      R"({"dtype":"money","kind":"bin","op":"+","lhs":{"dtype":"decimal","kind":"num","num":1},"rhs":{"dtype":"number","kind":"var","name":"rate"}})";
  EXPECT_EQ(verifyAndOrder(badExpression),
            "diag:ComputeNode:expression-operands");
}

TEST(BackendProjection, VerifierBitesComparisonGuardExpressionMutations) {
  BackendProjectionGraph malformed = project(balancedAtomic());
  malformed.guardObligations.front().guardKind = "comparison";
  malformed.guardObligations.front().conditionKind = "comparison";
  malformed.guardObligations.front().applicationMode = "comparison";
  malformed.edges.erase(std::remove_if(malformed.edges.begin(),
                                       malformed.edges.end(),
                                       [](const ProjectionEdge &edge) {
                                         return edge.name == "policyRef";
                                       }),
                        malformed.edges.end());
  malformed.balancedEffectGroups.front().comparisonGuardExpression = "{";
  EXPECT_EQ(verifyAndOrder(malformed),
            "diag:GroupGuardProjection:comparison-expression-invalid");

  BackendProjectionGraph nonComparison = project(balancedAtomic());
  nonComparison.guardObligations.front().guardKind = "comparison";
  nonComparison.guardObligations.front().conditionKind = "comparison";
  nonComparison.guardObligations.front().applicationMode = "comparison";
  nonComparison.edges.erase(std::remove_if(nonComparison.edges.begin(),
                                           nonComparison.edges.end(),
                                           [](const ProjectionEdge &edge) {
                                             return edge.name == "policyRef";
                                           }),
                            nonComparison.edges.end());
  ExprPtr value = parseExpr("1 + 2");
  typeExpr(*value, {});
  nonComparison.balancedEffectGroups.front().comparisonGuardExpression =
      compactJson(exprToJson(*value));
  EXPECT_EQ(verifyAndOrder(nonComparison),
            "diag:GroupGuardProjection:comparison-expression-invalid");
}

TEST(BackendProjection, EvidenceOnlyCompleteGraph) {
  BackendProjectionGraph g = project(evidenceOnly());

  ASSERT_EQ(g.executionIdentities.size(), 1u);
  const ExecutionIdentity &e = *execOf(g);
  EXPECT_EQ(e.procedureNamespace, "shipment_evidence_anchor");
  EXPECT_EQ(e.instanceKey, "shipment_ref");
  EXPECT_EQ(e.replayKey, "shipment_ref");
  EXPECT_EQ(e.invokedEvent, "procedure_invoked");

  BackendProjectionGraph missingInvokedEvent = g;
  missingInvokedEvent.executionIdentities.front().invokedEvent.clear();
  EXPECT_EQ(verifyAndOrder(missingInvokedEvent),
            "diag:ExecutionIdentity:invokedEvent-missing");

  // §2.2 attestation family.
  ASSERT_EQ(g.evidenceAcceptances.size(), 1u);
  EXPECT_EQ(g.evidenceAcceptances[0].style, "evidence-only");
  EXPECT_EQ(g.evidenceAcceptances[0].admissibility, "exact");
  EXPECT_EQ(g.evidenceAcceptances[0].bindingValue, "input:1");
  ASSERT_EQ(g.references.size(), 1u);
  EXPECT_EQ(g.references[0].ref, "0");
  EXPECT_EQ(g.references[0].role, "observerSet");
  // S0.1: the lossless raw observer-set name is carried in bindingValue
  // (here "0", the hand-built fixture's raw value), independent of `ref`.
  EXPECT_EQ(g.references[0].bindingValue, "0");
  ASSERT_EQ(g.quorumPolicies.size(), 1u);
  const QuorumPolicy &pol = g.quorumPolicies[0];
  EXPECT_EQ(pol.threshold, 2);
  EXPECT_EQ(pol.timeout, "PT48H");
  EXPECT_TRUE(hasEdge(g, "inputRef", pol.id, g.evidenceAcceptances[0].id));
  EXPECT_TRUE(hasEdge(g, "observerSetRef", pol.id, g.references[0].id));
  ASSERT_EQ(g.guardObligations.size(), 1u);
  EXPECT_EQ(g.guardObligations[0].guardKind, "attested");
  EXPECT_EQ(g.guardObligations[0].applicationMode, "atomic-refuse");
  EXPECT_TRUE(hasEdge(g, "policyRef", g.guardObligations[0].id, pol.id));
  ASSERT_EQ(g.primitiveObligations.size(), 1u);
  EXPECT_EQ(g.primitiveObligations[0].finalizedKind, "QuorumAcceptance.Single");
  EXPECT_TRUE(hasEdge(g, "policyRef", g.primitiveObligations[0].id, pol.id));

  // §2.1 commit binds to the policy by scopeRef (never by name), terminal
  // covers it.
  ASSERT_EQ(g.commitStates.size(), 1u);
  EXPECT_EQ(g.commitStates[0].idempotencyKey, "shipment_ref");
  EXPECT_TRUE(hasEdge(g, "execRef", g.commitStates[0].id, e.id));
  EXPECT_TRUE(hasEdge(g, "scopeRef", g.commitStates[0].id, pol.id));
  const LifecycleState *closed = stateByName(g, "CLOSED");
  ASSERT_NE(closed, nullptr);
  EXPECT_TRUE(closed->terminal);
  EXPECT_EQ(closed->terminalKind, TerminalKind::Success);
  EXPECT_TRUE(
      hasEdge(g, "requiredCommitRefs", closed->id, g.commitStates[0].id));

  // No effect family for an evidence-only coordination.
  EXPECT_TRUE(g.ledgerPostings.empty());
  EXPECT_TRUE(g.balancedEffectGroups.empty());
  EXPECT_TRUE(g.balanceAssertions.empty());
}

TEST(BackendProjection, BalancedAtomicEffectFamily) {
  BackendProjectionGraph g = project(balancedAtomic());

  // Single atomic-refuse policy -> Single primitive + attested group guard.
  ASSERT_EQ(g.primitiveObligations.size(), 1u);
  EXPECT_EQ(g.primitiveObligations[0].finalizedKind, "QuorumAcceptance.Single");
  ASSERT_EQ(g.guardObligations.size(), 1u);
  EXPECT_EQ(g.guardObligations[0].guardKind, "attested");

  // One posting per effect; operands deduped by (kind,value): amount+currency
  // shared, ledger+party distinct -> 6 operands.
  ASSERT_EQ(g.ledgerPostings.size(), 2u);
  EXPECT_EQ(g.typedOperands.size(), 6u);
  const LedgerPosting &debit = g.ledgerPostings[0].direction == "debit"
                                   ? g.ledgerPostings[0]
                                   : g.ledgerPostings[1];
  EXPECT_EQ(edgeCount(g, "ledgerRef", debit.id), 1);
  EXPECT_EQ(edgeCount(g, "partyRef", debit.id), 1);
  EXPECT_EQ(edgeCount(g, "amountRef", debit.id), 1);
  EXPECT_EQ(edgeCount(g, "currencyRef", debit.id), 1);
  EXPECT_EQ(edgeCount(g, "groupRef", debit.id), 1);

  // One balanced group, guardRef -> the guard, effectRefs inverse-exact.
  ASSERT_EQ(g.balancedEffectGroups.size(), 1u);
  const BalancedEffectGroup &grp = g.balancedEffectGroups[0];
  EXPECT_TRUE(grp.mustBalance);
  EXPECT_TRUE(hasEdge(g, "guardRef", grp.id, g.guardObligations[0].id));
  EXPECT_EQ(edgeCount(g, "effectRefs", grp.id), 2);

  // Coordination-scoped balance assertion covers the mustBalance group.
  ASSERT_EQ(g.balanceAssertions.size(), 1u);
  EXPECT_TRUE(hasEdge(g, "assertsRefs", g.balanceAssertions[0].id, grp.id));

  // Rollback obligation on the balanced group (atomic context).
  ASSERT_EQ(g.compensationObligations.size(), 1u);
  EXPECT_EQ(g.compensationObligations[0].mode, "rollback");
  EXPECT_TRUE(
      hasEdge(g, "compensates", g.compensationObligations[0].id, grp.id));

  // The COMMIT transition references the posted group.
  ASSERT_EQ(g.transitions.size(), 1u);
  EXPECT_TRUE(hasEdge(g, "effectGroupRefs", g.transitions[0].id, grp.id));
}

TEST(BackendProjection, MultiPolicyPerPolicyCommitsAndPrimitive) {
  BackendProjectionGraph g = project(multiPolicyTemporal());

  // Temporal -> PerPolicy primitive ranging over both policies.
  ASSERT_EQ(g.primitiveObligations.size(), 1u);
  EXPECT_EQ(g.primitiveObligations[0].finalizedKind,
            "QuorumAcceptance.PerPolicy");
  EXPECT_EQ(edgeCount(g, "policyRef", g.primitiveObligations[0].id), 2);
  // Each temporal group carries its projected policy guard; the targets
  // consume these typed associations instead of re-reading PlanGateMode.
  ASSERT_EQ(g.guardObligations.size(), 2u);
  for (const GuardObligation &guard : g.guardObligations) {
    EXPECT_EQ(guard.guardKind, "attested");
    EXPECT_EQ(guard.applicationMode, "temporal-suppress");
    EXPECT_EQ(edgeCount(g, "policyRef", guard.id), 1);
  }
  for (const BalancedEffectGroup &group : g.balancedEffectGroups)
    EXPECT_EQ(edgeCount(g, "guardRef", group.id), 1);

  // One CommitState per policy scope, each scopeRef -> its own policy.
  ASSERT_EQ(g.commitStates.size(), 2u);
  const QuorumPolicy *pA = policyByThreshold(g, 2);
  const QuorumPolicy *pB = policyByThreshold(g, 3);
  ASSERT_NE(pA, nullptr);
  ASSERT_NE(pB, nullptr);
  int toA = 0, toB = 0;
  for (const auto &c : g.commitStates) {
    if (hasEdge(g, "scopeRef", c.id, pA->id))
      ++toA;
    if (hasEdge(g, "scopeRef", c.id, pB->id))
      ++toB;
  }
  EXPECT_EQ(toA, 1);
  EXPECT_EQ(toB, 1);

  // Terminal requiredCommitRefs EXACTLY cover both commits.
  const LifecycleState *closed = stateByName(g, "CLOSED");
  ASSERT_NE(closed, nullptr);
  EXPECT_EQ(edgeCount(g, "requiredCommitRefs", closed->id), 2);
}

TEST(BackendProjection, Deterministic) {
  CoordinationPlan p = balancedAtomic();
  BackendProjectionGraph a = project(p);
  BackendProjectionGraph b = project(balancedAtomic());
  ASSERT_EQ(a.edges.size(), b.edges.size());
  for (size_t i = 0; i < a.edges.size(); ++i) {
    EXPECT_EQ(a.edges[i].from, b.edges[i].from);
    EXPECT_EQ(a.edges[i].name, b.edges[i].name);
    EXPECT_EQ(a.edges[i].to, b.edges[i].to);
  }
  ASSERT_EQ(a.ledgerPostings.size(), b.ledgerPostings.size());
  for (size_t i = 0; i < a.ledgerPostings.size(); ++i)
    EXPECT_EQ(a.ledgerPostings[i].id, b.ledgerPostings[i].id);
}

TEST(BackendProjection, CanonicalCodecIsLosslessAndDeterministic) {
  const CoordinationPlan plans[] = {evidenceOnly(), balancedAtomic(),
                                    codecTemporal(), withComputes()};
  for (const CoordinationPlan &plan : plans) {
    BackendProjectionGraph original = project(plan);
    llvm::Expected<std::string> first = encodeFinalizedProjection(original);
    ASSERT_TRUE(static_cast<bool>(first)) << llvm::toString(first.takeError());
    llvm::Expected<std::string> second = encodeFinalizedProjection(original);
    ASSERT_TRUE(static_cast<bool>(second))
        << llvm::toString(second.takeError());
    EXPECT_EQ(*first, *second);
    llvm::Expected<llvm::json::Value> canonical = llvm::json::parse(*first);
    ASSERT_TRUE(static_cast<bool>(canonical))
        << llvm::toString(canonical.takeError());
    EXPECT_EQ(compactJson(*canonical), *first);

    llvm::Expected<BackendProjectionGraph> decoded =
        decodeFinalizedProjection(*first);
    ASSERT_TRUE(static_cast<bool>(decoded))
        << llvm::toString(decoded.takeError());
    EXPECT_TRUE(verifyAndOrder(*decoded).empty());
    llvm::Expected<FinalizedProjectionSequence> originalSequence =
        consumeFinalizedProjectionSequence(original);
    ASSERT_TRUE(static_cast<bool>(originalSequence))
        << llvm::toString(originalSequence.takeError());
    llvm::Expected<FinalizedProjectionSequence> decodedSequence =
        consumeFinalizedProjectionSequence(*decoded);
    ASSERT_TRUE(static_cast<bool>(decodedSequence))
        << llvm::toString(decodedSequence.takeError());

    llvm::Expected<std::string> roundTrip = encodeFinalizedProjection(*decoded);
    ASSERT_TRUE(static_cast<bool>(roundTrip))
        << llvm::toString(roundTrip.takeError());
    EXPECT_EQ(*first, *roundTrip);
    EXPECT_EQ(originalSequence->executionMode, decodedSequence->executionMode);
    EXPECT_EQ(originalSequence->attestationKind,
              decodedSequence->attestationKind);
    EXPECT_EQ(originalSequence->lifecycleRoles.size(),
              decodedSequence->lifecycleRoles.size());
    EXPECT_EQ(originalSequence->effectGroups.size(),
              decodedSequence->effectGroups.size());
    EXPECT_EQ(originalSequence->postings.size(),
              decodedSequence->postings.size());
  }
}

TEST(BackendProjection, CodecEncoderRejectsUnknownEnum) {
  BackendProjectionGraph graph = project(evidenceOnly());
  ASSERT_FALSE(graph.lifecycleStates.empty());
  graph.lifecycleStates[0].terminalKind = static_cast<TerminalKind>(99);
  llvm::Expected<std::string> encoded = encodeFinalizedProjection(graph);
  ASSERT_FALSE(static_cast<bool>(encoded));
  EXPECT_NE(llvm::toString(encoded.takeError())
                .find("unknown TerminalKind enumerator"),
            std::string::npos);
}

TEST(BackendProjection, CodecRejectsNonCanonicalBytes) {
  llvm::Expected<std::string> canonical =
      encodeFinalizedProjection(project(evidenceOnly()));
  ASSERT_TRUE(static_cast<bool>(canonical))
      << llvm::toString(canonical.takeError());

  expectDecodeBytesError(" " + *canonical, "non-canonical encoding");

  const size_t kindDelimiter = canonical->find(",\"kind\":");
  const size_t nodesDelimiter = canonical->find(",\"nodes\":", kindDelimiter);
  ASSERT_NE(kindDelimiter, std::string::npos);
  ASSERT_NE(nodesDelimiter, std::string::npos);
  const size_t kindValueStart =
      kindDelimiter + llvm::StringRef(",\"kind\":").size();
  std::string reordered =
      "{\"kind\":" +
      canonical->substr(kindValueStart, nodesDelimiter - kindValueStart) + "," +
      canonical->substr(1, kindDelimiter - 1) +
      canonical->substr(nodesDelimiter);
  ASSERT_NE(reordered, *canonical);
  expectDecodeBytesError(reordered, "non-canonical encoding");
}

TEST(BackendProjection, CodecRejectsUnknownEnumAndOmittedField) {
  llvm::json::Value unknownEnum = parseEncoded(project(evidenceOnly()));
  llvm::json::Object *root = unknownEnum.getAsObject();
  ASSERT_NE(root, nullptr);
  llvm::json::Object *nodes = root->getObject("nodes");
  ASSERT_NE(nodes, nullptr);
  llvm::json::Array *states = nodes->getArray("lifecycleStates");
  ASSERT_NE(states, nullptr);
  ASSERT_FALSE(states->empty());
  llvm::json::Object *state = (*states)[0].getAsObject();
  ASSERT_NE(state, nullptr);
  (*state)["terminalKind"] = "FutureTerminal";
  expectDecodeError(std::move(unknownEnum), "unknown TerminalKind spelling");

  llvm::json::Value omitted = parseEncoded(project(evidenceOnly()));
  root = omitted.getAsObject();
  ASSERT_NE(root, nullptr);
  nodes = root->getObject("nodes");
  ASSERT_NE(nodes, nullptr);
  states = nodes->getArray("lifecycleStates");
  ASSERT_NE(states, nullptr);
  state = (*states)[0].getAsObject();
  ASSERT_NE(state, nullptr);
  state->erase("sourceRef");
  expectDecodeError(std::move(omitted), "required field is omitted");
}

TEST(BackendProjection, CodecRejectsDuplicateIdsAndMalformedEdges) {
  llvm::json::Value duplicate = parseEncoded(project(evidenceOnly()));
  llvm::json::Object *root = duplicate.getAsObject();
  ASSERT_NE(root, nullptr);
  llvm::json::Object *nodes = root->getObject("nodes");
  ASSERT_NE(nodes, nullptr);
  llvm::json::Array *states = nodes->getArray("lifecycleStates");
  ASSERT_NE(states, nullptr);
  ASSERT_GE(states->size(), 2u);
  llvm::json::Object *firstState = (*states)[0].getAsObject();
  llvm::json::Object *secondState = (*states)[1].getAsObject();
  ASSERT_NE(firstState, nullptr);
  ASSERT_NE(secondState, nullptr);
  llvm::Optional<llvm::StringRef> firstId = firstState->getString("id");
  ASSERT_TRUE(firstId.hasValue());
  (*secondState)["id"] = firstId->str();
  expectDecodeError(std::move(duplicate), "duplicate-id");

  llvm::json::Value dangling = parseEncoded(project(evidenceOnly()));
  root = dangling.getAsObject();
  ASSERT_NE(root, nullptr);
  llvm::json::Array *edges = root->getArray("edges");
  ASSERT_NE(edges, nullptr);
  ASSERT_FALSE(edges->empty());
  llvm::json::Object *edge = (*edges)[0].getAsObject();
  ASSERT_NE(edge, nullptr);
  (*edge)["to"] = "missing-node";
  expectDecodeError(std::move(dangling), "dangling");

  llvm::json::Value malformed = parseEncoded(project(evidenceOnly()));
  root = malformed.getAsObject();
  ASSERT_NE(root, nullptr);
  edges = root->getArray("edges");
  ASSERT_NE(edges, nullptr);
  ASSERT_FALSE(edges->empty());
  edge = (*edges)[0].getAsObject();
  ASSERT_NE(edge, nullptr);
  (*edge)["name"] = "unregisteredEdge";
  expectDecodeError(std::move(malformed), "unregisteredEdge-unknown");
}

TEST(BackendProjection, StableIdIsPunningProof) {
  // §2.5: a single quoted component "Q.A" must never collide with the
  // two-component path ["Q","A"].
  EXPECT_NE(projectionNodeId(ProjectionNodeKind::CommitState, {"Q.A"}),
            projectionNodeId(ProjectionNodeKind::CommitState, {"Q", "A"}));
  // Kind namespaces the id: same key, different kind -> different id.
  EXPECT_NE(projectionNodeId(ProjectionNodeKind::CommitState, {"P"}),
            projectionNodeId(ProjectionNodeKind::LifecycleState, {"P"}));
}

// ---- P1-B: no internally-invalid projection escapes as a successful graph -

TEST(BackendProjection, ProjectorSurfacesVerifierErrorAndEmitsNoGraph) {
  // Two identical lifecycle transitions project two Transition nodes with the
  // same (name, from, to) stable id -> the verifier's uniqueness check fails,
  // and the projector must surface it as an Error, never return a graph.
  CoordinationPlan p = evidenceOnly();
  p.evidenceOnly = false; // give it a transition-bearing lifecycle
  p.terminal.success = "B";
  LifecycleTransitionPolicy t1, t2;
  t1.name = t2.name = "COMMIT";
  t1.from = t2.from = "A";
  t1.to = t2.to = "B";
  p.lifecycleTransitions = {t1, t2};
  llvm::Expected<BackendProjectionGraph> g = projectBackendGraph(p);
  ASSERT_FALSE(static_cast<bool>(g));
  EXPECT_EQ(llvm::toString(g.takeError()), "diag:Transition:duplicate-id");
}

// ---- verifier rejects an internally-invalid graph (dangling / kind /
// coverage / cardinality) --------------------------------------------------

TEST(BackendProjection, VerifierCatchesDanglingEdge) {
  BackendProjectionGraph g = project(evidenceOnly());
  for (auto &e : g.edges)
    if (e.name == "execRef")
      e.to = "id:does-not-exist";
  EXPECT_EQ(verifyAndOrder(g), "diag:edge:execRef-dangling");
}

TEST(BackendProjection, VerifierCatchesSwappedScopeKind) {
  BackendProjectionGraph g = project(balancedAtomic());
  // Point a scopeRef at a LedgerPosting instead of a QuorumPolicy (wrong kind).
  const std::string post = g.ledgerPostings.front().id;
  for (auto &e : g.edges)
    if (e.name == "scopeRef")
      e.to = post;
  EXPECT_EQ(verifyAndOrder(g), "diag:edge:scopeRef-to-kind");
}

TEST(BackendProjection, VerifierCatchesMissingBalanceCoverage) {
  BackendProjectionGraph g = project(balancedAtomic());
  // Drop the assertsRefs edge -> the balance assertion no longer covers the
  // mustBalance group.
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [](const ProjectionEdge &e) {
                                 return e.name == "assertsRefs";
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:BalanceAssertion:coverage");
}

// ---- §2.1 ProjectedLifecycleRole ( G1-S1): projected role/mode + verify -
// The status-authority lowering roles are decided in the projection (never by a
// backend), keyed per execution mode, and anchored to the projected success
// terminal. The legalizers CONSUME this set (see the backend tests); here we
// pin the set the projector emits per mode and every verifier refusal.

TEST(BackendProjection, ProjectedLifecycleRoleEvidenceSet) {
  BackendProjectionGraph g = project(evidenceOnly());
  const LifecycleState *closed = stateByName(g, "CLOSED");
  ASSERT_NE(closed, nullptr);
  ASSERT_EQ(closed->terminalKind, TerminalKind::Success);
  std::set<LifecycleRole> roles;
  for (const auto &r : g.projectedLifecycleRoles) {
    EXPECT_EQ(r.mode, ExecutionMode::Evidence);
    EXPECT_EQ(r.state, "CLOSED");
    EXPECT_TRUE(hasEdge(g, "stateRef", r.id, closed->id));
    roles.insert(r.role);
  }
  EXPECT_EQ(roles, (std::set<LifecycleRole>{LifecycleRole::Initial,
                                            LifecycleRole::Success}));
}

TEST(BackendProjection, ProjectedLifecycleRoleEffectfulAddsAttestCheckpoint) {
  BackendProjectionGraph g = project(balancedAtomic());
  std::set<LifecycleRole> roles;
  for (const auto &r : g.projectedLifecycleRoles) {
    EXPECT_EQ(r.mode, ExecutionMode::Effectful);
    roles.insert(r.role);
  }
  EXPECT_EQ(roles, (std::set<LifecycleRole>{LifecycleRole::Initial,
                                            LifecycleRole::AcceptedOrAttested,
                                            LifecycleRole::Success}));
}

TEST(BackendProjection, ProjectedLifecycleRoleTemporalSet) {
  BackendProjectionGraph g = project(multiPolicyTemporal());
  std::set<LifecycleRole> roles;
  for (const auto &r : g.projectedLifecycleRoles) {
    EXPECT_EQ(r.mode, ExecutionMode::Temporal);
    roles.insert(r.role);
  }
  EXPECT_EQ(roles, (std::set<LifecycleRole>{LifecycleRole::Initial,
                                            LifecycleRole::Success}));
}

TEST(BackendProjection, VerifierCatchesMissingProjectedRoles) {
  BackendProjectionGraph g = project(evidenceOnly());
  g.projectedLifecycleRoles.clear();
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [](const ProjectionEdge &e) {
                                 return e.name == "stateRef";
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:ProjectedLifecycleRole:missing");
}

TEST(BackendProjection, VerifierCatchesRoleMissingStateRef) {
  BackendProjectionGraph g = project(evidenceOnly());
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [](const ProjectionEdge &e) {
                                 return e.name == "stateRef";
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g),
            "diag:ProjectedLifecycleRole:stateRef-cardinality");
}

TEST(BackendProjection, VerifierCatchesIncompleteRoleSet) {
  BackendProjectionGraph g = project(evidenceOnly());
  // Drop the Initial role AND its anchoring edge -> the set no longer equals
  // the required {Initial, Success} for evidence mode.
  ASSERT_FALSE(g.projectedLifecycleRoles.empty());
  std::string dropped;
  for (auto it = g.projectedLifecycleRoles.begin();
       it != g.projectedLifecycleRoles.end(); ++it)
    if (it->role == LifecycleRole::Initial) {
      dropped = it->id;
      g.projectedLifecycleRoles.erase(it);
      break;
    }
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [&](const ProjectionEdge &e) {
                                 return e.name == "stateRef" &&
                                        e.from == dropped;
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:ProjectedLifecycleRole:role-set");
}

TEST(BackendProjection, VerifierCatchesRoleAnchoredToNonSuccessTerminal) {
  BackendProjectionGraph g = project(evidenceOnly());
  const LifecycleState *open = stateByName(g, "OPEN");
  ASSERT_NE(open, nullptr);
  ASSERT_NE(open->terminalKind, TerminalKind::Success);
  for (auto &e : g.edges)
    if (e.name == "stateRef") {
      e.to = open->id;
      break;
    }
  EXPECT_EQ(verifyAndOrder(g),
            "diag:ProjectedLifecycleRole:stateRef-not-success-terminal");
}

TEST(BackendProjection, VerifierCatchesInconsistentRoleMode) {
  BackendProjectionGraph g = project(evidenceOnly());
  ASSERT_GE(g.projectedLifecycleRoles.size(), 2u);
  g.projectedLifecycleRoles.back().mode = ExecutionMode::Effectful;
  EXPECT_EQ(verifyAndOrder(g), "diag:ProjectedLifecycleRole:mode-inconsistent");
}

TEST(BackendProjection, VerifierCatchesUniformEvidenceToTemporalSubstitution) {
  // The reviewer's P1-A: flip the COMPLETE mode set (not one role) from
  // Evidence to Temporal. Both modes require {Initial, Success}, so the role
  // set stays internally consistent — but the graph structure (evidence-only
  // style) still says Evidence, so the independent re-derivation rejects it.
  BackendProjectionGraph g = project(evidenceOnly());
  for (auto &r : g.projectedLifecycleRoles)
    r.mode = ExecutionMode::Temporal;
  EXPECT_EQ(verifyAndOrder(g),
            "diag:ProjectedLifecycleRole:mode-structure-mismatch");
}

TEST(BackendProjection, VerifierCatchesUniformTemporalToEvidenceSubstitution) {
  // The other same-role-set pair: a temporal graph forged to Evidence. The
  // balanced group carries no rollback obligation (temporal structure), so the
  // re-derivation still says Temporal.
  BackendProjectionGraph g = project(multiPolicyTemporal());
  for (auto &r : g.projectedLifecycleRoles)
    r.mode = ExecutionMode::Evidence;
  EXPECT_EQ(verifyAndOrder(g),
            "diag:ProjectedLifecycleRole:mode-structure-mismatch");
}

TEST(BackendProjection, VerifierCatchesStatePayloadEdgeDisagreement) {
  // The reviewer's P1-B: change the serialized `state` payload while leaving
  // the typed `stateRef` edge intact. The edge is the sole association
  // authority, so the payload must equal the state it resolves to.
  BackendProjectionGraph g = project(evidenceOnly());
  ASSERT_FALSE(g.projectedLifecycleRoles.empty());
  g.projectedLifecycleRoles.front().state = "FORGED";
  EXPECT_EQ(verifyAndOrder(g),
            "diag:ProjectedLifecycleRole:state-edge-disagreement");
}

TEST(BackendProjection, VerifierCatchesComparisonGuardWithPolicy) {
  BackendProjectionGraph g = project(balancedAtomic());
  // Flip the attested guard to comparison while keeping its policyRef -> F12.
  for (auto &gd : g.guardObligations)
    gd.guardKind = "comparison";
  EXPECT_EQ(verifyAndOrder(g), "diag:GuardObligation:policyRef-cardinality");
}

// ---- completeness: a MISSING required node must be caught (a node that owns
// no edge would otherwise slip past the per-edge checks) --------------------

TEST(BackendProjection, VerifierCatchesMissingBalanceAssertion) {
  BackendProjectionGraph g = project(balancedAtomic());
  // Drop the whole BalanceAssertion node + its edges: a mustBalance group is
  // now left with no covering assertion.
  const std::string ba = g.balanceAssertions.front().id;
  g.balanceAssertions.clear();
  g.edges.erase(
      std::remove_if(g.edges.begin(), g.edges.end(),
                     [&](const ProjectionEdge &e) { return e.from == ba; }),
      g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:BalanceAssertion:missing");
}

TEST(BackendProjection, VerifierCatchesSinglePrimitiveWithExtraPolicyRef) {
  BackendProjectionGraph g = project(evidenceOnly());
  // A .Single primitive must range over EXACTLY one policy; add a second
  // (self) policyRef and the exact-one check fires.
  ASSERT_EQ(g.primitiveObligations.size(), 1u);
  ASSERT_EQ(g.primitiveObligations[0].finalizedKind, "QuorumAcceptance.Single");
  g.edges.push_back(
      {g.primitiveObligations[0].id, "policyRef", g.quorumPolicies[0].id, "x"});
  EXPECT_EQ(verifyAndOrder(g),
            "diag:PrimitiveObligation:single-policyRef-cardinality");
}

TEST(BackendProjection, VerifierCatchesUnknownFinalizedKind) {
  BackendProjectionGraph g = project(evidenceOnly());
  ASSERT_EQ(g.primitiveObligations.size(), 1u);
  // An unknown finalizedKind must NOT be silently accepted as PerPolicy.
  g.primitiveObligations[0].finalizedKind = "QuorumAcceptance.Bogus";
  EXPECT_EQ(verifyAndOrder(g),
            "diag:PrimitiveObligation:unknown-finalizedKind");
}

TEST(BackendProjection, VerifierCatchesDuplicateCompensation) {
  BackendProjectionGraph g = project(balancedAtomic());
  // Add a second well-formed compensation node for the same group: each owner
  // keeps its required single edge, so only exact group coverage can catch the
  // duplicate.
  ASSERT_EQ(g.compensationObligations.size(), 1u);
  CompensationObligation dupNode = g.compensationObligations.front();
  dupNode.id += ".duplicate";
  g.compensationObligations.push_back(dupNode);
  ProjectionEdge dup;
  for (const auto &e : g.edges)
    if (e.name == "compensates") {
      dup = e;
      break;
    }
  ASSERT_FALSE(dup.name.empty());
  dup.from = dupNode.id;
  g.edges.push_back(dup);
  EXPECT_EQ(verifyAndOrder(g),
            "diag:CompensationObligation:duplicate-coverage");
}

TEST(BackendProjection, VerifierCatchesAllCompensationsDeleted) {
  BackendProjectionGraph g = project(balancedAtomic());
  // Delete EVERY compensation node + its compensates edge. The balanced group
  // still requires rollback (rollbackRequired stays true), so the empty
  // compensated set no longer covers it — the verifier must NOT skip this.
  ASSERT_FALSE(g.compensationObligations.empty());
  std::set<std::string> comps;
  for (const auto &c : g.compensationObligations)
    comps.insert(c.id);
  g.compensationObligations.clear();
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [&](const ProjectionEdge &e) {
                                 return comps.count(e.from);
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:CompensationObligation:coverage");
}

TEST(BackendProjection, VerifierCatchesComputeNodeWithNoOperands) {
  BackendProjectionGraph g = project(withComputes());
  ASSERT_FALSE(g.computeNodes.empty());
  const std::string cn = g.computeNodes.front().id;
  // Strip the compute's operand refs: a ComputeNode must carry 1..n (§3).
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [&](const ProjectionEdge &e) {
                                 return e.name == "operandRefs" && e.from == cn;
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:ComputeNode:operandRefs-cardinality");
}

TEST(BackendProjection, VerifierCatchesOrphanCommitWithNoTerminal) {
  BackendProjectionGraph g = project(evidenceOnly());
  // Drop every terminal LifecycleState and the fixture-only transition that
  // reaches it: the CommitState is now orphaned (no terminal requires it).
  std::set<std::string> terminals;
  for (const auto &s : g.lifecycleStates)
    if (s.terminal)
      terminals.insert(s.id);
  std::set<std::string> transitions;
  for (const auto &t : g.transitions)
    transitions.insert(t.id);
  g.lifecycleStates.erase(
      std::remove_if(g.lifecycleStates.begin(), g.lifecycleStates.end(),
                     [](const LifecycleState &s) { return s.terminal; }),
      g.lifecycleStates.end());
  g.transitions.clear();
  g.edges.erase(std::remove_if(g.edges.begin(), g.edges.end(),
                               [&](const ProjectionEdge &e) {
                                 return terminals.count(e.from) ||
                                        terminals.count(e.to) ||
                                        transitions.count(e.from);
                               }),
                g.edges.end());
  EXPECT_EQ(verifyAndOrder(g), "diag:LifecycleState:missing-terminal");
}

// ---- S0.1 Reference.bindingValue witnesses -------------------------------

TEST(BackendProjection, S0BindingValueIsLosslessAndDistinctFromRef) {
  CoordinationPlan p = evidenceOnly();
  p.attestations[0].observerSet = "logistics_oracles"; // raw name != ordinal
  BackendProjectionGraph g = project(p);
  ASSERT_EQ(g.references.size(), 1u);
  EXPECT_EQ(g.references[0].role, "observerSet");
  // The raw name is carried losslessly, INDEPENDENT of the ordinal `ref`.
  EXPECT_EQ(g.references[0].bindingValue, "logistics_oracles");
  EXPECT_NE(g.references[0].bindingValue, g.references[0].ref);
}

TEST(BackendProjection, VerifierCatchesMissingObserverSetBinding) {
  BackendProjectionGraph g = project(evidenceOnly());
  // Drop the lossless authorization operand from an observer-set reference: the
  // ordinal `ref` still identifies it, but the reviewed gate has nothing to
  // authorize against. Fail closed.
  ASSERT_EQ(g.references.size(), 1u);
  ASSERT_EQ(g.references[0].role, "observerSet");
  g.references[0].bindingValue.clear();
  EXPECT_EQ(verifyAndOrder(g),
            "diag:Reference:observerSet-bindingValue-missing");
}

TEST(BackendProjection, VerifierCatchesSpuriousBindingOnNonObserverSet) {
  BackendProjectionGraph g = project(evidenceOnly());
  // A binding value smuggled onto a non-observer-set reference is spurious —
  // the operand exists EXACTLY for role==observerSet.
  ASSERT_EQ(g.references.size(), 1u);
  ASSERT_FALSE(g.references[0].bindingValue.empty());
  g.references[0].role = "ledger";
  EXPECT_EQ(verifyAndOrder(g),
            "diag:Reference:non-observerSet-bindingValue-spurious");
}

TEST(BackendProjection, VerifierCatchesMissingAcceptedInputBinding) {
  BackendProjectionGraph g = project(evidenceOnly());
  ASSERT_EQ(g.evidenceAcceptances.size(), 1u);
  g.evidenceAcceptances[0].bindingValue.clear();
  EXPECT_EQ(verifyAndOrder(g), "diag:EvidenceAcceptance:bindingValue-missing");
}

TEST(BackendProjection, VerifierCatchesUnknownGuardApplicationMode) {
  BackendProjectionGraph g = project(multiPolicyTemporal());
  ASSERT_FALSE(g.guardObligations.empty());
  g.guardObligations[0].applicationMode = "backend-inferred";
  EXPECT_EQ(verifyAndOrder(g), "diag:GuardObligation:application-mode");
}

// ---- S0 consumes 's projected execution rail, owns no second one -------

TEST(BackendProjection, S0ConsumesProjectedLifecycleModeNotASecondRailNode) {
  // The acceptance/execution rail is 's ProjectedLifecycleRole.mode; S0
  // introduces NO second rail representation. An evidence-only coordination's
  // projected roles carry ExecutionMode::Evidence — the single rail fact the
  //  consumer reads (never re-derived into another core enum).
  BackendProjectionGraph g = project(evidenceOnly());
  ASSERT_FALSE(g.projectedLifecycleRoles.empty());
  for (const auto &r : g.projectedLifecycleRoles)
    EXPECT_EQ(r.mode, ExecutionMode::Evidence);
}

} // namespace
