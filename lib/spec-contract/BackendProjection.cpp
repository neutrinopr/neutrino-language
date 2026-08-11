//===- BackendProjection.cpp - shared backend projection graph () -----===//
//
// The domain-blind projection of the verified CoordinationPlan into the
// COMPLETE closed BackendProjectionGraph (see include/Neutrino/
// BackendProjection.h and docs/process/M6_BACKEND_PROJECTION_MODEL.md). Reads
// only the `CoordinationPlan`.
//
// Per the  P1-A ruling the projector is NOT partial: it emits every §2 node
// family and every §3 cross-family typed edge in one pass, with exact §3
// cardinalities established by `verifyAndOrder`. Association is carried by
// typed edges (`scopeRef`, `inputRef`, `observerSetRef`, `guardRef`,
// `groupRef`, `effectRefs`, `assertsRefs`, the posting operand refs,
// `compensates`, …), never re-inferred by name / order — so no field is used as
// an association carrier for a later reconstruction.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/BackendProjection.h"

#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY
#include "Neutrino/CanonicalLabels.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationEnvelope.h"
#endif
#include "Neutrino/JsonUtil.h"
#include "Neutrino/ValueModel.h"

#include <algorithm>
#include <functional>
#include <map>
#include <set>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

namespace neutrino {
namespace projection {

#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY
static std::string
finalizedInvokedEvent(const CoordinationPlan &coordinationPlan) {
  return coordinationPlan.invokedEvent.empty() ? "procedure_invoked"
                                               : coordinationPlan.invokedEvent;
}

// §2.5 canonical, length-prefixed, collision-proof id: the node-kind ordinal
// followed by `<len>:<component>` for each identifying component. Length-
// prefixing makes punning impossible — one quoted component "Q.A" (`3:Q.A`)
// cannot collide with the two-component path ["Q","A"] (`1:Q1:A`), and no
// separator/quote needs escaping. NEVER a display name.
std::string projectionNodeId(ProjectionNodeKind kind,
                             const std::vector<std::string> &components) {
  std::string id = std::to_string(static_cast<int>(kind));
  for (const std::string &c : components)
    id += "|" + std::to_string(c.size()) + ":" + c;
  return id;
}
#endif

namespace {

#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY
// A temporal (per-policy) coordination — any effect suppressed per-policy — vs
// a single-shot / evidence-only one. This is the sole execution-mode decision;
// the finalized primitive kind matches their dispatch (§5/§6).
bool coordinationIsTemporal(const CoordinationPlan &coordinationPlan) {
  for (const PlanEffect &e : coordinationPlan.effects)
    if (e.gateMode == PlanGateMode::TemporalSuppress)
      return true;
  return false;
}

TerminalKind terminalKindOf(const CoordinationPlan &coordinationPlan,
                            const std::string &name) {
  if (!coordinationPlan.terminal.success.empty() &&
      name == coordinationPlan.terminal.success)
    return TerminalKind::Success;
  if (!coordinationPlan.terminal.aborted.empty() &&
      name == coordinationPlan.terminal.aborted)
    return TerminalKind::Aborted;
  if (!coordinationPlan.terminal.contested.empty() &&
      name == coordinationPlan.terminal.contested)
    return TerminalKind::Contested;
  return TerminalKind::None;
}

// The closed evidence admissibility (§2.2). Today it mirrors the policy's
// canonicalization ("exact" | "median"); an unset canonicalization is the exact
// default.
std::string admissibilityOf(const AttestationPolicy &p) {
  return p.canonicalization.empty() ? "exact" : p.canonicalization;
}
#endif

// The closed ComputeNode exprKind vocabulary (§2.4), mirroring the
// `CoordinationPlan` semantic-expression kinds.
const char *exprKindName(ExprNode::Kind k) {
  switch (k) {
  case ExprNode::Num:
    return "number";
  case ExprNode::Var:
    return "value";
  case ExprNode::Bin:
    return "binary";
  case ExprNode::Cmp:
    return "compare";
  case ExprNode::Call:
    return "call";
  }
  return "value";
}

#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY
// The projection is a total function of the `CoordinationPlan`: it emits
// exactly one node per construct in each 1:1 family. A count mismatch means a
// required node was dropped (a missing node owns no edge to dangle, so the
// graph verifier alone would pass it). Returns a stable diagnostic, or "" when
// complete.
std::string
completenessAgainstCoordination(const CoordinationPlan &coordinationPlan,
                                const BackendProjectionGraph &g) {
  if (g.executionIdentities.size() != 1)
    return "diag:completeness:executionIdentity-count";
  const ExecutionIdentity &exec = g.executionIdentities.front();
  if (exec.invokedEvent != finalizedInvokedEvent(coordinationPlan) ||
      exec.coordinationIdentity != coordinationIdentityHash(coordinationPlan) ||
      exec.claimInputs.size() != coordinationPlan.inputs.size())
    return "diag:completeness:executionIdentity-lowering-payload";
  for (size_t i = 0; i < exec.claimInputs.size(); ++i)
    if (exec.claimInputs[i].name != coordinationPlan.inputs[i].name ||
        exec.claimInputs[i].type != coordinationPlan.inputs[i].type)
      return "diag:completeness:executionIdentity-claim-input";
  if (coordinationPlan.terminal.success.empty())
    return "diag:completeness:success-terminal";
  if (g.ledgerPostings.size() != coordinationPlan.effects.size())
    return "diag:completeness:ledgerPosting-count";
  for (const LedgerPosting &posting : g.ledgerPostings) {
    if (posting.effectIndex < 0 || static_cast<size_t>(posting.effectIndex) >=
                                       coordinationPlan.effects.size())
      return "diag:completeness:ledgerPosting-index";
    const PlanEffect &effect =
        coordinationPlan.effects[static_cast<size_t>(posting.effectIndex)];
    if (posting.direction != effect.kind || posting.name != effect.name ||
        posting.ledger != effect.ledger || posting.party != effect.party ||
        posting.amount != effect.amount ||
        posting.currency != effect.currency || posting.memo != effect.memo)
      return "diag:completeness:ledgerPosting-lowering-payload";
  }
  if (g.quorumPolicies.size() != coordinationPlan.attestations.size())
    return "diag:completeness:quorumPolicy-count";
  if (g.evidenceAcceptances.size() != coordinationPlan.attestations.size())
    return "diag:completeness:evidenceAcceptance-count";
  if (g.references.size() != coordinationPlan.attestations.size())
    return "diag:completeness:reference-count";
  if (g.balancedEffectGroups.size() != coordinationPlan.effectGroups.size())
    return "diag:completeness:balancedEffectGroup-count";
  for (const BalancedEffectGroup &group : g.balancedEffectGroups) {
    auto found = std::find_if(
        coordinationPlan.effectGroups.begin(),
        coordinationPlan.effectGroups.end(), [&](const PlanEffectGroup &item) {
          return static_cast<int>(item.firstIndex) == group.firstIndex;
        });
    if (found == coordinationPlan.effectGroups.end())
      return "diag:completeness:balancedEffectGroup-index";
    std::string expectedGuard;
    if (found->gateMode == PlanGateMode::None && !found->effectIndices.empty())
      if (const ExprNode *guard =
              coordinationPlan.effects[found->effectIndices.front()]
                  .guard.get())
        expectedGuard = compactJson(exprToJson(*guard));
    if (group.gateMode != found->gateMode ||
        group.gatePolicy != found->gatePolicy ||
        group.comparisonGuardExpression != expectedGuard)
      return "diag:completeness:balancedEffectGroup-lowering-payload";
  }
  if (g.typedParams.size() != coordinationPlan.inputs.size())
    return "diag:completeness:typedParam-count";
  if (g.computeNodes.size() != coordinationPlan.computes.size())
    return "diag:completeness:computeNode-count";
  // (CompensationObligation coverage is verified EXACTLY per-group in
  // verifyAndOrder via each group's `rollbackRequired` flag — not by a count
  // here, which a duplicate could satisfy while a group went uncompensated.)
  return "";
}
#endif

} // namespace

#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY
llvm::Expected<BackendProjectionGraph>
projectBackendGraph(const CoordinationPlan &coordinationPlan) {
  BackendProjectionGraph g;
  const bool temporal = coordinationIsTemporal(coordinationPlan);

  // §2.5: a node's operand / observer / param identity is the CANONICAL
  // structural label, never a source display name. Establish the labels up
  // front (in this core, BEFORE verification) so every leaf value the graph
  // carries is already canonical and the verifier operates on the real values.
  SemanticLabels labels(coordinationPlan);
  establishProjectionLabels(coordinationPlan, labels);

  // ---- §2.1 ExecutionIdentity — one per coordination ----------------------
  ExecutionIdentity exec;
  exec.id = projectionNodeId(ProjectionNodeKind::ExecutionIdentity,
                             {coordinationPlan.procedure});
  exec.procedureNamespace = coordinationPlan.procedure;
  exec.instanceKey = coordinationPlan.workflowKey;
  exec.replayKey = coordinationPlan.workflowKey;
  exec.invokedEvent = finalizedInvokedEvent(coordinationPlan);
  exec.coordinationIdentity = coordinationIdentityHash(coordinationPlan);
  for (const PlanInput &input : coordinationPlan.inputs)
    exec.claimInputs.push_back({input.name, input.type});
  exec.sourceRef = "coordinationPlan.procedure";
  g.executionIdentities.push_back(exec);

  // ---- §2.2 per attestation policy: EvidenceAcceptance, Reference, Policy --
  std::unordered_map<std::string, std::string> policyIdByInput;
  for (size_t i = 0; i < coordinationPlan.attestations.size(); ++i) {
    const AttestationPolicy &p = coordinationPlan.attestations[i];
    const std::string aref =
        "coordinationPlan.attestations[" + std::to_string(i) + "]";

    EvidenceAcceptance evid;
    evid.id =
        projectionNodeId(ProjectionNodeKind::EvidenceAcceptance, {p.input});
    evid.bindingValue = p.input;
    evid.style = coordinationPlan.evidenceOnly ? "evidence-only" : "attested";
    evid.chained = false;
    evid.admissibility = admissibilityOf(p);
    evid.sourceRef =
        coordinationPlan.evidenceOnly ? "coordinationPlan.evidenceOnly" : aref;
    g.evidenceAcceptances.push_back(evid);

    Reference obs;
    obs.id = projectionNodeId(ProjectionNodeKind::Reference,
                              {p.input, "observerSet"});
    obs.ref = labels.observerSet(p.observerSet);
    obs.role = "observerSet";
    // S0.1: carry the raw observer-set name verbatim as a lossless
    // authorization operand, INDEPENDENT of the structural `ref` label. The
    // reviewed quorum primitive authorizes against this exact value; the
    // ordinal `ref` only identifies. Never substitute one for the other.
    obs.bindingValue = p.observerSet;
    obs.sourceRef = aref + ".observerSet";
    g.references.push_back(obs);

    QuorumPolicy pol;
    pol.id = projectionNodeId(ProjectionNodeKind::QuorumPolicy, {p.input});
    pol.threshold = p.quorum;
    pol.canonicalization = p.canonicalization;
    pol.timeout = p.timeout;
    pol.fallback = p.fallback;
    pol.sourceRef = aref;
    g.quorumPolicies.push_back(pol);
    policyIdByInput[p.input] = pol.id;

    g.edges.push_back({pol.id, "inputRef", evid.id, aref});
    g.edges.push_back(
        {pol.id, "observerSetRef", obs.id, aref + ".observerSet"});
  }

  // ---- §2.2 PrimitiveObligation — the finalized acceptance primitive ------
  if (!coordinationPlan.attestations.empty()) {
    PrimitiveObligation prim;
    // `.Single` ranges over EXACTLY ONE policy (§3: policyRef = 1); any
    // per-policy (temporal) or multi-policy acceptance is `.PerPolicy`
    // (policyRef = 1..n). So a single-shot single-attestation coordination is
    // Single; everything else is PerPolicy.
    const bool perPolicy = temporal || coordinationPlan.attestations.size() > 1;
    prim.finalizedKind =
        perPolicy ? "QuorumAcceptance.PerPolicy" : "QuorumAcceptance.Single";
    prim.id =
        projectionNodeId(ProjectionNodeKind::PrimitiveObligation,
                         {prim.finalizedKind, coordinationPlan.procedure});
    prim.sourceRef = perPolicy ? "coordinationPlan.attestations"
                               : "coordinationPlan.attestations[0]";
    for (const AttestationPolicy &p : coordinationPlan.attestations)
      prim.typedOperands.push_back(policyIdByInput[p.input]);
    g.primitiveObligations.push_back(prim);
    for (size_t i = 0; i < coordinationPlan.attestations.size(); ++i)
      g.edges.push_back(
          {prim.id, "policyRef",
           policyIdByInput[coordinationPlan.attestations[i].input],
           "coordinationPlan.attestations[" + std::to_string(i) + "]"});
  }

  // ---- §2.2 GuardObligation for evidence-only acceptance ------------------
  // The evidence-only acceptance is an attested (quorum) guard per attestation;
  // effectful groups carry their guard on the group below.
  if (coordinationPlan.evidenceOnly)
    for (size_t i = 0; i < coordinationPlan.attestations.size(); ++i) {
      const AttestationPolicy &p = coordinationPlan.attestations[i];
      const std::string aref =
          "coordinationPlan.attestations[" + std::to_string(i) + "]";
      GuardObligation guard;
      guard.id =
          projectionNodeId(ProjectionNodeKind::GuardObligation, {"a", p.input});
      guard.guardKind = "attested";
      guard.conditionKind = "quorum";
      guard.applicationMode = "atomic-refuse";
      guard.sourceRef = aref;
      g.guardObligations.push_back(guard);
      g.edges.push_back(
          {guard.id, "policyRef", policyIdByInput[p.input], aref});
    }

  // ---- §2.4 TypedOperand pool (deduped by (operandKind, value)) -----------
  std::map<std::pair<std::string, std::string>, std::string> operandId;
  auto operandRef = [&](const std::string &kind, const std::string &value,
                        const std::string &sourceRef) -> std::string {
    auto key = std::make_pair(kind, value);
    if (auto it = operandId.find(key); it != operandId.end())
      return it->second;
    TypedOperand op;
    op.id = projectionNodeId(ProjectionNodeKind::TypedOperand, {kind, value});
    op.operandKind = kind;
    op.value = value;
    op.sourceRef = sourceRef;
    g.typedOperands.push_back(op);
    operandId[key] = op.id;
    return op.id;
  };

  // ---- §2.3 LedgerPosting per effect + operand refs -----------------------
  std::unordered_map<size_t, std::string> postingIdByEffectIndex;
  for (size_t ei = 0; ei < coordinationPlan.effects.size(); ++ei) {
    const PlanEffect &e = coordinationPlan.effects[ei];
    const std::string eref =
        "coordinationPlan.effects[" + std::to_string(ei) + "]";
    LedgerPosting post;
    post.id = projectionNodeId(ProjectionNodeKind::LedgerPosting,
                               {std::to_string(e.index)});
    post.effectIndex = static_cast<int>(e.index);
    post.direction = e.kind;
    post.name = e.name;
    post.ledger = e.ledger;
    post.party = e.party;
    post.amount = e.amount;
    post.currency = e.currency;
    post.memo = e.memo;
    post.sourceRef = eref;
    g.ledgerPostings.push_back(post);
    postingIdByEffectIndex[e.index] = post.id;

    if (!e.ledger.empty())
      g.edges.push_back(
          {post.id, "ledgerRef",
           operandRef("ledger", labels.ledger(e.ledger), eref + ".ledger"),
           eref + ".ledger"});
    if (!e.party.empty())
      g.edges.push_back(
          {post.id, "partyRef",
           operandRef("party", labels.operand(e.party), eref + ".party"),
           eref + ".party"});
    if (!e.amount.empty())
      g.edges.push_back(
          {post.id, "amountRef",
           operandRef("amount", labels.operand(e.amount), eref + ".amount"),
           eref + ".amount"});
    if (!e.currency.empty())
      g.edges.push_back({post.id, "currencyRef",
                         operandRef("currency", labels.operand(e.currency),
                                    eref + ".currency"),
                         eref + ".currency"});
    if (!e.memo.empty())
      g.edges.push_back({post.id, "memoRef",
                         operandRef("memo", e.memo, eref + ".memo"),
                         eref + ".memo"});
  }

  // ---- §2.4 TypedParam — one per declared input (closed target-neutral type)
  // Identity is the canonical input label (`input:<n>`), never the source name.
  std::unordered_map<std::string, std::string>
      paramIdByInput; // name -> node id
  for (size_t i = 0; i < coordinationPlan.inputs.size(); ++i) {
    const PlanInput &in = coordinationPlan.inputs[i];
    TypedParam param;
    const std::string canon = labels.value(in.name);
    param.id = projectionNodeId(ProjectionNodeKind::TypedParam, {canon});
    param.name = canon;
    param.bindingValue = in.name;
    param.ordinal = static_cast<int>(i);
    param.type = in.type;
    param.sourceRef = "coordinationPlan.inputs[" + std::to_string(i) + "]";
    // §2.4 closed instance-key role (): mark this param iff it binds the
    // execution instance key (coordinationPlan.workflowKey). The role is
    // resolved here, once, above the waist — never re-inferred downstream. The
    // key is a coordination-level identity that MAY have no corresponding value
    // input (e.g. the evidence-only rail carries an instanceKey but zero typed
    // params); in that case no param is marked, which is a valid graph.
    param.isInstanceKey = !coordinationPlan.workflowKey.empty() &&
                          in.name == coordinationPlan.workflowKey;
    g.typedParams.push_back(param);
    paramIdByInput[in.name] = param.id;
  }

  // ---- §2.4 ComputeNode — one per declared compute; operandRefs -> the typed
  // operands / compute nodes its dependencies resolve to (1..n, acyclic §3).
  std::unordered_map<std::string, std::string> computeIdByName;
  for (size_t i = 0; i < coordinationPlan.computes.size(); ++i) {
    const PlanCompute &c = coordinationPlan.computes[i];
    ComputeNode cn;
    cn.id = projectionNodeId(ProjectionNodeKind::ComputeNode,
                             {labels.value(c.name)});
    cn.bindingValue = c.name;
    cn.ordinal = static_cast<int>(i);
    cn.exprKind = c.expr ? exprKindName(c.expr->kind) : "value";
    cn.dtype = c.category;
    cn.expression = c.expr ? compactJson(exprToJson(*c.expr)) : "";
    cn.sourceRef = "coordinationPlan.computes[" + std::to_string(i) + "]";
    g.computeNodes.push_back(cn);
    computeIdByName[c.name] = cn.id;
  }
  for (size_t i = 0; i < coordinationPlan.computes.size(); ++i) {
    const PlanCompute &c = coordinationPlan.computes[i];
    const std::string cref =
        "coordinationPlan.computes[" + std::to_string(i) + "]";
    for (const std::string &dep : c.deps) {
      // A dependency resolves to a sibling ComputeNode, else to a TypedOperand
      // carrying the canonical value reference.
      if (auto it = computeIdByName.find(dep); it != computeIdByName.end())
        g.edges.push_back(
            {computeIdByName[c.name], "operandRefs", it->second, cref});
      else
        g.edges.push_back(
            {computeIdByName[c.name], "operandRefs",
             operandRef("value", "ref:" + labels.value(dep), cref), cref});
    }
  }

  // ---- §2.3 BalancedEffectGroup + guard + groupRef/effectRefs -------------
  std::vector<std::string> groupIdByIndex(coordinationPlan.effectGroups.size());
  for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi) {
    const PlanEffectGroup &grp = coordinationPlan.effectGroups[gi];
    const std::string gref =
        "coordinationPlan.effectGroups[" + std::to_string(gi) + "]";
    BalancedEffectGroup bg;
    bg.id = projectionNodeId(ProjectionNodeKind::BalancedEffectGroup,
                             {std::to_string(grp.firstIndex)});
    bg.firstIndex = static_cast<int>(grp.firstIndex);
    bg.pairing = "identical-guard";
    bg.mustBalance = grp.mustBalance;
    bg.gateMode = grp.gateMode;
    bg.gatePolicy = grp.gatePolicy;
    if (grp.gateMode == PlanGateMode::None && !grp.effectIndices.empty())
      if (const ExprNode *guard =
              coordinationPlan.effects[grp.effectIndices.front()].guard.get())
        bg.comparisonGuardExpression = compactJson(exprToJson(*guard));
    // A balanced group in a single-transaction (non-temporal) coordination
    // requires a rollback CompensationObligation (§2.3 B4); a temporal
    // per-policy coordination uses the commit ledger instead. Recorded on the
    // node so the verifier enforces exact per-group coverage graph-internally.
    bg.rollbackRequired = grp.mustBalance && !temporal;
    bg.sourceRef = gref;
    g.balancedEffectGroups.push_back(bg);
    groupIdByIndex[gi] = bg.id;

    // The group's guard: an atomic-refuse attestation gate projects an
    // `attested`/`quorum` GuardObligation with a `policyRef`; a non-attestation
    // predicate projects a `comparison` guard with no policyRef (§3, F12).
    // Temporal-suppress groups carry no group-level guard.
    if ((grp.gateMode == PlanGateMode::AtomicRefuse ||
         grp.gateMode == PlanGateMode::TemporalSuppress) &&
        !grp.gatePolicy.empty()) {
      GuardObligation guard;
      guard.id = projectionNodeId(ProjectionNodeKind::GuardObligation,
                                  {"g", std::to_string(grp.firstIndex)});
      guard.guardKind = "attested";
      guard.conditionKind = "quorum";
      guard.applicationMode = grp.gateMode == PlanGateMode::TemporalSuppress
                                  ? "temporal-suppress"
                                  : "atomic-refuse";
      guard.sourceRef = gref;
      g.guardObligations.push_back(guard);
      g.edges.push_back(
          {guard.id, "policyRef", policyIdByInput[grp.gatePolicy], gref});
      g.edges.push_back({bg.id, "guardRef", guard.id, gref});
    } else if (grp.gateMode == PlanGateMode::None && !grp.guardKey.empty()) {
      GuardObligation guard;
      guard.id = projectionNodeId(ProjectionNodeKind::GuardObligation,
                                  {"g", std::to_string(grp.firstIndex)});
      guard.guardKind = "comparison";
      guard.conditionKind = "comparison";
      guard.applicationMode = "comparison";
      guard.sourceRef = gref;
      g.guardObligations.push_back(guard);
      g.edges.push_back({bg.id, "guardRef", guard.id, gref});
    }

    // groupRef (posting -> group) + inverse-exact effectRefs (group ->
    // posting).
    for (size_t k = 0; k < grp.effectIndices.size(); ++k) {
      size_t ei = grp.effectIndices[k];
      auto it = postingIdByEffectIndex.find(ei);
      if (it == postingIdByEffectIndex.end())
        continue;
      g.edges.push_back({it->second, "groupRef", bg.id, gref});
      g.edges.push_back({bg.id, "effectRefs", it->second,
                         gref + ".effectIndices[" + std::to_string(k) + "]"});
    }
  }

