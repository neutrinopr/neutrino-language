//===- CoordinationPlanBuild.cpp - normalize the plan from verified MLIR --===//
//
// normalizePlan (): the from-MLIR producer of the CoordinationPlan. It
// reads the verified ProcedureView + the canonical lifecycle machine, gathers
// raw inputs, and hands them to the leaf's assemblePlan — the ONE normalization
// + verification seam it shares with planFromSpec, so the from-MLIR plan and
// the from-spec reconstruction are identical.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationPlanBuild.h"

#include "Neutrino/Expr.h"
#include "Neutrino/LifecycleView.h"
#include "Neutrino/ValueModel.h"

using namespace llvm;

namespace neutrino {

namespace {
// The operand's identity, "kind:value" — mirrors the spec's operand()
// serialization (Ref = (isLiteral, text)), so normalizePlan and planFromSpec
// compare moved values identically.
std::string operandKey(const Ref &r) {
  return std::string(r.first ? "literal:" : "ref:") + r.second;
}

// accepted(x) detection on a typed guard node: a Call named "accepted" whose
// one argument is a Var — returns x, or "" for any other guard shape.
std::string acceptedInputFromNode(const ExprNode *n) {
  if (!n || n->kind != ExprNode::Call || n->name != "accepted")
    return "";
  if (n->args.size() != 1)
    return "";
  const ExprNode *a = n->args[0].get();
  if (!a || a->kind != ExprNode::Var)
    return "";
  return a->name;
}
} // namespace

Expected<CoordinationPlan> normalizePlan(const ProcedureView &view) {
  PlanInputs in;
  in.procedure = view.name;
  in.invokedEvent = view.trigger.value_or("");
  in.attestations = view.attestations;
  in.balanced = view.balanced;
  if (view.instanceKey)
    in.explicitInstanceKey = *view.instanceKey;

  // The declared input inventory {name, type} from the verified view.
  for (const auto &io : view.inputs)
    in.inputs.push_back({io.first, io.second});

  for (const ParticipantView &p : view.participants)
    in.participants.push_back({p.name, p.role, p.org});
  for (const OrgPolicy &p : view.allowedOrgPairs)
    in.allowedOrgPairs.push_back({p.orgA, p.orgB, p.roleA, p.roleB});

  for (const EntryView &e : view.entries) {
    PlanEffectInput pe;
    pe.name = e.name;
    pe.kind = e.kind;
    pe.participant = e.participant;
    // Ref = (isLit, text): a literal key vs an input ref (matches operand()).
    pe.idempotencyKind = e.idempotency_key.first ? "literal" : "ref";
    pe.idempotencyValue = e.idempotency_key.second;
    pe.canonicalGuard = e.guard;
    pe.guardAcceptedInput = acceptedInputFromNode(e.guardAst.get());
    pe.amount = operandKey(e.amount);
    pe.currency = operandKey(e.currency);
    pe.ledger = e.ledger;
    pe.party = operandKey(e.party);
    pe.memo = e.memo;
    // Carry an OWNED copy of the typed guard predicate into the plan (
    // amendment 3); the view holds it by shared_ptr, so deep-copy into ExprPtr.
    if (e.guardAst)
      pe.guard = cloneExpr(*e.guardAst);
    in.effects.push_back(std::move(pe));
  }

  for (const ComputeView &c : view.computes) {
    PlanCompute pc;
    pc.name = c.name;
    pc.category = c.ast ? categoryName(c.ast->dtype).str() : "extension";
    pc.deps = c.deps;
    if (c.ast)
      pc.expr = cloneExpr(*c.ast);
    in.computes.push_back(std::move(pc));
  }

  // Obligations (): carry each verified undertaking through to
  // assemblePlan, which resolves obligor/scope/effects and stamps the lifecycle
  // statuses. The typed predicate is deep-copied into an owned ExprPtr like a
  // guard.
  for (const ObligationView &o : view.obligations) {
    PlanObligationInput po;
    po.name = o.name;
    po.obligor = o.obligor;
    po.beneficiary = o.beneficiary;
    po.authority = o.authority;
    po.canonicalGuard = o.when;
    po.effects = o.effects;
    if (o.whenAst)
      po.when = cloneExpr(*o.whenAst);
    in.obligations.push_back(std::move(po));
  }

  const LifecycleModel m = lifecycleModel(view);
  in.lifecycleInitialState = m.initialState;
  in.terminal.success = m.successState;
  in.terminal.aborted = m.abortedState;
  in.terminal.contested = m.contestedState;
  for (const LifecycleState &s : m.states)
    in.lifecycleStates.push_back(s.name);
  for (const LifecycleTransition &t : m.transitions)
    in.lifecycleTransitions.push_back(
        {t.name, t.from, t.to, t.effects, {}, t.idempotency, std::nullopt});

  return assemblePlan(std::move(in));
}

} // namespace neutrino
