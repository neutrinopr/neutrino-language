#include "Neutrino/View.h"

#include "Neutrino/ExprAttr.h"
#include "Neutrino/ValueModel.h"
#include "mlir/IR/Location.h"
#include "llvm/ADT/SmallVector.h"

#include <cctype>
#include <map>
#include <memory>

using namespace mlir;
using namespace neutrino;

neutrino::ProcedureOp neutrino::findProcedure(mlir::ModuleOp module,
                                              llvm::StringRef name) {
  ProcedureOp found;
  for (auto p : module.getOps<ProcedureOp>())
    if (p.getSymName() == name)
      found = p;
  return found;
}

neutrino::ProcedureOp neutrino::defaultProcedure(mlir::ModuleOp module) {
  // The scenario-free selection (D2 / , --target=capability-spec): the
  // module's procedure, last declaration wins — the same rule findProcedure
  // uses, without a name.
  ProcedureOp found;
  for (auto p : module.getOps<ProcedureOp>())
    found = p;
  return found;
}

bool neutrino::isNumericType(llvm::StringRef ty) {
  // Delegates to the typed value model (WP1a, ): one classifier owns the
  // value-type categories, so backends/validation no longer re-derive "is this
  // numeric" from raw strings. Behavior is identical to the previous string
  // set.
  return isNumericCategory(classifyValueType(ty));
}

// `pascalCase` moved to the contract leaf (lib/spec-contract/StrCase.cpp, )
// so a leaf-only renderer can name contracts from the spec without View.h;
// View.h re-includes StrCase.h, so the callers below still resolve it (through
// the leaf they already link).
std::string ProcedureView::pascalName() const { return pascalCase(name); }

// 1-based source start line of an op: a FileLineColLoc is one line; a FusedLoc
// (block ops) starts at its earliest FileLineColLoc. 0 when no file location is
// attached. Mirrors Emit.cpp's range extraction (the frontend attaches these,
// ).
static int startLine(mlir::Location loc) {
  if (auto fl = loc.dyn_cast<mlir::FileLineColLoc>())
    return (int)fl.getLine();
  if (auto fused = loc.dyn_cast<mlir::FusedLoc>()) {
    int s = 0;
    for (mlir::Location l : fused.getLocations())
      if (auto f = l.dyn_cast<mlir::FileLineColLoc>())
        if (s == 0 || (int)f.getLine() < s)
          s = (int)f.getLine();
    return s;
  }
  return 0;
}

static Ref refOf(Value v) {
  Operation *def = v.getDefiningOp();
  if (auto c = dyn_cast_or_null<ConstOp>(def))
    return {true, c.getValue().str()};
  if (auto in = dyn_cast_or_null<InputOp>(def))
    return {false, in.getSymName().str()};
  if (auto cm = dyn_cast_or_null<ComputeOp>(def))
    return {false, cm.getSymName().str()};
  return {false, "?"};
}