  // ---- §2.3 BalanceAssertion — coordination-scoped over mustBalance groups -
  std::vector<std::string> mustBalanceGroups;
  for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi)
    if (coordinationPlan.effectGroups[gi].mustBalance)
      mustBalanceGroups.push_back(groupIdByIndex[gi]);
  if (!mustBalanceGroups.empty()) {
    BalanceAssertion bal;
    bal.id = projectionNodeId(ProjectionNodeKind::BalanceAssertion,
                              {coordinationPlan.procedure});
    bal.scope = "coordination";
    bal.sourceRef = "coordinationPlan.balanced";
    g.balanceAssertions.push_back(bal);
    for (const std::string &gid : mustBalanceGroups)
      g.edges.push_back(
          {bal.id, "assertsRefs", gid, "coordinationPlan.balanced"});
  }

  // ---- §2.3 CompensationObligation — rollback per balanced group (atomic) --
  // A balanced group in a single-transaction (non-temporal) context carries a
  // rollback obligation discharged by the target's atomicity capability (§6.1);
  // temporal per-policy coordinations use the per-(key,group) commit ledger.
  if (!temporal)
    for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi) {
      if (!coordinationPlan.effectGroups[gi].mustBalance)
        continue;
      const std::string gref =
          "coordinationPlan.effectGroups[" + std::to_string(gi) + "]";
      CompensationObligation comp;
      comp.id = projectionNodeId(
          ProjectionNodeKind::CompensationObligation,
          {std::to_string(coordinationPlan.effectGroups[gi].firstIndex)});
      comp.mode = "rollback";
      comp.sourceRef = gref;
      g.compensationObligations.push_back(comp);
      g.edges.push_back({comp.id, "compensates", groupIdByIndex[gi], gref});
    }

  // ---- §2.1 CommitState — one per gated policy scope ----------------------
  // Effectful: per gated effect group (keyed by its gatePolicy, deduped per
  // policy). Evidence-only: per attestation. Each binds execRef -> identity and
  // the typed scopeRef -> its QuorumPolicy (never by commitScope name).
  std::vector<std::string> commitIds;
  std::unordered_set<std::string> committedPolicies;
  auto addCommit = [&](const std::string &policyKey,
                       const std::string &sourceRef) {
    if (!committedPolicies.insert(policyKey).second)
      return; // one CommitState per policy scope
    CommitState commit;
    commit.id = projectionNodeId(ProjectionNodeKind::CommitState, {policyKey});
    commit.idempotencyKey = coordinationPlan.workflowKey;
    commit.commitScope = policyIdByInput.count(policyKey)
                             ? policyIdByInput[policyKey]
                             : policyKey;
    commit.sourceRef = sourceRef;
    g.commitStates.push_back(commit);
    commitIds.push_back(commit.id);
    g.edges.push_back(
        {commit.id, "execRef", exec.id, "coordinationPlan.workflowKey"});
    if (policyIdByInput.count(policyKey))
      g.edges.push_back(
          {commit.id, "scopeRef", policyIdByInput[policyKey], sourceRef});
  };
  if (coordinationPlan.evidenceOnly) {
    for (const AttestationPolicy &p : coordinationPlan.attestations)
      addCommit(p.input, "coordinationPlan.workflowKey");
  } else {
    for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi) {
      const PlanEffectGroup &grp = coordinationPlan.effectGroups[gi];
      if (grp.gatePolicy.empty())
        continue;
      addCommit(grp.gatePolicy,
                "coordinationPlan.effectGroups[" + std::to_string(gi) + "]");
    }
  }

  // ---- §2.1 terminal reachability (fail closed) ---------------------------
  // A declared terminal (success/aborted/contested) must name a state the
  // lifecycle can actually reach — the `to` of at least one transition.
  // Otherwise `noteState(coordinationPlan.terminal.*)` below would mint a
  // standalone terminal LifecycleState that no transition ever enters (a
  // dangling, unreachable terminal), and the graph would verify and emit.
  // Refuse here, ONCE, in the projector with a stable diagnostic identity —
  // before either backend emits anything — rather than let each legalizer
  // re-derive the check independently ( part 3).
  {
    std::unordered_set<std::string> reachable;
    for (const LifecycleTransitionPolicy &t :
         coordinationPlan.lifecycleTransitions)
      reachable.insert(t.to);
    auto requireReachable = [&](const char *kind,
                                const std::string &name) -> llvm::Error {
      if (!name.empty() && !reachable.count(name))
        return llvm::make_error<llvm::StringError>(
            std::string(
                "BackendProjection:LifecycleState:unreachable-terminal:") +
                kind + ":" + name,
            llvm::inconvertibleErrorCode());
      return llvm::Error::success();
    };
    if (llvm::Error e =
            requireReachable("success", coordinationPlan.terminal.success))
      return std::move(e);
    if (llvm::Error e =
            requireReachable("aborted", coordinationPlan.terminal.aborted))
      return std::move(e);
    if (llvm::Error e =
            requireReachable("contested", coordinationPlan.terminal.contested))
      return std::move(e);
  }

  // ---- §2.1 posting terminal-outcome precondition ( G1-S0) ------------
  // The backends collapse the full lifecycle to a 2-state surface
  // (None -> Accepted/Reconciled) that commits every effect group and then
  // moves unconditionally to the single success terminal — it carries no
  // representation of an aborted/contested terminal, nor of effects committed
  // off the success path. This check establishes ONE precondition for that
  // collapse: every effect-committing (posting) transition preserves the
  // terminal OUTCOME — the set of terminals reachable from its target
  // (terminals treated as sinks) is EXACTLY {success}. A reachable non-success
  // terminal, or NO reachable terminal at all (a dead end / terminal-free
  // path), is a terminal-outcome mismatch the 2-state surface cannot express:
  // the backend would commit the ledger and reconcile on a path that either can
  // still abort or never reaches success. The legalizers read the lifecycle
  // only through projectedSuccessTerminal, so nothing downstream would catch
  // it; enforce it once here, before either backend emits.
  //
  // Scope: this is terminal-OUTCOME preservation, NOT a full quotient-soundness
  // proof — it does not establish liveness (a reachable terminal-free cycle
  // alongside the success path still satisfies {success}). That, and the
  // consumer-side migration (legalizers consuming projected lifecycle roles +
  // deleting the backend-local status-enum authority), are later G1 slices.
  if (!coordinationPlan.terminal.success.empty()) {
    std::unordered_map<std::string, std::vector<std::string>> adjacency;
    for (const LifecycleTransitionPolicy &t :
         coordinationPlan.lifecycleTransitions)
      adjacency[t.from].push_back(t.to);
    std::unordered_set<std::string> terminalNames;
    for (const std::string &n :
         {coordinationPlan.terminal.success, coordinationPlan.terminal.aborted,
          coordinationPlan.terminal.contested})
      if (!n.empty())
        terminalNames.insert(n);
    // The terminals reachable from `start`, treating each terminal as a sink.
    auto reachableTerminals = [&](const std::string &start) {
      std::set<std::string> terms;
      std::unordered_set<std::string> seen;
      std::vector<std::string> stack{start};
      while (!stack.empty()) {
        std::string s = stack.back();
        stack.pop_back();
        if (!seen.insert(s).second)
          continue;
        if (terminalNames.count(s)) {
          terms.insert(s); // a terminal is a sink — do not expand past it
          continue;
        }
        for (const std::string &n : adjacency[s])
          stack.push_back(n);
      }
      return terms;
    };
    for (const LifecycleTransitionPolicy &t :
         coordinationPlan.lifecycleTransitions) {
      if (std::find(t.effects.begin(), t.effects.end(), "post") ==
          t.effects.end())
        continue;
      // Require reachableTerminals(t.to) == {success} EXACTLY. Two failures:
      const std::set<std::string> terms = reachableTerminals(t.to);
      // (1) any reachable terminal other than success;
      for (const std::string &term : terms)
        if (term != coordinationPlan.terminal.success)
          return llvm::make_error<llvm::StringError>(
              "BackendProjection:Transition:"
              "posting-reaches-non-success-terminal:" +
                  t.name + ":" + term,
              llvm::inconvertibleErrorCode());
      // (2) success not reachable at all (empty set / terminal-free path) — the
      // backend would still reconcile a lifecycle that never reaches success.
      if (!terms.count(coordinationPlan.terminal.success))
        return llvm::make_error<llvm::StringError>(
            "BackendProjection:Transition:"
            "posting-reaches-no-success-terminal:" +
                t.name,
            llvm::inconvertibleErrorCode());
    }
  }

  // ---- §2.1 LifecycleState — terminals + transition endpoints -------------
  std::vector<std::string> stateOrder;
  std::unordered_map<std::string, std::string> stateSourceRef; // name -> ref
  auto noteState = [&](const std::string &name, const std::string &ref) {
    if (name.empty())
      return;
    if (stateSourceRef.find(name) == stateSourceRef.end()) {
      stateSourceRef[name] = ref;
      stateOrder.push_back(name);
    }
  };
  noteState(coordinationPlan.terminal.success,
            "coordinationPlan.terminal.success");
  noteState(coordinationPlan.terminal.aborted,
            "coordinationPlan.terminal.aborted");
  noteState(coordinationPlan.terminal.contested,
            "coordinationPlan.terminal.contested");
  for (size_t i = 0; i < coordinationPlan.lifecycleTransitions.size(); ++i) {
    const LifecycleTransitionPolicy &t =
        coordinationPlan.lifecycleTransitions[i];
    noteState(t.from, "coordinationPlan.lifecycleTransitions[" +
                          std::to_string(i) + "].from");
    noteState(t.to, "coordinationPlan.lifecycleTransitions[" +
                        std::to_string(i) + "].to");
  }

  std::unordered_map<std::string, std::string> stateNodeId; // name -> node id
  for (const std::string &name : stateOrder) {
    LifecycleState state;
    state.id = projectionNodeId(ProjectionNodeKind::LifecycleState, {name});
    state.name = name;
    state.terminalKind = terminalKindOf(coordinationPlan, name);
    state.terminal = state.terminalKind != TerminalKind::None;
    state.sourceRef = stateSourceRef[name];
    stateNodeId[name] = state.id;
    g.lifecycleStates.push_back(state);

    // requiredCommitRefs: a terminal state requires EXACTLY the CommitStates of
    // the coordination's required policy scopes (§3, F14/F15).
    if (state.terminal)
      for (const std::string &cid : commitIds)
        g.edges.push_back(
            {state.id, "requiredCommitRefs", cid, state.sourceRef});
  }

  // ---- §2.1 Transition — endpoints + effectGroupRefs ----------------------
  for (size_t i = 0; i < coordinationPlan.lifecycleTransitions.size(); ++i) {
    const LifecycleTransitionPolicy &t =
        coordinationPlan.lifecycleTransitions[i];
    Transition trans;
    // A transition's stable identity is its (name, from, to) triple — the name
    // alone is NOT unique (e.g. two `CLOSE` transitions into a terminal state
    // from different sources), which would otherwise collide (§2.5, F10).
    trans.id = projectionNodeId(ProjectionNodeKind::Transition,
                                {t.name, t.from, t.to});
    trans.name = t.name;
    trans.sourceRef =
        "coordinationPlan.lifecycleTransitions[" + std::to_string(i) + "]";
    g.transitions.push_back(trans);
    if (auto it = stateNodeId.find(t.from); it != stateNodeId.end())
      g.edges.push_back({trans.id, "fromRef", it->second, trans.sourceRef});
    if (auto it = stateNodeId.find(t.to); it != stateNodeId.end())
      g.edges.push_back({trans.id, "toRef", it->second, trans.sourceRef});
    // A posting transition references every effect group it commits (§3, 0..n).
    const bool posts = std::find(t.effects.begin(), t.effects.end(), "post") !=
                       t.effects.end();
    if (posts)
      for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi)
        g.edges.push_back(
            {trans.id, "effectGroupRefs", groupIdByIndex[gi],
             "coordinationPlan.effectGroups[" + std::to_string(gi) + "]"});
  }

  // ---- §2.1 ProjectedLifecycleRole — (mode, role) lowering obligations -----
  // The status-authority quotient a target spells is a single lifecycle fact:
  // whether the coordination has reached its success terminal. The role and
  // mode are decided HERE, backend-blind (mode is the same
  // evidenceOnly/temporal axis the target legalizers already dispatch on), so
  // NO legalizer selects them; a target CONSUMES (mode, role) through its idiom
  // table. Every role anchors
  // (`stateRef`, 1) to the projected success terminal — the one lifecycle state
  // the quotient encodes (evidence-only projects no distinct pre-success
  // state). Required set per mode: Evidence/Temporal -> {Initial, Success};
  // Effectful adds the intermediate AcceptedOrAttested accept/attest
  // checkpoint.
  if (auto successIt = stateNodeId.find(coordinationPlan.terminal.success);
      successIt != stateNodeId.end()) {
    const ExecutionMode mode = coordinationPlan.evidenceOnly
                                   ? ExecutionMode::Evidence
                               : temporal ? ExecutionMode::Temporal
                                          : ExecutionMode::Effectful;
    auto addRole = [&](LifecycleRole role) {
      ProjectedLifecycleRole r;
      r.id = projectionNodeId(ProjectionNodeKind::ProjectedLifecycleRole,
                              {std::to_string(static_cast<int>(mode)),
                               std::to_string(static_cast<int>(role))});
      r.mode = mode;
      r.role = role;
      r.state = coordinationPlan.terminal.success;
      r.sourceRef = "coordinationPlan.terminal.success";
      g.projectedLifecycleRoles.push_back(r);
      g.edges.push_back({r.id, "stateRef", successIt->second, r.sourceRef});
    };
    addRole(LifecycleRole::Initial);
    if (mode == ExecutionMode::Effectful)
      addRole(LifecycleRole::AcceptedOrAttested);
    addRole(LifecycleRole::Success);
  }

  // Coordination-relative completeness: every effect projects a posting,
  // every attestation its policy/evidence/observer, and every group/input/
  // compute its node. A count mismatch means the projector dropped a required
  // node — fail closed with a stable diagnostic before the graph escapes,
  // rather than emit a silently-incomplete projection.
  if (std::string diag = completenessAgainstCoordination(coordinationPlan, g);
      !diag.empty())
    return llvm::make_error<llvm::StringError>(diag,
                                               llvm::inconvertibleErrorCode());

  // Establish + normalize the §2-§3 invariants. A non-empty diagnostic is an
  // explicit failure: convert it to an `llvm::Error` carrying the stable
  // diagnostic identity so it can NEVER be discarded or escape as a successful
  // graph. On success the verified, deterministically-ordered graph is
  // returned.
  if (std::string diag = verifyAndOrder(g); !diag.empty())
    return llvm::make_error<llvm::StringError>(diag,
                                               llvm::inconvertibleErrorCode());
  return g;
}
#endif

