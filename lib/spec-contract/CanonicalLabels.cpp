//===- CanonicalLabels.cpp - establish CoordinationPlan canonical labels --===//

#include "Neutrino/CanonicalLabels.h"

#include "Neutrino/Expr.h"

namespace neutrino {

namespace {
// Label every value (`Var`) identity an expression references, recursing into
// binary/compare/call operands — mirrors the serializer's semanticExpr walk so
// a guard operand establishes its input label in the same place.
void labelExpr(const ExprNode *node, SemanticLabels &labels) {
  if (!node)
    return;
  if (node->kind == ExprNode::Var)
    (void)labels.value(node->name);
  labelExpr(node->lhs.get(), labels);
  labelExpr(node->rhs.get(), labels);
  for (const auto &arg : node->args)
    labelExpr(arg.get(), labels);
}
} // namespace

void establishProjectionLabels(const CoordinationPlan &p,
                               SemanticLabels &labels) {
  (void)labels.value(p.workflowKey);
  if (!p.explicitInstanceKey.empty())
    (void)labels.value(p.explicitInstanceKey);

  for (const PlanEffect &e : p.effects) {
    (void)labels.ledger(e.ledger);
    (void)labels.operand(e.party);
    (void)labels.operand(e.amount);
    (void)labels.operand(e.currency);
    labelExpr(e.guard.get(), labels);
    if (!e.gatePolicy.empty())
      (void)labels.value(e.gatePolicy);
    if (!e.attestationInput.empty())
      (void)labels.value(e.attestationInput);
  }

  for (const PlanEffectGroup &g : p.effectGroups) {
    if (!g.effectIndices.empty())
      labelExpr(p.effects[g.effectIndices.front()].guard.get(), labels);
    if (!g.gatePolicy.empty())
      (void)labels.value(g.gatePolicy);
    if (!g.attestationInput.empty())
      (void)labels.value(g.attestationInput);
  }

  for (const AttestationPolicy &a : p.attestations) {
    (void)labels.value(a.input);
    (void)labels.observerSet(a.observerSet);
    (void)labels.observerRole(a.observerRole);
  }

  for (const PlanCompute &c : p.computes)
    (void)labels.value(c.name);
  {
    std::map<std::string, const PlanCompute *> byName;
    for (const PlanCompute &c : p.computes)
      byName.emplace(c.name, &c);
    for (const std::string &name : labels.computes()) {
      const PlanCompute &c = *byName.at(name);
      for (const std::string &dep : c.deps)
        (void)labels.value(dep);
    }
  }

  // Deadline detail refs (best-effort, transition order) — they never precede
  // an operand, so they never perturb a trace-relevant operand index.
  for (const LifecycleTransitionPolicy &t : p.lifecycleTransitions)
    for (const LifecycleTransitionGuardPolicy &guard : t.guards)
      if (guard.kind == "deadline" && !guard.detail.empty())
        (void)labels.value(guard.detail);

  labels.completeValues();
}

} // namespace neutrino