ProcedureView neutrino::viewOf(ProcedureOp proc) {
  ProcedureView v;
  v.name = proc.getSymName().str();
  if (auto trig = proc.getTriggerAttr())
    v.trigger = trig.getValue().str();
  if (auto ver = proc.getVersionAttr())
    v.version = ver.getValue().str();
  if (auto key = proc.getInstanceKeyAttr())
    v.instanceKey = key.getValue().str();

  // The value category of each named value in scope, used to type compute
  // expressions once as the view is built (M5 WP1b, ). Inputs classify by
  // their declared type (); a compute result is numeric (Decimal). SSA
  // ordering guarantees a name is defined before it is referenced.
  std::map<std::string, ValueCategory> valueEnv;

  for (Operation &op : proc.getBody().front()) {
    if (auto in = dyn_cast<InputOp>(op)) {
      v.inputs.push_back({in.getSymName().str(), in.getTy().str()});
      v.inputLines.push_back(startLine(op.getLoc()));
      valueEnv[in.getSymName().str()] = classifyValueType(in.getTy().str());
    } else if (auto c = dyn_cast<ComputeOp>(op)) {
      v.computeLines.push_back(startLine(op.getLoc()));
      ComputeView cv{c.getSymName().str(), c.getExpr().str(), {}, {}};
      for (Value d : c.getDeps())
        cv.deps.push_back(refOf(d).second);
      // Read the structured, typed AST straight from the IR (): the
      // frontend parsed + typed it once and the verifier enforced it, so viewOf
      // neither re-parses the source text nor re-infers dtypes — it
      // reconstructs the shared ExprNode (dtypes restored) from the
      // #neutrino.expr attribute.
      ExprPtr ast = toExprNode(c.getAst(), cv.deps);
      valueEnv[cv.name] = ast->dtype;
      cv.ast = std::shared_ptr<const ExprNode>(std::move(ast));
      v.computes.push_back(std::move(cv));
    } else if (isa<DebitOp>(op) || isa<CreditOp>(op)) {
      // DebitOp and CreditOp share the Neutrino_EntryOp accessor set (party /
      // amount / currency / idempotency_key / ledger / owner / participant /
      // guard); a generic lambda reads either without duplicating the guard
      // parse-and-type. Parse + type the guard ONCE against the value env
      // (inputs + computes already in scope by SSA order), then freeze the AST
      // — every renderer and the reference evaluator share it, like a compute.
      auto build = [&](auto e, const char *kind) {
        std::string part = e.getParticipantAttr()
                               ? e.getParticipantAttr().getValue().str()
                               : "";
        EntryView ev{kind,
                     e.getSymName().str(),
                     e.getLedger().str(),
                     e.getOwner().str(),
                     part,
                     refOf(e.getParty()),
                     refOf(e.getAmount()),
                     refOf(e.getCurrency()),
                     refOf(e.getIdempotencyKey())};
        if (auto g = e.getGuardAttr()) {
          ev.guard = g.getValue().str();
          // The typed guard AST comes from the IR (); its var leaves
          // resolve through the entry's guard-dep operands (amendment 2), not a
          // re-parse.
          std::vector<std::string> gdeps;
          for (Value d : e.getGuardDeps())
            gdeps.push_back(refOf(d).second);
          ev.guardAst = std::shared_ptr<const ExprNode>(
              toExprNode(e.getGuardAstAttr(), gdeps));
        }
        if (auto m = e.getMemoAttr())
          ev.memo = m.getValue().str();
        v.entries.push_back(std::move(ev));
        v.entryLines.push_back(startLine(e.getLoc()));
      };
      if (auto d = dyn_cast<DebitOp>(op))
        build(d, "debit");
      else
        build(cast<CreditOp>(op), "credit");
    } else if (auto p = dyn_cast<ParticipantOp>(op)) {
      v.participantLines.push_back(startLine(op.getLoc()));
      ParticipantView pv{p.getSymName().str(), p.getRole().str(), "", {}};
      if (auto org = p.getOrgAttr())
        pv.org = org.getValue().str();
      if (auto caps = p.getCapabilities())
        for (Attribute a : *caps)
          pv.capabilities.push_back(a.cast<StringAttr>().getValue().str());
      if (auto b = p.getBindingAttr())
        pv.binding = b.getValue().str();
      if (auto rt = p.getBindRuntimes())
        for (Attribute a : *rt)
          pv.bindRuntimes.push_back(a.cast<StringAttr>().getValue().str());
      if (auto ma = p.getBindMinAssuranceAttr())
        pv.bindMinAssurance = ma.getValue().str();
      v.participants.push_back(std::move(pv));
    } else if (auto a = dyn_cast<AllowOrgsOp>(op)) {
      v.allowLines.push_back(startLine(op.getLoc()));
      OrgPolicy pol;
      pol.orgA = a.getOrgA().str();
      pol.orgB = a.getOrgB().str();
      if (auto ra = a.getRoleAAttr())
        pol.roleA = ra.getValue().str();
      if (auto rb = a.getRoleBAttr())
        pol.roleB = rb.getValue().str();
      v.allowedOrgPairs.push_back(std::move(pol));
    } else if (auto at = dyn_cast<AttestOp>(op)) {
      v.attestationLines.push_back(startLine(op.getLoc()));
      AttestationPolicy p;
      p.input = at.getInput().str();
      p.quorum = (int)at.getQuorum();
      p.observerSet = at.getObserverSet().str();
      if (auto r = at.getObserverRoleAttr())
        p.observerRole = r.getValue().str();
      p.canonicalization = at.getCanonicalization().str();
      if (auto tol = at.getToleranceAttr())
        p.tolerance = tol.getValue().str();
      if (auto to = at.getTimeoutAttr())
        p.timeout = to.getValue().str();
      if (auto as = at.getAssuranceAttr())
        p.assurance = as.getValue().str();
      if (auto ind = at.getIndependenceAttr())
        p.independence = ind.getValue().str();
      p.fallback = at.getFallback().str();
      v.attestations.push_back(std::move(p));
    } else if (auto ob = dyn_cast<ObligationOp>(op)) {
      // Obligation (L1 v0.2 O1, ): a verified first-class undertaking. Its
      // typed activation predicate decodes exactly like an entry guard (the
      // when_ast var leaves resolve through when_deps), and its ordered effect
      // references are declared entry names. Structure only — no backend.
      ObligationView ov;
      ov.name = ob.getSymName().str();
      ov.obligor = ob.getObligor().str();
      ov.beneficiary = ob.getBeneficiary().str();
      ov.authority = ob.getAuthority().str();
      if (auto w = ob.getWhenAttr()) {
        ov.when = w.getValue().str();
        std::vector<std::string> wdeps;
        for (Value d : ob.getWhenDeps())
          wdeps.push_back(refOf(d).second);
        ov.whenAst = toExprNode(ob.getWhenAstAttr(), wdeps);
      }
      for (Attribute a : ob.getEffects())
        ov.effects.push_back(a.cast<StringAttr>().getValue().str());
      v.obligations.push_back(std::move(ov));
    } else if (isa<AssertBalancedOp>(op)) {
      v.balanced = true;
      v.assertLine = startLine(op.getLoc());
    }
  }
  return v;
}