llvm::Expected<AttestationProjection>
consumeAttestationProjection(const BackendProjectionGraph &graph) {
  auto error = [](const char *diag) -> llvm::Expected<AttestationProjection> {
    return llvm::make_error<llvm::StringError>(diag,
                                               llvm::inconvertibleErrorCode());
  };
  AttestationProjection out;
  if (graph.projectedLifecycleRoles.empty())
    return error("diag:AttestationProjection:execution-mode-missing");
  out.executionMode = graph.projectedLifecycleRoles.front().mode;
  for (const ProjectedLifecycleRole &role : graph.projectedLifecycleRoles)
    if (role.mode != out.executionMode)
      return error("diag:AttestationProjection:execution-mode-ambiguous");

  if (graph.primitiveObligations.empty()) {
    if (!graph.quorumPolicies.empty() || !graph.evidenceAcceptances.empty())
      return error("diag:AttestationProjection:primitive-missing");
    return out;
  }
  if (graph.primitiveObligations.size() != 1)
    return error("diag:AttestationProjection:primitive-ambiguous");
  const PrimitiveObligation &primitive = graph.primitiveObligations.front();
  out.finalizedKind = primitive.finalizedKind;

  auto edgeTo = [&](const std::string &from,
                    const char *name) -> llvm::Expected<std::string> {
    const ProjectionEdge *found = nullptr;
    for (const ProjectionEdge &edge : graph.edges) {
      if (edge.from != from || edge.name != name)
        continue;
      if (found)
        return llvm::make_error<llvm::StringError>(
            "diag:AttestationProjection:edge-ambiguous",
            llvm::inconvertibleErrorCode());
      found = &edge;
    }
    if (!found)
      return llvm::make_error<llvm::StringError>(
          "diag:AttestationProjection:edge-missing",
          llvm::inconvertibleErrorCode());
    return found->to;
  };

  for (const std::string &policyId : primitive.typedOperands) {
    const QuorumPolicy *policy = nullptr;
    for (const QuorumPolicy &candidate : graph.quorumPolicies)
      if (candidate.id == policyId)
        policy = &candidate;
    if (!policy)
      return error("diag:AttestationProjection:policy-missing");

    auto inputId = edgeTo(policy->id, "inputRef");
    if (!inputId)
      return inputId.takeError();
    auto observerId = edgeTo(policy->id, "observerSetRef");
    if (!observerId)
      return observerId.takeError();

    const EvidenceAcceptance *evidence = nullptr;
    for (const EvidenceAcceptance &candidate : graph.evidenceAcceptances)
      if (candidate.id == *inputId)
        evidence = &candidate;
    const Reference *observer = nullptr;
    for (const Reference &candidate : graph.references)
      if (candidate.id == *observerId)
        observer = &candidate;
    if (!evidence || !observer || observer->role != "observerSet")
      return error("diag:AttestationProjection:binding-missing");

    out.policies.push_back({policy->id, evidence->bindingValue,
                            observer->bindingValue, policy->threshold,
                            policy->canonicalization, policy->timeout,
                            policy->fallback, evidence->style,
                            evidence->chained, evidence->admissibility});
  }
  return out;
}

