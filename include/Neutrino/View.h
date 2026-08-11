#ifndef NEUTRINO_VIEW_H
#define NEUTRINO_VIEW_H

#include "Neutrino/Attestation.h"
#include "Neutrino/Expr.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/StrCase.h"
#include "mlir/IR/BuiltinOps.h"
#include "llvm/ADT/StringRef.h"

#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace neutrino {

// (isLit, text): a debit/credit operand resolved to a ref name or a const
// literal.
using Ref = std::pair<bool, std::string>;

struct EntryView {
  std::string kind; // "debit" | "credit"
  std::string name, ledger, owner;
  std::string participant; // bound declared participant, "" if unbound
  Ref party, amount, currency, idempotency_key;
  // Optional conditional guard (M5 WP7, ): the leg posts iff this predicate
  // holds. `guard` is the source text (empty if unguarded); `guardAst` is the
  // parsed + typed comparison (a Cmp node), shared immutably with every
  // renderer and the reference evaluator so the guard has one meaning across
  // backends.
  std::string guard;
  std::shared_ptr<const ExprNode> guardAst;
  // Optional effect metadata (M5 token S3, ): a free-text memo/reference
  // carried with the movement; "" when absent. Surfaced in each backend's
  // emitted event/row so a transfer's reference travels with it. Metadata only.
  std::string memo;
};

struct ComputeView {
  std::string name, expr;
  std::vector<std::string> deps;
  // The compute expression, parsed and typed ONCE when the view is built (M5
  // WP1b, ). Every backend renderer and the reference evaluator share this
  // AST instead of re-parsing `expr`; its nodes carry the  value dtype.
  // `const` makes immutability-after-viewOf structural: no consumer can re-type
  // it with a different env.
  std::shared_ptr<const ExprNode> ast;
};

// A first-class undertaking: a scoped obligor commits, under an activation
// predicate, to an ORDERED set of value effects it authorizes. Its
// identity/lifecycle is distinct from effect execution — the `effects` are
// references to declared entry (debit/credit) names, in order.
struct ObligationView {
  std::string name;                            // the obligation identity
  std::string obligor, beneficiary, authority; // declared participant refs
  std::string when;                            // activation predicate source
  // The typed predicate (a Cmp). OWNED (unique) — unlike an entry guard it is
  // not shared with a renderer; normalizePlan clones it into the plan.
  ExprPtr whenAst;
  std::vector<std::string> effects; // ordered debit/credit names
};

struct ParticipantView {
  std::string name, role, org; // org = "" when not declared
  std::vector<std::string> capabilities;
  // Late-binding policy (Trust lane, T1). binding = "" => fixed (no policy);
  // "to_be_bound" => bound at realization time, governed by the fields below.
  std::string binding;                   // "" | "to_be_bound"
  std::vector<std::string> bindRuntimes; // allowed runtime/backend families
  std::string bindMinAssurance;          // "" | "A1".."A4"
  bool isFlexible() const { return binding == "to_be_bound"; }
};

// A declared topology policy: the org pair permitted to coordinate, plus an
// optional role each org's actors must take ("" = unconstrained).
struct OrgPolicy {
  std::string orgA, orgB;
  std::string roleA, roleB;
};

struct ProcedureView {
  std::string name;
  std::optional<std::string> trigger;
  std::string version =
      "0.1.0"; // DSL/semantic version; default when not declared
  // The declared procedure-level instance key: the input the coordination
  // declares as its identity, independent of any ledger effect. Empty when the
  // procedure declares none (the key is then derived from effects).
  std::optional<std::string> instanceKey;
  std::vector<std::pair<std::string, std::string>> inputs; // (name, type)
  std::vector<ParticipantView> participants;
  std::vector<OrgPolicy>
      allowedOrgPairs; // topology policy (pairs + optional per-org roles)
  std::vector<ComputeView> computes;
  std::vector<EntryView> entries;
  // Obligations (L1 v0.2 O1, ): empty for every current spec, which keeps
  // their view / coordination-plan / hash byte-identical (omit-when-empty).
  std::vector<ObligationView> obligations;
  bool balanced = false;

  // Attestation policies (oracle S1, ): the M-of-N oracle-consensus policy
  // declared on an `evidence` input. Empty for the vast majority of specs (no
  // attestation declared), which keeps their rendered spec byte-identical.
  std::vector<AttestationPolicy> attestations;

  // 1-based source START line per construct, parallel to
  // inputs/computes/entries/ participants (0 when unknown) — the frontend
  // attaches FileLineColLoc/FusedLoc to every op (). Additive: it feeds the
  // spec's sourceMap ( WP1d /  F3) without changing the existing fields
  // other consumers read. assertLine is the `assert balanced` line (0 if none).
  std::vector<int> inputLines, computeLines, entryLines, participantLines,
      allowLines, attestationLines;
  int assertLine = 0;

  std::string pascalName() const;
};

// pascalCase is declared in Neutrino/StrCase.h (included above) so
// spec-consuming renderers can use it without View.h; re-declared availability
// here keeps existing View.h callers unchanged.

// The procedure named `name` in `module`, or a null ProcedureOp if none. The
// CLI tools resolve the scenario's target procedure with this before building a
// view (last declaration wins, matching the previous in-tool lookup). Pair with
// viewOf.
ProcedureOp findProcedure(mlir::ModuleOp module, llvm::StringRef name);

// The module's procedure without a scenario to name it — last declaration wins,
// matching findProcedure's rule. Used by scenario-free targets
// (--target=capability-spec, D2/). Null ProcedureOp when the module
// declares none.
ProcedureOp defaultProcedure(mlir::ModuleOp module);

ProcedureView viewOf(ProcedureOp proc);
// The GUARANTEED choreography: unconditional legs only (a guarded leg  is
// omitted — it fires conditionally).
std::vector<std::string> eventChain(const ProcedureView &view);
// The CONCRETE choreography for one scenario: a guarded leg's event is included
// iff its predicate holds for `env` (numeric input + computed values), so the
// realized/equivalence event chain matches what the backends actually emit.
// Used by realize() and neutrino-equiv.
std::vector<std::string>
eventChain(const ProcedureView &view,
           const std::map<std::string, long long> &env);

// A declared input type that maps to an integer (money/decimal/number/...).
// Single source of truth for "is this numeric" across backends + validation.
bool isNumericType(llvm::StringRef ty);

} // namespace neutrino

#endif // NEUTRINO_VIEW_H