// Shared event-chain builder. `includeGuarded(e)` decides whether a guarded leg
// () contributes its event: false for the guaranteed/static choreography;
// "does the guard hold for this scenario?" for the concrete one.
static std::vector<std::string>
eventChainImpl(const ProcedureView &view,
               const std::function<bool(const EntryView &)> &includeGuarded) {
  std::vector<std::string> chain;
  chain.push_back(view.trigger ? pascalCase(*view.trigger)
                               : "ProcedureInvoked");
  for (const ComputeView &c : view.computes)
    chain.push_back(pascalCase(c.name) + "Computed");
  for (const EntryView &e : view.entries)
    if (e.guard.empty() || includeGuarded(e))
      chain.push_back(pascalCase(e.name) +
                      (e.kind == "debit" ? "Debited" : "Credited"));
  if (!view.entries.empty())
    chain.push_back(pascalCase(view.name) + "Reconciled");
  return chain;
}

std::vector<std::string> neutrino::eventChain(const ProcedureView &view) {
  // Guaranteed choreography: a guarded leg posts conditionally, so its event is
  // omitted (the renderers emit it inside the guard).
  return eventChainImpl(view, [](const EntryView &) { return false; });
}

std::vector<std::string>
neutrino::eventChain(const ProcedureView &view,
                     const std::map<std::string, long long> &env) {
  // Concrete choreography for a scenario: a guarded leg's event is included iff
  // its predicate holds — the same condition the backends lower to — so the
  // realized/equivalence chain matches what the contract/procedure actually
  // emits on this branch.
  return eventChainImpl(view, [&](const EntryView &e) {
    return e.guardAst && evalGuard(*e.guardAst, env);
  });
}