llvm::Expected<GroupGuardProjection>
consumeGroupGuardProjection(const BackendProjectionGraph &graph,
                            const std::string &groupSourceRef) {
  auto error = [](const char *diag) -> llvm::Expected<GroupGuardProjection> {
    return llvm::make_error<llvm::StringError>(diag,
                                               llvm::inconvertibleErrorCode());
  };
  const BalancedEffectGroup *group = nullptr;
  for (const BalancedEffectGroup &candidate : graph.balancedEffectGroups)
    if (candidate.sourceRef == groupSourceRef) {
      if (group)
        return error("diag:GroupGuardProjection:group-ambiguous");
      group = &candidate;
    }
  if (!group)
    return error("diag:GroupGuardProjection:group-missing");

  auto reconstructComparison = [&]() -> llvm::Expected<ExprPtr> {
    auto json = llvm::json::parse(group->comparisonGuardExpression);
    if (!json)
      return llvm::make_error<llvm::StringError>(
          "diag:GroupGuardProjection:comparison-expression-invalid",
          llvm::inconvertibleErrorCode());
    try {
      ExprPtr expression = exprFromJson(*json);
      std::map<std::string, ValueCategory> env;
      for (const TypedParam &param : graph.typedParams)
        env[param.bindingValue] = classifyValueType(param.type);
      for (const ComputeNode &compute : graph.computeNodes)
        env[compute.bindingValue] = categoryFromName(compute.dtype);
      typeGuard(*expression, env);
      if (compactJson(exprToJson(*expression)) !=
          group->comparisonGuardExpression)
        return llvm::make_error<llvm::StringError>(
            "diag:GroupGuardProjection:comparison-expression-invalid",
            llvm::inconvertibleErrorCode());
      return std::move(expression);
    } catch (const ExprError &) {
      return llvm::make_error<llvm::StringError>(
          "diag:GroupGuardProjection:comparison-expression-invalid",
          llvm::inconvertibleErrorCode());
    }
  };

  const ProjectionEdge *guardEdge = nullptr;
  for (const ProjectionEdge &edge : graph.edges)
    if (edge.from == group->id && edge.name == "guardRef") {
      if (guardEdge)
        return error("diag:GroupGuardProjection:guard-ambiguous");
      guardEdge = &edge;
    }
  if (!guardEdge) {
    if (!group->comparisonGuardExpression.empty())
      return error("diag:GroupGuardProjection:comparison-expression-spurious");
    return GroupGuardProjection{};
  }

  const GuardObligation *guard = nullptr;
  for (const GuardObligation &candidate : graph.guardObligations)
    if (candidate.id == guardEdge->to)
      guard = &candidate;
  if (!guard)
    return error("diag:GroupGuardProjection:guard-missing");

  GroupGuardProjection out;
  out.present = true;
  out.guardKind = guard->guardKind;
  out.conditionKind = guard->conditionKind;
  out.applicationMode = guard->applicationMode;
  if (guard->guardKind == "comparison") {
    if (group->comparisonGuardExpression.empty())
      return error("diag:GroupGuardProjection:comparison-expression-missing");
    auto expression = reconstructComparison();
    if (!expression)
      return expression.takeError();
    out.comparisonGuard = std::move(*expression);
    return std::move(out);
  }
  if (!group->comparisonGuardExpression.empty())
    return error("diag:GroupGuardProjection:comparison-expression-spurious");
  if (guard->guardKind != "attested")
    return std::move(out);

  const ProjectionEdge *policyEdge = nullptr;
  for (const ProjectionEdge &edge : graph.edges)
    if (edge.from == guard->id && edge.name == "policyRef") {
      if (policyEdge)
        return error("diag:GroupGuardProjection:policy-ambiguous");
      policyEdge = &edge;
    }
  if (!policyEdge)
    return error("diag:GroupGuardProjection:policy-missing");

  auto attestation = consumeAttestationProjection(graph);
  if (!attestation)
    return attestation.takeError();
  for (const AttestationBinding &binding : attestation->policies)
    if (binding.policyId == policyEdge->to) {
      out.policyInputBinding = binding.inputBinding;
      return std::move(out);
    }
  return error("diag:GroupGuardProjection:policy-binding-missing");
}

llvm::Expected<TypedValueProjection>
consumeTypedValueProjection(const BackendProjectionGraph &graph) {
  auto error = [](const char *diag) -> llvm::Expected<TypedValueProjection> {
    return llvm::make_error<llvm::StringError>(diag,
                                               llvm::inconvertibleErrorCode());
  };
  TypedValueProjection out;

  std::vector<const TypedParam *> params;
  for (const TypedParam &param : graph.typedParams)
    params.push_back(&param);
  std::stable_sort(
      params.begin(), params.end(),
      [](const auto *a, const auto *b) { return a->ordinal < b->ordinal; });
  for (const TypedParam *param : params) {
    out.params.push_back({param->bindingValue, param->type,
                          static_cast<size_t>(param->ordinal)});
    // Resolve the instance-key association ONCE, above the provider boundary,
    // into a dedicated exact-0/1 accessor (). Exactly one param may carry
    // the graph role (the verifier enforces the iff + unique bindings); a
    // second is a malformed graph and fails closed here.
    if (param->isInstanceKey) {
      if (out.instanceKeyParam)
        return error("diag:TypedValueProjection:instance-key-ambiguous");
      out.instanceKeyParam =
          TypedParamProjection{param->bindingValue, param->type,
                               static_cast<size_t>(param->ordinal)};
    }
  }

  std::vector<const ComputeNode *> computes;
  for (const ComputeNode &compute : graph.computeNodes)
    computes.push_back(&compute);
  std::stable_sort(
      computes.begin(), computes.end(),
      [](const auto *a, const auto *b) { return a->ordinal < b->ordinal; });
  for (const ComputeNode *compute : computes) {
    auto json = llvm::json::parse(compute->expression);
    if (!json)
      return error("diag:TypedValueProjection:compute-expression-invalid");
    try {
      out.computes.push_back({compute->bindingValue, compute->dtype,
                              exprFromJson(*json),
                              static_cast<size_t>(compute->ordinal)});
    } catch (const ExprError &) {
      return error("diag:TypedValueProjection:compute-expression-invalid");
    }
  }

  auto operandValue = [&](const std::string &postingId, const char *edgeName,
                          bool required) -> llvm::Expected<std::string> {
    const ProjectionEdge *found = nullptr;
    for (const ProjectionEdge &edge : graph.edges) {
      if (edge.from != postingId || edge.name != edgeName)
        continue;
      if (found)
        return llvm::make_error<llvm::StringError>(
            "diag:TypedValueProjection:posting-edge-ambiguous",
            llvm::inconvertibleErrorCode());
      found = &edge;
    }
    if (!found) {
      if (!required)
        return std::string();
      return llvm::make_error<llvm::StringError>(
          "diag:TypedValueProjection:posting-edge-missing",
          llvm::inconvertibleErrorCode());
    }
    for (const TypedOperand &operand : graph.typedOperands)
      if (operand.id == found->to)
        return operand.value;
    return llvm::make_error<llvm::StringError>(
        "diag:TypedValueProjection:posting-operand-missing",
        llvm::inconvertibleErrorCode());
  };

  std::vector<const LedgerPosting *> postings;
  for (const LedgerPosting &posting : graph.ledgerPostings)
    postings.push_back(&posting);
  std::stable_sort(postings.begin(), postings.end(),
                   [](const auto *a, const auto *b) {
                     return a->effectIndex < b->effectIndex;
                   });
  for (const LedgerPosting *posting : postings) {
    PostingValueProjection value;
    value.effectIndex = posting->effectIndex;
    auto memo = operandValue(posting->id, "memoRef", false);
    if (!memo)
      return memo.takeError();
    value.memo = *memo;
    out.postings.push_back(std::move(value));
  }
  return out;
}

llvm::Expected<FinalizedProjectionSequence>
consumeFinalizedProjectionSequence(const BackendProjectionGraph &graph) {
  auto error =
      [](const char *diag) -> llvm::Expected<FinalizedProjectionSequence> {
    return llvm::make_error<llvm::StringError>(diag,
                                               llvm::inconvertibleErrorCode());
  };

  FinalizedProjectionSequence out;
  out.graph = &graph;
  if (graph.executionIdentities.size() != 1)
    return error("diag:FinalizedProjectionSequence:execution-identity");
  out.executionIdentity = graph.executionIdentities.front();
  out.lifecycleRoles = graph.projectedLifecycleRoles;
  bool foundInitial = false;
  bool foundSuccess = false;
  for (const ProjectedLifecycleRole &role : out.lifecycleRoles) {
    if (role.role == LifecycleRole::Initial) {
      if (foundInitial)
        return error("diag:FinalizedProjectionSequence:initial-role");
      out.initialLifecycleRole = role;
      foundInitial = true;
    } else if (role.role == LifecycleRole::Success) {
      if (foundSuccess)
        return error("diag:FinalizedProjectionSequence:success-role");
      out.successLifecycleRole = role;
      foundSuccess = true;
    }
  }
  if (!foundInitial || !foundSuccess)
    return error("diag:FinalizedProjectionSequence:lifecycle-roles");
  std::vector<ExecutionClaimInput> claimInputs =
      out.executionIdentity.claimInputs;
  std::stable_sort(
      claimInputs.begin(), claimInputs.end(),
      [](const auto &lhs, const auto &rhs) { return lhs.name < rhs.name; });
  for (size_t ordinal = 0; ordinal < claimInputs.size(); ++ordinal)
    out.claimInputs.push_back(
        {claimInputs[ordinal].name, claimInputs[ordinal].type,
         categoryName(classifyValueType(claimInputs[ordinal].type)).str(),
         ordinal});
  auto attestation = consumeAttestationProjection(graph);
  if (!attestation)
    return attestation.takeError();
  out.executionMode = attestation->executionMode;
  out.attestation = std::move(*attestation);

  if (out.attestation.finalizedKind.empty() &&
      out.attestation.policies.empty()) {
    out.attestationKind = FinalizedAttestationKind::None;
  } else if (out.attestation.finalizedKind == "QuorumAcceptance.Single" &&
             out.attestation.policies.size() == 1) {
    out.attestationKind = FinalizedAttestationKind::Single;
  } else if (out.attestation.finalizedKind == "QuorumAcceptance.PerPolicy" &&
             !out.attestation.policies.empty()) {
    out.attestationKind = FinalizedAttestationKind::PerPolicy;
  } else {
    return error("diag:FinalizedProjectionSequence:attestation-shape");
  }

  const bool validRail =
      (out.executionMode == ExecutionMode::Evidence &&
       out.attestationKind == FinalizedAttestationKind::Single) ||
      (out.executionMode == ExecutionMode::Temporal &&
       out.attestationKind == FinalizedAttestationKind::PerPolicy) ||
      (out.executionMode == ExecutionMode::Effectful &&
       out.attestationKind != FinalizedAttestationKind::PerPolicy);
  if (!validRail)
    return error("diag:FinalizedProjectionSequence:execution-rail");
  for (const AttestationBinding &policy : out.attestation.policies)
    if (policy.canonicalization != "exact")
      return error(
          "diag:FinalizedProjectionSequence:canonicalization-unsupported");
  if (out.executionMode == ExecutionMode::Temporal) {
    auto isAlpha = [](char c) {
      return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
    };
    auto isTargetIdentifier = [&](llvm::StringRef value) {
      if (value.empty() || !(isAlpha(value.front()) || value.front() == '_'))
        return false;
      return llvm::all_of(value.drop_front(), [&](char c) {
        return isAlpha(c) || (c >= '0' && c <= '9') || c == '_';
      });
    };
    out.temporalPolicies.reserve(out.attestation.policies.size());
    for (size_t ordinal = 0; ordinal < out.attestation.policies.size();
         ++ordinal) {
      const std::string &identifier =
          out.attestation.policies[ordinal].inputBinding;
      if (!isTargetIdentifier(identifier))
        return error(
            "diag:FinalizedProjectionSequence:temporal-policy-identifier");
      out.temporalPolicies.push_back({identifier, ordinal});
    }
  }

  auto values = consumeTypedValueProjection(graph);
  if (!values)
    return values.takeError();
  out.values = std::move(*values);

  std::vector<const BalancedEffectGroup *> groups;
  for (const BalancedEffectGroup &group : graph.balancedEffectGroups)
    groups.push_back(&group);
  std::stable_sort(groups.begin(), groups.end(),
                   [](const auto *a, const auto *b) {
                     return a->firstIndex < b->firstIndex;
                   });
  for (size_t ordinal = 0; ordinal < groups.size(); ++ordinal) {
    const BalancedEffectGroup *group = groups[ordinal];
    FinalizedEffectGroupProjection finalized;
    finalized.group = group;
    finalized.ordinal = ordinal;
    auto guard = consumeGroupGuardProjection(graph, group->sourceRef);
    if (!guard)
      return guard.takeError();
    finalized.guard = std::move(*guard);
    for (const ProjectionEdge &edge : graph.edges) {
      if (edge.from != group->id || edge.name != "effectRefs")
        continue;
      for (const LedgerPosting &posting : graph.ledgerPostings)
        if (posting.id == edge.to)
          finalized.postings.push_back(&posting);
    }
    std::stable_sort(finalized.postings.begin(), finalized.postings.end(),
                     [](const auto *a, const auto *b) {
                       return a->effectIndex < b->effectIndex;
                     });
    if (finalized.postings.empty())
      return error("diag:FinalizedProjectionSequence:empty-effect-group");
    for (const LedgerPosting *posting : finalized.postings) {
      FinalizedPostingProjection item;
      item.posting = posting;
      if (posting->direction == "debit")
        item.direction = FinalizedPostingDirection::Debit;
      else if (posting->direction == "credit")
        item.direction = FinalizedPostingDirection::Credit;
      else
        return error("diag:FinalizedProjectionSequence:posting-direction");
      const auto value = llvm::find_if(
          out.values.postings, [&](const PostingValueProjection &candidate) {
            return candidate.effectIndex == posting->effectIndex;
          });
      if (value == out.values.postings.end())
        return error("diag:FinalizedProjectionSequence:posting-value");
      if (!value->memo.empty())
        item.memo = value->memo;
      // : the per-posting typed memo variant, derived MECHANICALLY from
      // the already-verified posting value (no operand inspection, no semantic
      // branch, no string escaping — target-neutral). A generated backend picks
      // the memo-column vs non-memo posting shape from this closed enum.
      item.memoPresence = value->memo.empty() ? FinalizedPostingMemo::Absent
                                              : FinalizedPostingMemo::Present;
      if (finalized.guard.present &&
          finalized.guard.guardKind == "comparison" &&
          finalized.guard.comparisonGuard) {
        item.guardKind = FinalizedPostingGuardKind::Comparison;
        item.comparisonGuard = finalized.guard.comparisonGuard.get();
      } else if (finalized.guard.present &&
                 finalized.guard.guardKind != "attested") {
        return error("diag:FinalizedProjectionSequence:posting-guard");
      }
      item.groupIndex = ordinal;
      item.ordinal = static_cast<size_t>(posting->effectIndex);
      finalized.finalizedPostings.push_back(std::move(item));
    }
    out.effectGroups.push_back(std::move(finalized));
  }
  for (size_t groupIndex = 0; groupIndex < out.effectGroups.size();
       ++groupIndex)
    for (const FinalizedPostingProjection &posting :
         out.effectGroups[groupIndex].finalizedPostings)
      out.postings.push_back(posting);
  std::stable_sort(out.postings.begin(), out.postings.end(),
                   [](const auto &a, const auto &b) {
                     return a.posting->effectIndex < b.posting->effectIndex;
                   });

  for (const BalanceAssertion &assertion : graph.balanceAssertions)
    out.balanceAssertions.push_back(&assertion);

  if (out.executionMode != ExecutionMode::Evidence && out.postings.empty())
    return error("diag:FinalizedProjectionSequence:postings-missing");
  if (out.executionMode == ExecutionMode::Evidence &&
      out.attestation.policies.front().evidenceStyle != "evidence-only")
    return error("diag:FinalizedProjectionSequence:evidence-style");
  if (out.executionMode == ExecutionMode::Temporal) {
    for (const FinalizedEffectGroupProjection &group : out.effectGroups)
      if (!group.guard.present || group.guard.guardKind != "attested" ||
          group.guard.applicationMode != "temporal-suppress")
        return error("diag:FinalizedProjectionSequence:temporal-group-guard");
  }
  // Finalize the postings-shape variant ONCE (target-blind): the coordination's
  // schema carries a memo column iff some posting value declares a memo.
  // Backends bind this presence mechanically and do not re-scan postings.
  out.postingsSchemaKind =
      std::any_of(out.values.postings.begin(), out.values.postings.end(),
                  [](const PostingValueProjection &value) {
                    return !value.memo.empty();
                  })
          ? FinalizedPostingsSchemaKind::WithMemo
          : FinalizedPostingsSchemaKind::Plain;
  return out;
}

namespace {

// The closed edge -> (allowed from-kinds, allowed to-kinds) table (§3),
// mirrored from the design's typed-edge cardinality table so a mis-kinded edge
// fails.
using KindSet = std::set<ProjectionNodeKind>;
const std::map<std::string, std::pair<KindSet, KindSet>> &edgeEndpointKinds() {
  using K = ProjectionNodeKind;
  static const std::map<std::string, std::pair<KindSet, KindSet>> table = {
      {"guardRef", {{K::BalancedEffectGroup}, {K::GuardObligation}}},
      {"policyRef",
       {{K::GuardObligation, K::PrimitiveObligation}, {K::QuorumPolicy}}},
      {"inputRef", {{K::QuorumPolicy}, {K::EvidenceAcceptance}}},
      {"observerSetRef", {{K::QuorumPolicy}, {K::Reference}}},
      {"effectGroupRefs", {{K::Transition}, {K::BalancedEffectGroup}}},
      {"fromRef", {{K::Transition}, {K::LifecycleState}}},
      {"toRef", {{K::Transition}, {K::LifecycleState}}},
      {"stateRef", {{K::ProjectedLifecycleRole}, {K::LifecycleState}}},
      {"execRef", {{K::CommitState}, {K::ExecutionIdentity}}},
      {"scopeRef", {{K::CommitState}, {K::QuorumPolicy}}},
      {"requiredCommitRefs", {{K::LifecycleState}, {K::CommitState}}},
      {"groupRef", {{K::LedgerPosting}, {K::BalancedEffectGroup}}},
      {"effectRefs", {{K::BalancedEffectGroup}, {K::LedgerPosting}}},
      {"assertsRefs", {{K::BalanceAssertion}, {K::BalancedEffectGroup}}},
      {"ledgerRef", {{K::LedgerPosting}, {K::TypedOperand, K::ComputeNode}}},
      {"partyRef", {{K::LedgerPosting}, {K::TypedOperand, K::ComputeNode}}},
      {"amountRef", {{K::LedgerPosting}, {K::TypedOperand, K::ComputeNode}}},
      {"currencyRef", {{K::LedgerPosting}, {K::TypedOperand, K::ComputeNode}}},
      {"memoRef", {{K::LedgerPosting}, {K::TypedOperand, K::ComputeNode}}},
      {"operandRefs", {{K::ComputeNode}, {K::TypedOperand, K::ComputeNode}}},
      {"compensates",
       {{K::CompensationObligation}, {K::BalancedEffectGroup, K::Transition}}},
  };
  return table;
}

} // namespace

std::string verifyAndOrder(BackendProjectionGraph &graph) {
  // ---- unique stable ids across ALL node kinds (F2/F10/F11) + id -> kind ---
  std::unordered_map<std::string, ProjectionNodeKind> kindOf;
  auto reg = [&](const std::string &id, ProjectionNodeKind k,
                 const char *dup) -> const char * {
    if (!kindOf.emplace(id, k).second)
      return dup;
    return nullptr;
  };
#define REG(vec, kind, diag)                                                   \
  for (const auto &n : graph.vec)                                              \
    if (const char *d = reg(n.id, ProjectionNodeKind::kind, diag))             \
      return d;
  REG(executionIdentities, ExecutionIdentity,
      "diag:ExecutionIdentity:duplicate-id")
  REG(commitStates, CommitState, "diag:CommitState:duplicate-id")
  REG(lifecycleStates, LifecycleState, "diag:LifecycleState:duplicate-id")
  REG(transitions, Transition, "diag:Transition:duplicate-id")
  REG(quorumPolicies, QuorumPolicy, "diag:QuorumPolicy:duplicate-id")
  REG(guardObligations, GuardObligation, "diag:GuardObligation:duplicate-id")
  REG(evidenceAcceptances, EvidenceAcceptance,
      "diag:EvidenceAcceptance:duplicate-id")
  REG(primitiveObligations, PrimitiveObligation,
      "diag:PrimitiveObligation:duplicate-id")
  REG(balancedEffectGroups, BalancedEffectGroup,
      "diag:BalancedEffectGroup:duplicate-id")
  REG(ledgerPostings, LedgerPosting, "diag:LedgerPosting:duplicate-id")
  REG(balanceAssertions, BalanceAssertion, "diag:BalanceAssertion:duplicate-id")
  REG(compensationObligations, CompensationObligation,
      "diag:CompensationObligation:duplicate-id")
  REG(typedOperands, TypedOperand, "diag:TypedOperand:duplicate-id")
  REG(typedParams, TypedParam, "diag:TypedParam:duplicate-id")
  REG(references, Reference, "diag:Reference:duplicate-id")
  REG(computeNodes, ComputeNode, "diag:ComputeNode:duplicate-id")
  REG(projectedLifecycleRoles, ProjectedLifecycleRole,
      "diag:ProjectedLifecycleRole:duplicate-id")
#undef REG

  for (const ExecutionIdentity &exec : graph.executionIdentities)
    if (exec.invokedEvent.empty())
      return "diag:ExecutionIdentity:invokedEvent-missing";

  // ---- S0.1: Reference.bindingValue present iff role=="observerSet" --------
  // The lossless authorization operand is required (non-empty) EXACTLY for an
  // observer-set reference and forbidden (empty) otherwise — fail closed. This
  // biting rule catches both a dropped binding and a binding smuggled onto a
  // non-observerSet reference.
  for (const auto &r : graph.references) {
    const bool isObserverSet = r.role == "observerSet";
    if (isObserverSet && r.bindingValue.empty())
      return "diag:Reference:observerSet-bindingValue-missing";
    if (!isObserverSet && !r.bindingValue.empty())
      return "diag:Reference:non-observerSet-bindingValue-spurious";
  }
  // §2.4 lossless typed bindings are complete, uniquely ordered, and carry a
  // reconstructable typed AST. Targets consume this data; they never recover
  // names, order, or expressions from a CoordinationPlan.
  {
    std::set<int> paramOrdinals;
    std::set<std::string> paramBindings;
    for (const auto &param : graph.typedParams) {
      if (param.bindingValue.empty())
        return "diag:TypedParam:bindingValue-missing";
      if (param.type.empty())
        return "diag:TypedParam:type-missing";
      if (param.ordinal < 0 || !paramOrdinals.insert(param.ordinal).second)
        return "diag:TypedParam:ordinal";
      if (!paramBindings.insert(param.bindingValue).second)
        return "diag:TypedParam:bindingValue-duplicate";
    }
    for (int i = 0; i < static_cast<int>(paramOrdinals.size()); ++i)
      if (!paramOrdinals.count(i))
        return "diag:TypedParam:ordinal";

    // §2.4 closed instance-key role (): the role is a projected fact, so it
    // must hold EXACTLY for the param whose binding is a declared execution
    // instance key. A param marked without binding an instance key, or a
    // key-binding param left unmarked, is a malformed graph and fails closed.
    std::set<std::string> instanceKeys;
    for (const auto &exec : graph.executionIdentities)
      if (!exec.instanceKey.empty())
        instanceKeys.insert(exec.instanceKey);
    for (const auto &param : graph.typedParams) {
      const bool shouldBeKey = instanceKeys.count(param.bindingValue) > 0;
      if (param.isInstanceKey && !shouldBeKey)
        return "diag:TypedParam:instance-key-role-unbound";
      if (!param.isInstanceKey && shouldBeKey)
        return "diag:TypedParam:instance-key-role-missing";
    }

    std::set<int> computeOrdinals;
    std::set<std::string> computeBindings;
    for (const auto &compute : graph.computeNodes) {
      if (compute.bindingValue.empty())
        return "diag:ComputeNode:bindingValue-missing";
      if (compute.ordinal < 0 ||
          !computeOrdinals.insert(compute.ordinal).second)
        return "diag:ComputeNode:ordinal";
      if (!computeBindings.insert(compute.bindingValue).second)
        return "diag:ComputeNode:bindingValue-duplicate";
      auto json = llvm::json::parse(compute.expression);
      if (!json)
        return "diag:ComputeNode:expression-invalid";
      try {
        ExprPtr expression = exprFromJson(*json);
        if (exprKindName(expression->kind) != compute.exprKind ||
            categoryName(expression->dtype) != compute.dtype)
          return "diag:ComputeNode:expression-shape";
      } catch (const ExprError &) {
        return "diag:ComputeNode:expression-invalid";
      }
    }
    for (int i = 0; i < static_cast<int>(computeOrdinals.size()); ++i)
      if (!computeOrdinals.count(i))
        return "diag:ComputeNode:ordinal";
  }

  // ---- terminal ⇒ terminalKind set (§2.1) ---------------------------------
  for (const auto &s : graph.lifecycleStates)
    if (s.terminal && s.terminalKind == TerminalKind::None)
      return "diag:LifecycleState:terminal-without-kind";

  // ---- every typed edge resolves to one node of the declared kind (F1) ----
  const auto &endpoints = edgeEndpointKinds();
  std::map<std::pair<std::string, std::string>, int>
      outDeg;                                              // (from,name)->count
  std::map<std::string, std::set<std::string>> byFromName; // "from\0name"->tos
  for (const auto &e : graph.edges) {
    auto it = endpoints.find(e.name);
    if (it == endpoints.end())
      return "diag:edge:" + e.name + "-unknown";
    auto fromIt = kindOf.find(e.from), toIt = kindOf.find(e.to);
    if (fromIt == kindOf.end())
      return "diag:edge:" + e.name + "-from-dangling";
    if (toIt == kindOf.end())
      return "diag:edge:" + e.name + "-dangling";
    if (!it->second.first.count(fromIt->second))
      return "diag:edge:" + e.name + "-from-kind";
    if (!it->second.second.count(toIt->second))
      return "diag:edge:" + e.name + "-to-kind";
    ++outDeg[{e.from, e.name}];
    byFromName[e.from + std::string(1, '\0') + e.name].insert(e.to);
  }
  auto deg = [&](const std::string &from, const std::string &name) {
    auto it = outDeg.find({from, name});
    return it == outDeg.end() ? 0 : it->second;
  };

  // ---- exact §3 cardinalities per owning node -----------------------------
  for (const auto &c : graph.commitStates) {
    if (deg(c.id, "execRef") != 1)
      return "diag:CommitState:execRef-cardinality";
    if (deg(c.id, "scopeRef") != 1)
      return "diag:CommitState:scopeRef-cardinality";
  }
  for (const auto &t : graph.transitions) {
    if (deg(t.id, "fromRef") != 1)
      return "diag:Transition:fromRef-cardinality";
    if (deg(t.id, "toRef") != 1)
      return "diag:Transition:toRef-cardinality";
  }
  for (const auto &p : graph.quorumPolicies) {
    if (deg(p.id, "inputRef") != 1)
      return "diag:QuorumPolicy:inputRef-cardinality";
    if (deg(p.id, "observerSetRef") != 1)
      return "diag:QuorumPolicy:observerSetRef-cardinality";
  }
  for (const auto &gd : graph.guardObligations) {
    const int want = gd.guardKind == "attested" ? 1 : 0;
    if (deg(gd.id, "policyRef") != want)
      return "diag:GuardObligation:policyRef-cardinality"; // F12
    if ((gd.guardKind == "attested" && gd.applicationMode != "atomic-refuse" &&
         gd.applicationMode != "temporal-suppress") ||
        (gd.guardKind == "comparison" && gd.applicationMode != "comparison"))
      return "diag:GuardObligation:application-mode";
  }
  for (const BalancedEffectGroup &group : graph.balancedEffectGroups) {
    auto guard = consumeGroupGuardProjection(graph, group.sourceRef);
    if (!guard)
      return llvm::toString(guard.takeError());
  }
  for (const auto &ea : graph.evidenceAcceptances)
    if (ea.bindingValue.empty())
      return "diag:EvidenceAcceptance:bindingValue-missing";
  for (const auto &pr : graph.primitiveObligations) {
    const int refs = deg(pr.id, "policyRef");
    // §5: finalizedKind is a CLOSED set — an unknown value must NOT be treated
    // as PerPolicy (or anything else); it fails. §3: `.Single` ranges over
    // EXACTLY ONE policy; `.PerPolicy` over 1..n.
    if (pr.finalizedKind == "QuorumAcceptance.Single") {
      if (refs != 1)
        return "diag:PrimitiveObligation:single-policyRef-cardinality";
    } else if (pr.finalizedKind == "QuorumAcceptance.PerPolicy") {
      if (refs < 1)
        return "diag:PrimitiveObligation:policyRef-cardinality";
    } else {
      return "diag:PrimitiveObligation:unknown-finalizedKind";
    }
  }
  // §2.4/§3: a ComputeNode carries 1..n operand refs.
  for (const auto &cn : graph.computeNodes)
    if (deg(cn.id, "operandRefs") < 1)
      return "diag:ComputeNode:operandRefs-cardinality";
  // A compute's typed AST and operandRefs are the same authority: every
  // variable leaf resolves to exactly the projected parameter/compute node
  // named by its edge, and no stale/spurious edge survives an AST mutation.
  {
    std::map<std::string, std::string> computeByBinding;
    std::map<std::string, std::string> paramValueByBinding;
    for (const auto &compute : graph.computeNodes)
      computeByBinding[compute.bindingValue] = compute.id;
    for (const auto &param : graph.typedParams)
      paramValueByBinding[param.bindingValue] = "ref:" + param.name;
    for (const auto &compute : graph.computeNodes) {
      auto json = llvm::json::parse(compute.expression);
      if (!json)
        return "diag:ComputeNode:expression-invalid";
      ExprPtr expression;
      try {
        expression = exprFromJson(*json);
      } catch (const ExprError &) {
        return "diag:ComputeNode:expression-invalid";
      }
      std::set<std::string> expected;
      for (const std::string &var : exprVars(*expression)) {
        if (auto it = computeByBinding.find(var);
            it != computeByBinding.end()) {
          expected.insert(it->second);
          continue;
        }
        auto param = paramValueByBinding.find(var);
        if (param == paramValueByBinding.end())
          return "diag:ComputeNode:expression-reference-unresolved";
        const TypedOperand *operand = nullptr;
        for (const auto &candidate : graph.typedOperands)
          if (candidate.operandKind == "value" &&
              candidate.value == param->second) {
            if (operand)
              return "diag:ComputeNode:expression-reference-ambiguous";
            operand = &candidate;
          }
        if (!operand)
          return "diag:ComputeNode:expression-reference-missing";
        expected.insert(operand->id);
      }
      const auto &actual =
          byFromName[compute.id + std::string(1, '\0') + "operandRefs"];
      if (expected != actual)
        return "diag:ComputeNode:expression-operands";
    }
  }
  for (const auto &po : graph.ledgerPostings) {
    if (deg(po.id, "groupRef") != 1)
      return "diag:LedgerPosting:groupRef-cardinality";
    for (const char *ref :
         {"ledgerRef", "partyRef", "amountRef", "currencyRef"})
      if (deg(po.id, ref) != 1)
        return std::string("diag:LedgerPosting:") + ref + "-cardinality";
    if (deg(po.id, "memoRef") > 1)
      return "diag:LedgerPosting:memoRef-cardinality";
  }
  for (const auto &bg : graph.balancedEffectGroups) {
    if (deg(bg.id, "effectRefs") < 1)
      return "diag:BalancedEffectGroup:effectRefs-cardinality";
    if (deg(bg.id, "guardRef") > 1)
      return "diag:BalancedEffectGroup:guardRef-cardinality";
  }
  for (const auto &co : graph.compensationObligations)
    if (deg(co.id, "compensates") != 1)
      return "diag:CompensationObligation:compensates-cardinality"; // F9

  // ---- CompensationObligation per-group coverage (exact, graph-carried) ----
  // A group's `rollbackRequired` flag makes "needs compensation" a graph fact,
  // so the set of group-targeted `compensates` edges must EXACTLY equal the set
  // of rollback-requiring groups: no missing (INCLUDING when ALL compensations
  // are dropped — the required set is non-empty while the compensated set is
  // empty), no spurious group, no duplicate. A temporal balanced group has
  // rollbackRequired=false, so it correctly requires none.
  {
    std::set<std::string> rollbackGroups;
    for (const auto &bg : graph.balancedEffectGroups)
      if (bg.rollbackRequired)
        rollbackGroups.insert(bg.id);
    std::set<std::string> compensatedGroups;
    for (const auto &e : graph.edges) {
      if (e.name != "compensates")
        continue;
      // A transition-targeted compensation is a different form (§3); this
      // coverage rule governs the group-targeted rollback obligations.
      if (kindOf[e.to] != ProjectionNodeKind::BalancedEffectGroup)
        continue;
      if (!compensatedGroups.insert(e.to).second)
        return "diag:CompensationObligation:duplicate-coverage";
    }
    if (compensatedGroups != rollbackGroups)
      return "diag:CompensationObligation:coverage";
  }

  // ---- posting/group inverse-exact (F14-F17 analog for postings) ----------
  // Every group's effectRefs are exactly the postings whose groupRef points
  // back — no missing, extra, or duplicate.
  for (const auto &bg : graph.balancedEffectGroups) {
    const auto &effs = byFromName[bg.id + std::string(1, '\0') + "effectRefs"];
    for (const std::string &pid : effs)
      if (!byFromName[pid + std::string(1, '\0') + "groupRef"].count(bg.id))
        return "diag:BalancedEffectGroup:effectRefs-not-inverse";
  }
  for (const auto &po : graph.ledgerPostings) {
    const auto &grp = byFromName[po.id + std::string(1, '\0') + "groupRef"];
    for (const std::string &gid : grp)
      if (!byFromName[gid + std::string(1, '\0') + "effectRefs"].count(po.id))
        return "diag:LedgerPosting:groupRef-not-inverse";
  }

  // ---- BalanceAssertion covers exactly the mustBalance groups (B3) --------
  std::set<std::string> mustBalance;
  for (const auto &bg : graph.balancedEffectGroups)
    if (bg.mustBalance)
      mustBalance.insert(bg.id);
  for (const auto &ba : graph.balanceAssertions) {
    const auto &covered =
        byFromName[ba.id + std::string(1, '\0') + "assertsRefs"];
    if (std::set<std::string>(covered.begin(), covered.end()) != mustBalance)
      return "diag:BalanceAssertion:coverage"; // F6 coverage
    // duplicate assertsRefs (a group asserted twice) -> the multiset != set.
    if (deg(ba.id, "assertsRefs") != static_cast<int>(mustBalance.size()))
      return "diag:BalanceAssertion:duplicate-coverage";
  }

  // ---- structural completeness: a required node may not be MISSING ---------
  // These catch a dropped node that the per-edge/per-owner checks above would
  // otherwise pass over (an absent node owns no edge to dangle).
  // (a) a balanced coordination carries EXACTLY ONE coordination-scoped
  //     BalanceAssertion — present iff there are mustBalance groups (B3).
  if (!mustBalance.empty() && graph.balanceAssertions.size() != 1)
    return "diag:BalanceAssertion:missing";
  if (mustBalance.empty() && !graph.balanceAssertions.empty())
    return "diag:BalanceAssertion:spurious";
  // (b) exactly one ExecutionIdentity anchors any obligation-bearing graph.
  const bool hasObligations = !graph.commitStates.empty() ||
                              !graph.quorumPolicies.empty() ||
                              !graph.ledgerPostings.empty();
  if (hasObligations && graph.executionIdentities.size() != 1)
    return "diag:ExecutionIdentity:missing";

  // ---- terminal requiredCommitRefs EXACTLY cover the CommitStates ---------
  std::set<std::string> allCommits;
  for (const auto &c : graph.commitStates)
    allCommits.insert(c.id);
  size_t terminalStateCount = 0;
  for (const auto &s : graph.lifecycleStates)
    terminalStateCount += s.terminal ? 1 : 0;
  // (c) CommitStates without a covering terminal state are orphaned — a missing
  //     terminal LifecycleState leaves them uncommitted.
  if (!allCommits.empty() && terminalStateCount == 0)
    return "diag:LifecycleState:missing-terminal";
  for (const auto &s : graph.lifecycleStates) {
    if (!s.terminal)
      continue;
    const auto &req =
        byFromName[s.id + std::string(1, '\0') + "requiredCommitRefs"];
    if (std::set<std::string>(req.begin(), req.end()) != allCommits)
      return "diag:LifecycleState:requiredCommitRefs-coverage"; // F14/F15
    if (deg(s.id, "requiredCommitRefs") != static_cast<int>(allCommits.size()))
      return "diag:LifecycleState:requiredCommitRefs-duplicate"; // F17
  }

  // ---- ComputeNode operand graph is acyclic (§2.4) ------------------------
  {
    std::unordered_map<std::string, std::vector<std::string>> adj;
    std::unordered_set<std::string> computeIds;
    for (const auto &cn : graph.computeNodes)
      computeIds.insert(cn.id);
    for (const auto &e : graph.edges)
      if (e.name == "operandRefs")
        adj[e.from].push_back(e.to);
    std::unordered_map<std::string, int> mark; // 0=unseen,1=onstack,2=done
    std::function<bool(const std::string &)> hasCycle =
        [&](const std::string &n) -> bool {
      int &m = mark[n];
      if (m == 1)
        return true;
      if (m == 2)
        return false;
      m = 1;
      for (const std::string &t : adj[n])
        if (computeIds.count(t) && hasCycle(t))
          return true;
      m = 2;
      return false;
    };
    for (const auto &cn : graph.computeNodes)
      if (hasCycle(cn.id))
        return "diag:ComputeNode:operandRefs-cyclic";
  }

  // ---- §2.1 ProjectedLifecycleRole role-set + success anchoring (§3) -------
  // Backend-blind lowering obligations: whenever the graph reaches a success
  // terminal a target must spell its status-authority quotient, so the role set
  // is REQUIRED and EXACT. Every role anchors (`stateRef`, 1) to the projected
  // success terminal and its `state` payload MUST equal that edge's target name
  // (the typed edge is the sole association authority — no unchecked
  // duplicate). All roles share the coordination's single execution mode; the
  // set is EXACTLY the required set for that mode (Evidence/Temporal ->
  // {Initial, Success}; Effectful adds AcceptedOrAttested). Finally the
  // declared mode is checked against an INDEPENDENT re-derivation from graph
  // structure, so a uniform mode substitution (which keeps the role set
  // internally consistent) cannot pass. A legalizer consumes this set and may
  // not invent, drop, or re-select a role.
  {
    bool hasSuccessTerminal = false;
    for (const auto &s : graph.lifecycleStates)
      if (s.terminalKind == TerminalKind::Success)
        hasSuccessTerminal = true;
    if (hasSuccessTerminal && graph.projectedLifecycleRoles.empty())
      return "diag:ProjectedLifecycleRole:missing";
    if (!graph.projectedLifecycleRoles.empty()) {
      std::set<LifecycleRole> seen;
      bool haveMode = false;
      ExecutionMode mode = ExecutionMode::Effectful;
      for (const auto &r : graph.projectedLifecycleRoles) {
        if (deg(r.id, "stateRef") != 1)
          return "diag:ProjectedLifecycleRole:stateRef-cardinality";
        const auto &tos = byFromName[r.id + std::string(1, '\0') + "stateRef"];
        for (const std::string &sid : tos) {
          const LifecycleState *st = nullptr;
          for (const auto &s : graph.lifecycleStates)
            if (s.id == sid) {
              st = &s;
              break;
            }
          if (!st || st->terminalKind != TerminalKind::Success)
            return "diag:ProjectedLifecycleRole:stateRef-not-success-terminal";
          // P1-B: the serialized `state` payload is not an independent
          // authority — it must equal the state the typed `stateRef` edge
          // resolves to.
          if (st->name != r.state)
            return "diag:ProjectedLifecycleRole:state-edge-disagreement";
        }
        if (!haveMode) {
          mode = r.mode;
          haveMode = true;
        } else if (mode != r.mode) {
          return "diag:ProjectedLifecycleRole:mode-inconsistent";
        }
        if (!seen.insert(r.role).second)
          return "diag:ProjectedLifecycleRole:duplicate-role";
      }
      std::set<LifecycleRole> required = {LifecycleRole::Initial,
                                          LifecycleRole::Success};
      if (mode == ExecutionMode::Effectful)
        required.insert(LifecycleRole::AcceptedOrAttested);
      if (seen != required)
        return "diag:ProjectedLifecycleRole:role-set";

      // P1-A: the declared mode must match an INDEPENDENT re-derivation from
      // graph structure — never merely be self-consistent. Evidence is recorded
      // by the EvidenceAcceptance style (a coordination without ledger
      // effects); temporal by a balanced group that carries NO rollback
      // obligation
      // (`rollbackRequired` is itself anchored to the CompensationObligation
      // coverage checked above, so a tamperer cannot flip it freely). A uniform
      // Evidence->Temporal (or Effectful<->Temporal) substitution then fails.
      bool evidenceStructure = false;
      for (const auto &ea : graph.evidenceAcceptances)
        if (ea.style == "evidence-only")
          evidenceStructure = true;
      bool temporalStructure = false;
      for (const auto &bg : graph.balancedEffectGroups)
        if (bg.mustBalance && !bg.rollbackRequired)
          temporalStructure = true;
      const ExecutionMode expected = evidenceStructure ? ExecutionMode::Evidence
                                     : temporalStructure
                                         ? ExecutionMode::Temporal
                                         : ExecutionMode::Effectful;
      if (mode != expected)
        return "diag:ProjectedLifecycleRole:mode-structure-mismatch";
    }
  }

  // ---- §4 deterministic order: nodes by stable id, edges by (from,name,to) -
  auto byId = [](const auto &a, const auto &b) { return a.id < b.id; };
  std::stable_sort(graph.executionIdentities.begin(),
                   graph.executionIdentities.end(), byId);
  std::stable_sort(graph.commitStates.begin(), graph.commitStates.end(), byId);
  std::stable_sort(graph.lifecycleStates.begin(), graph.lifecycleStates.end(),
                   byId);
  std::stable_sort(graph.transitions.begin(), graph.transitions.end(), byId);
  std::stable_sort(graph.projectedLifecycleRoles.begin(),
                   graph.projectedLifecycleRoles.end(), byId);
  std::stable_sort(graph.quorumPolicies.begin(), graph.quorumPolicies.end(),
                   byId);
  std::stable_sort(graph.guardObligations.begin(), graph.guardObligations.end(),
                   byId);
  std::stable_sort(graph.evidenceAcceptances.begin(),
                   graph.evidenceAcceptances.end(), byId);
  std::stable_sort(graph.primitiveObligations.begin(),
                   graph.primitiveObligations.end(), byId);
  std::stable_sort(graph.balancedEffectGroups.begin(),
                   graph.balancedEffectGroups.end(), byId);
  std::stable_sort(graph.ledgerPostings.begin(), graph.ledgerPostings.end(),
                   byId);
  std::stable_sort(graph.balanceAssertions.begin(),
                   graph.balanceAssertions.end(), byId);
  std::stable_sort(graph.compensationObligations.begin(),
                   graph.compensationObligations.end(), byId);
  std::stable_sort(graph.typedOperands.begin(), graph.typedOperands.end(),
                   byId);
  std::stable_sort(graph.typedParams.begin(), graph.typedParams.end(), byId);
  std::stable_sort(graph.references.begin(), graph.references.end(), byId);
  std::stable_sort(graph.computeNodes.begin(), graph.computeNodes.end(), byId);
  std::stable_sort(graph.edges.begin(), graph.edges.end(),
                   [](const ProjectionEdge &a, const ProjectionEdge &b) {
                     return std::tie(a.from, a.name, a.to) <
                            std::tie(b.from, b.name, b.to);
                   });
  return "";
}

} // namespace projection
} // namespace neutrino
