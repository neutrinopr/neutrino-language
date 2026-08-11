#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/Attestation.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Expr.h"
#include "Neutrino/ExprAttr.h"
#include "Neutrino/ValueModel.h"
#include "Neutrino/Version.h"

#include "mlir/IR/Builders.h"
#include "mlir/IR/BuiltinAttributes.h"
#include "mlir/IR/DialectImplementation.h"
#include "mlir/IR/OpImplementation.h"
#include "mlir/IR/TypeUtilities.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/ADT/TypeSwitch.h"
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <utility>

using namespace mlir;
using namespace neutrino;

// Dialect definitions (generated).
#include "Neutrino/NeutrinoDialect.cpp.inc"

// Type definitions (generated).
#define GET_TYPEDEF_CLASSES
#include "Neutrino/NeutrinoTypes.cpp.inc"

// Attribute definitions (generated).
#define GET_ATTRDEF_CLASSES
#include "Neutrino/NeutrinoAttrs.cpp.inc"

// Op definitions (generated).
#define GET_OP_CLASSES
#include "Neutrino/NeutrinoOps.cpp.inc"

// ExprAttr structural verifier (): the closed grammar's shape — a leaf
// carries no children, a binary/comparison node exactly two, a call at least
// one. Typing (dtype inference) is enforced by the op verifiers that carry the
// value-category env; here we pin the structural invariants an attribute built
// from a hand-authored .mlir must satisfy.
mlir::LogicalResult
ExprAttr::verify(llvm::function_ref<mlir::InFlightDiagnostic()> emitError,
                 llvm::StringRef kind, llvm::StringRef dtype, int64_t num,
                 int64_t slot, llvm::StringRef name, llvm::StringRef binop,
                 llvm::ArrayRef<ExprAttr> children) {
  auto arity = [&](size_t n) -> bool { return children.size() == n; };
  // The dtype must be a CANONICAL category name (): categoryFromName maps
  // an unknown string to Extension, so the round-trip pins the closed
  // vocabulary and rejects a bogus/laundered dtype spelling at the IR boundary.
  if (categoryName(categoryFromName(dtype)) != dtype)
    return emitError() << "neutrino.expr dtype '" << dtype
                       << "' is not a canonical value category";
  // A var is SSA-bound by $slot (the bijection with the op's deps is proved by
  // the op verifier, which knows the deps); every other node has slot -1. The
  // per-node UNUSED fields must be canonical too, so one semantics has ONE
  // encoding (no laundering through an ignored field).
  if (kind != "var" && slot != -1)
    return emitError() << "neutrino.expr non-var node must have slot -1";
  if (kind != "cmp" && kind != "call" && !name.empty())
    return emitError() << "neutrino.expr " << kind << " must have empty name";
  if (kind != "bin" && !binop.empty())
    return emitError() << "neutrino.expr " << kind << " must have empty binop";
  if (kind != "num" && num != 0)
    return emitError() << "neutrino.expr " << kind << " must have num 0";
  if (kind == "num") {
    if (!arity(0))
      return emitError() << "neutrino.expr num takes no children";
  } else if (kind == "var") {
    if (!arity(0) || slot < 0)
      return emitError() << "neutrino.expr var needs a dep slot >= 0 and no "
                            "children";
  } else if (kind == "bin") {
    if (!arity(2) || binop.size() != 1 ||
        llvm::StringRef("+-*/").find(binop) == llvm::StringRef::npos)
      return emitError()
             << "neutrino.expr bin needs a +-*/ operator and two children";
  } else if (kind == "cmp") {
    static const char *kCmp[] = {"<", "<=", ">", ">=", "==", "!="};
    if (!arity(2) || !llvm::is_contained(kCmp, name))
      return emitError() << "neutrino.expr cmp needs a comparison operator and "
                            "two children";
  } else if (kind == "call") {
    if (children.empty() || name.empty())
      return emitError() << "neutrino.expr call needs a callee and >=1 arg";
  } else {
    return emitError() << "neutrino.expr unknown kind '" << kind << "'";
  }
  return mlir::success();
}

// Textual form: #neutrino.expr<KIND DTYPE NUM SLOT "NAME" "BINOP" [child, …]>.
// Children print via the FULL attribute form (#neutrino.expr<…>), so the array
// is unambiguously delimited by [ ] and the recursion round-trips.
void ExprAttr::print(mlir::AsmPrinter &p) const {
  p << "<" << getKind() << " " << getDtype() << " " << getNum() << " "
    << getSlot() << " \"" << getName() << "\" \"" << getBinop() << "\" [";
  llvm::interleaveComma(getChildren(), p,
                        [&](ExprAttr c) { p.printAttribute(c); });
  p << "]>";
}

mlir::Attribute ExprAttr::parse(mlir::AsmParser &p, mlir::Type) {
  std::string kind, dtype, name, binop;
  int64_t num = 0, slot = 0;
  if (p.parseLess() || p.parseKeywordOrString(&kind) ||
      p.parseKeywordOrString(&dtype) || p.parseInteger(num) ||
      p.parseInteger(slot) || p.parseString(&name) || p.parseString(&binop) ||
      p.parseLSquare())
    return {};
  llvm::SmallVector<ExprAttr> children;
  if (failed(p.parseOptionalRSquare())) {
    do {
      ExprAttr child;
      if (p.parseAttribute(child))
        return {};
      children.push_back(child);
    } while (succeeded(p.parseOptionalComma()));
    if (p.parseRSquare())
      return {};
  }
  if (p.parseGreater())
    return {};
  return ExprAttr::getChecked(
      [&] { return p.emitError(p.getCurrentLocation()); }, p.getContext(), kind,
      dtype, num, slot, name, binop, children);
}

void NeutrinoDialect::initialize() {
  addTypes<
#define GET_TYPEDEF_LIST
#include "Neutrino/NeutrinoTypes.cpp.inc"
      >();
  addAttributes<
#define GET_ATTRDEF_LIST
#include "Neutrino/NeutrinoAttrs.cpp.inc"
      >();
  addOperations<
#define GET_OP_LIST
#include "Neutrino/NeutrinoOps.cpp.inc"
      >();
}

//===----------------------------------------------------------------------===//
// ProcedureOp custom verifier: the balanced invariant.
//===----------------------------------------------------------------------===//

// Identity of an operand by its defining op (matches the Python _operand_key).
static std::string operandKey(Value v) {
  Operation *def = v.getDefiningOp();
  if (auto c = dyn_cast_or_null<ConstOp>(def))
    return std::string("lit:") + c.getValue().str();
  if (auto in = dyn_cast_or_null<InputOp>(def))
    return std::string("ref:") + in.getSymName().str();
  if (auto cm = dyn_cast_or_null<ComputeOp>(def))
    return std::string("ref:") + cm.getSymName().str();
  return std::string("ssa");
}

LogicalResult ProcedureOp::verify() {
  // A declared version must be a real SemVer (MAJOR.MINOR.PATCH). Checked here
  // as well as in the frontend so a hand-written .mlir cannot fail open. Absent
  // version is fine (the default 0.1.0 is applied downstream in viewOf).
  if (StringAttr v = getVersionAttr())
    if (!isValidSemVer(v.getValue()))
      return emitOpError("[kernel.version.invalid] has an invalid version \"")
             << v.getValue()
             << "\": must be a semantic version MAJOR.MINOR.PATCH";

  Block &block = getBody().front();

  SmallVector<DebitOp> debits;
  SmallVector<CreditOp> credits;
  bool hasAssert = false;
  bool hasAttest = false;
  std::map<std::string, std::string> inputType; // name -> declared type
  for (Operation &op : block) {
    if (auto d = dyn_cast<DebitOp>(op))
      debits.push_back(d);
    else if (auto c = dyn_cast<CreditOp>(op))
      credits.push_back(c);
    else if (isa<AssertBalancedOp>(op))
      hasAssert = true;
    else if (isa<AttestOp>(op))
      hasAttest = true;
    else if (auto in = dyn_cast<InputOp>(op))
      inputType[in.getSymName().str()] = in.getTy().str();
  }

  // The idempotency-key input an effect references ("" when it keys on a
  // literal/const, which cannot bind an explicit instance key).
  auto idemRef = [](auto e) -> std::string {
    if (auto in =
            dyn_cast_or_null<InputOp>(e.getIdempotencyKey().getDefiningOp()))
      return in.getSymName().str();
    return "";
  };

  // Explicit instance-key declaration + effectless evidence-only legality,
  // mirrored from the coordination-plan normalization seam so a verified view
  // always normalizes (the capability-spec path re-normalizes it, cantFail).
  StringRef instanceKey =
      getInstanceKeyAttr() ? getInstanceKeyAttr().getValue() : StringRef();
  if (!instanceKey.empty()) {
    auto it = inputType.find(instanceKey.str());
    if (it == inputType.end())
      return emitOpError("[kernel.identity.instance_key] instance key '")
             << instanceKey << "' names no declared input";
    if (classifyValueType(it->second) != ValueCategory::String)
      return emitOpError("[kernel.identity.instance_key] instance key '")
             << instanceKey << "' has non-string type '" << it->second << "'";
    // Every effect must key on the declared instance — a ref to it. A literal
    // effect key (idemRef == "") or a ref to a different input is rejected, so
    // authored effect identity is never silently rewritten to the declared key.
    auto agrees = [&](auto e) -> LogicalResult {
      std::string r = idemRef(e);
      if (r != instanceKey.str())
        return e.emitOpError("[kernel.identity.instance_key] ambiguous "
                             "instance key — effect does not key on the "
                             "declared instance key '")
               << instanceKey << "' (effect key: "
               << (r.empty() ? "literal" : "ref '" + r + "'") << ")";
      return success();
    };
    for (auto e : debits)
      if (failed(agrees(e)))
        return failure();
    for (auto e : credits)
      if (failed(agrees(e)))
        return failure();
  }

  if (debits.empty() && credits.empty()) {
    // Effectless: a coordination only as an evidence-acceptance action (an
    // attestation policy + an explicit instance key); the lifecycle synthesizes
    // the success terminal. A keyless, attestation-less effectless procedure is
    // a legitimate (non-coordination) anchor-only spec — left lenient.
    if (hasAttest && instanceKey.empty())
      return emitOpError("[kernel.identity.evidence_only] evidence-only "
                         "coordination requires an explicit instance key");
    if (!hasAttest && !instanceKey.empty())
      return emitOpError("[kernel.identity.evidence_only] an effectless "
                         "coordination must declare an attestation/evidence "
                         "acceptance action");
    return success(); // moves no value, nothing to balance
  }

  if (!hasAssert)
    return emitOpError("[kernel.balance.assert_missing] moves value "
                       "(debit/credit) but does not "
                       "declare the 'assert_balanced' invariant");

  if (debits.empty() || credits.empty())
    return emitOpError("[kernel.balance.not_balanceable] declares "
                       "'assert_balanced' but is not balanceable: needs "
                       "at least one debit and one credit");

  // The (amount, currency) moved by debits must match the credits as a
  // multiset.
  std::multiset<std::pair<std::string, std::string>> dflow, cflow;
  for (auto e : debits)
    dflow.insert({operandKey(e.getAmount()), operandKey(e.getCurrency())});
  for (auto e : credits)
    cflow.insert({operandKey(e.getAmount()), operandKey(e.getCurrency())});
  if (dflow != cflow)
    return emitOpError("[kernel.balance.unbalanced] is not balanced: the "
                       "(amount, currency) moved by debits "
                       "does not match the credits");

  // Guarded-balance soundness (): the plain (amount, currency) multiset
  // above is GUARD-BLIND — it accepts a conditionally-unbalanced capability,
  // e.g. a debit `when C` whose matching credit is unconditional: under `!C`
  // the credit posts and the debit does not, so value is not conserved. Fail
  // closed unless each guarded leg balances under the SAME guard partition.
  // Conservative + sound (M5 release-review, /): a leg balances
  // only against a counterpart carrying the identical guard. The partition is
  // the guard's VERIFIED STRUCTURAL KEY ( P1), not source text — so it
  // agrees with the CoordinationPlan's partitioning (assemblePlan), and
  // whitespace-different-but-structurally-equal guards can't be split here
  // while text-identical-but-AST-different guards can't slip through. An
  // unguarded leg has the empty key "", so a one-sided guard is a mismatch.
  auto guardOf = [](auto e) -> std::string {
    ExprAttr g = e.getGuardAstAttr();
    if (!g)
      return "";
    std::vector<std::string> syms;
    for (Value d : e.getGuardDeps()) {
      Operation *def = d.getDefiningOp();
      if (auto in = dyn_cast_or_null<InputOp>(def))
        syms.push_back(in.getSymName().str());
      else if (auto c = dyn_cast_or_null<ComputeOp>(def))
        syms.push_back(c.getSymName().str());
      else
        syms.push_back("");
    }
    return canonicalGuardKey(toExprNode(g, syms).get());
  };
  // Only guards can make an (amount, currency)-matched procedure unbalanced, so
  // this only fires once a leg carries a `when`. Key legs by (guard, amount,
  // currency) and require the debit and credit multisets to match under it too.
  std::multiset<std::tuple<std::string, std::string, std::string>> dg, cg;
  for (auto e : debits)
    dg.insert(
        {guardOf(e), operandKey(e.getAmount()), operandKey(e.getCurrency())});
  for (auto e : credits)
    cg.insert(
        {guardOf(e), operandKey(e.getAmount()), operandKey(e.getCurrency())});
  if (dg != cg) {
    // Point the diagnostic at a specific offending leg (source context): a leg
    // whose (guard, amount, currency) has no matching counterpart on the other
    // side. Prefer a guarded leg so the message names the unbalanced guard.
    auto offending = [&](auto &legs, auto &self, auto &other) -> Operation * {
      for (auto e : legs) {
        auto key = std::make_tuple(guardOf(e), operandKey(e.getAmount()),
                                   operandKey(e.getCurrency()));
        if (self.count(key) > other.count(key) && !guardOf(e).empty())
          return e.getOperation();
      }
      return nullptr;
    };
    Operation *leg = offending(debits, dg, cg);
    if (!leg)
      leg = offending(credits, cg, dg);
    Operation *at = leg ? leg : getOperation();
    return at->emitOpError(
        "[kernel.balance.unbalanced] guarded legs are not balanced under the "
        "same guard: a `when`-guarded leg has no matching-guarded counterpart, "
        "so "
        "value is not conserved on the partition where the guard does not hold "
        "(assert_balanced requires each guarded leg to be balanced by a leg "
        "with "
        "the identical guard). Refused: guarded-balance beyond identical-guard "
        "pairing is not statically provable and is not accepted ().");
  }

  return success();
}

namespace {
// The resolved value nature of an SSA operand on the numeric/non-numeric axis —
// which is what the value model and the backends actually key on.
// `Unconstrained` means the value carries no governed type (an extension-typed
// input, a literal, or a compute over only such values), so it is never forced
// into a category.
enum class Nature { Numeric, GovernedNonNumeric, Unconstrained };

// Resolve an operand's nature, transitively through computes so a governed
// non-numeric input cannot be laundered into a numeric slot via an arithmetic
// compute (e.g. `input raw : string; compute amt = raw * 1; debit ... amount =
// %amt`). A compute is governed-non-numeric if any dependency is
// (contamination), else numeric if any dependency is numeric, else
// unconstrained. `visited` guards the (acyclic) SSA walk.
Nature resolveNature(Value v, llvm::SmallPtrSetImpl<Operation *> &visited) {
  Operation *def = v.getDefiningOp();
  if (auto in = dyn_cast_or_null<InputOp>(def)) {
    ValueCategory c = classifyValueType(in.getTy());
    if (!isCanonicalCategory(c))
      return Nature::Unconstrained; // extension type: accepted verbatim
    return isNumericCategory(c) ? Nature::Numeric : Nature::GovernedNonNumeric;
  }
  if (auto cm = dyn_cast_or_null<ComputeOp>(def)) {
    if (!visited.insert(cm).second)
      return Nature::Unconstrained;
    bool anyNonNumeric = false, anyNumeric = false;
    for (Value d : cm.getDeps()) {
      switch (resolveNature(d, visited)) {
      case Nature::GovernedNonNumeric:
        anyNonNumeric = true;
        break;
      case Nature::Numeric:
        anyNumeric = true;
        break;
      case Nature::Unconstrained:
        break;
      }
    }
    if (anyNonNumeric)
      return Nature::GovernedNonNumeric;
    if (anyNumeric)
      return Nature::Numeric;
  }
  return Nature::Unconstrained; // ConstOp literal / anything else
}

std::string describeOperand(Value v) {
  Operation *def = v.getDefiningOp();
  if (auto in = dyn_cast_or_null<InputOp>(def))
    return "input '" + in.getSymName().str() + "' typed '" + in.getTy().str() +
           "'";
  if (auto cm = dyn_cast_or_null<ComputeOp>(def))
    return "compute '" + cm.getSymName().str() + "'";
  return "operand";
}

// A debit/credit operand should carry the value category its role requires —
// enforced on the numeric/non-numeric axis: an `amount` must be numeric
// (money/decimal), while `party` and `currency` must NOT be numeric (a party id
// / currency code is not a number — but it is legitimately carried as a
// `string`, which is why this checks the numeric axis rather than an exact
// category, so string-typed ids keep compiling).
//
// Fires only when the operand definitely resolves to the wrong side of that
// axis (governed types, transitively through computes). Extension-typed inputs
// and literals are unconstrained: the input type vocabulary is intentionally
// open (WP1a/, ADR D5). The diagnostic carries a machine-readable code and
// (via emitOpError) the source location.
LogicalResult verifyEntryOperand(Operation *op, Value v, StringRef role,
                                 bool requireNumeric) {
  llvm::SmallPtrSet<Operation *, 8> visited;
  Nature n = resolveNature(v, visited);
  if (n == Nature::Unconstrained)
    return success();
  bool numeric = n == Nature::Numeric;
  if (numeric == requireNumeric)
    return success();
  StringRef want = requireNumeric ? "a numeric (money/decimal)"
                                  : "a non-numeric (party / currency / string)";
  return op->emitOpError() << "[value_type.mismatch] " << role
                           << " operand must be " << want << " value, but "
                           << describeOperand(v) << " is "
                           << (numeric ? "numeric" : "governed non-numeric");
}

LogicalResult verifyEntry(Operation *op, Value party, Value amount,
                          Value currency) {
  if (failed(verifyEntryOperand(op, party, "party", /*requireNumeric=*/false)))
    return failure();
  if (failed(verifyEntryOperand(op, amount, "amount", /*requireNumeric=*/true)))
    return failure();
  if (failed(verifyEntryOperand(op, currency, "currency",
                                /*requireNumeric=*/false)))
    return failure();
  return success();
}

// The procedure-wide value-category env: every declared input's type + every
// compute's inferred result dtype. A guard may reference names beyond the
// entry's operands, so its typing needs the whole scope ().
std::map<std::string, ValueCategory> procEnv(Operation *op) {
  std::map<std::string, ValueCategory> env;
  Operation *proc = op->getParentOp();
  if (!proc)
    return env;
  for (Region &r : proc->getRegions())
    for (Block &b : r)
      for (Operation &o : b) {
        if (auto in = dyn_cast<InputOp>(o))
          env[in.getSymName().str()] = classifyValueType(in.getTy());
        else if (auto c = dyn_cast<ComputeOp>(o))
          env[c.getSymName().str()] = categoryFromName(c.getAst().getDtype());
      }
  return env;
}

// The symbol names of an op's dependency operands, positionally — the
// slot->name resolution the structured expression's var leaves bind through
// ().
llvm::SmallVector<std::string> depSymbols(ValueRange deps) {
  llvm::SmallVector<std::string> syms;
  for (Value d : deps) {
    Operation *def = d.getDefiningOp();
    if (auto in = dyn_cast_or_null<InputOp>(def))
      syms.push_back(in.getSymName().str());
    else if (auto c = dyn_cast_or_null<ComputeOp>(def))
      syms.push_back(c.getSymName().str());
    else
      syms.push_back("");
  }
  return syms;
}

// Prove the var-leaf <-> dependency-operand BIJECTION ( amendment 1): every
// var slot resolves to exactly one declared dependency, and every declared
// dependency is referenced — so a var cannot reference a value absent from the
// op's SSA deps, and no dep is dead. Deterministic in operand order.
LogicalResult verifyDepBijection(Operation *op, ExprAttr ast, ValueRange deps,
                                 llvm::StringRef what) {
  int64_t n = (int64_t)deps.size();
  // Each dependency must resolve to an input/compute SYMBOL, and no symbol may
  // repeat: a duplicated dep (two slots for one variable) would make canonical
  // identity operand-layout-dependent, so it is rejected ( P2).
  llvm::SmallVector<std::string> syms = depSymbols(deps);
  std::set<std::string> seen;
  for (int64_t i = 0; i < n; ++i) {
    if (syms[i].empty())
      return op->emitOpError() << "[expr.slot] " << what << " dependency " << i
                               << " is not a declared input/compute value";
    if (!seen.insert(syms[i]).second)
      return op->emitOpError()
             << "[expr.slot] " << what << " declares dependency '" << syms[i]
             << "' more than once";
  }
  llvm::SmallVector<int64_t> slots;
  collectSlots(ast, slots);
  llvm::SmallVector<bool> used(n, false);
  for (int64_t s : slots) {
    if (s < 0 || s >= n)
      return op->emitOpError()
             << "[expr.slot] " << what << " var leaf references dep slot " << s
             << " but the op declares " << n << " dependenc"
             << (n == 1 ? "y" : "ies");
    used[s] = true;
  }
  for (int64_t i = 0; i < n; ++i)
    if (!used[i])
      return op->emitOpError()
             << "[expr.slot] " << what << " declares dependency " << i
             << " that no expression leaf uses";
  return success();
}

// Every node's CARRIED dtype must equal the freshly INFERRED category — so a
// hand-authored .mlir cannot mark a string/evidence var as `money` and have the
// IR trust the lie downstream ( P1). The attribute and the (re-typed) node
// share a structure, so walk them in lockstep.
LogicalResult verifyCarriedDtypes(Operation *op, ExprAttr a, const ExprNode &n,
                                  llvm::StringRef what) {
  if (a.getDtype() != categoryName(n.dtype))
    return op->emitOpError()
           << "[expr.type] " << what << " node carries dtype '" << a.getDtype()
           << "' but its inferred category is '" << categoryName(n.dtype)
           << "'";
  llvm::ArrayRef<ExprAttr> kids = a.getChildren();
  if (n.lhs && !kids.empty() &&
      failed(verifyCarriedDtypes(op, kids[0], *n.lhs, what)))
    return failure();
  if (n.rhs && kids.size() > 1 &&
      failed(verifyCarriedDtypes(op, kids[1], *n.rhs, what)))
    return failure();
  for (size_t i = 0; i < n.args.size() && i < kids.size(); ++i)
    if (failed(verifyCarriedDtypes(op, kids[i], *n.args[i], what)))
      return failure();
  return success();
}

// Type the structured expression carried by an op at IR-verify time ():
// prove the dep bijection, reconstruct the name-resolved ExprNode, and run the
// SAME inference the frontend used — so a hand-authored .mlir with an
// unbound/ill-typed arithmetic or guard fails closed here, before
// serialization. Surfaces the coded diagnostic via emitOpError (no new throw).
LogicalResult verifyTypedExpr(Operation *op, ExprAttr ast, ValueRange deps,
                              llvm::StringRef text, bool guard) {
  llvm::StringRef what = guard ? "guard" : "compute";
  if (failed(verifyDepBijection(op, ast, deps, what)))
    return failure();
  ExprPtr node = toExprNode(ast, depSymbols(deps));

  // The retained provenance TEXT ($expr/$guard) must parse to the SAME
  // structure as the semantic AST — otherwise the capability-spec's `expr`
  // bytes would say one thing while `ast` executes another ( P1).
  // Re-parsing here validates provenance only; consumers/renderers still never
  // re-parse.
  try {
    ExprPtr fromText = guard ? parseGuard(text) : parseExpr(text);
    if (canonicalGuardKey(fromText.get()) != canonicalGuardKey(node.get()))
      return op->emitOpError() << "[expr.provenance] " << what << " text '"
                               << text << "' does not match the structured ast";
  } catch (const ExprError &e) {
    return op->emitOpError() << "[" << e.code << "] " << what
                             << " provenance text does not parse: " << e.what();
  }

  std::map<std::string, ValueCategory> env = procEnv(op);
  try {
    if (guard)
      typeGuard(*node, env);
    else
      typeExpr(*node, env);
  } catch (const ExprError &e) {
    return op->emitOpError() << "[" << e.code << "] " << e.what();
  }
  // The node now carries INFERRED dtypes; prove they equal the CARRIED ones.
  return verifyCarriedDtypes(op, ast, *node, what);
}
} // namespace

LogicalResult ComputeOp::verify() {
  return verifyTypedExpr(*this, getAst(), getDeps(), getExpr(),
                         /*guard=*/false);
}

// The guard source text and the structured guard ast are BOTH-present-or-BOTH-
// absent ( P1): one without the other would leave the spec's `when.expr` or
// `when.ast` half-defined.
template <typename EntryT> LogicalResult verifyEntryOp(EntryT e) {
  if (failed(verifyEntry(e, e.getParty(), e.getAmount(), e.getCurrency())))
    return failure();
  bool hasText = (bool)e.getGuardAttr();
  bool hasAst = (bool)e.getGuardAstAttr();
  if (hasText != hasAst)
    return e.emitOpError()
           << "[expr.provenance] guard text and guard ast must be both present "
              "or both absent";
  if (hasAst)
    return verifyTypedExpr(e, e.getGuardAstAttr(), e.getGuardDeps(),
                           e.getGuardAttr().getValue(), /*guard=*/true);
  return success();
}

LogicalResult DebitOp::verify() { return verifyEntryOp(*this); }
LogicalResult CreditOp::verify() { return verifyEntryOp(*this); }

// Late-binding policy invariants. Enforced at the IR level so
// a hand-written .mlir fed to neutrino-opt/neutrino-gen cannot bypass the
// frontend checks and emit a binding policy with no authorized binder or an
// empty runtime allow-list. A fixed participant (no `binding`) carries no
// policy and is exempt.
LogicalResult ParticipantOp::verify() {
  StringAttr bindingAttr = getBindingAttr();
  bool flexible = bindingAttr && bindingAttr.getValue() == "to_be_bound";

  if (bindingAttr && bindingAttr.getValue() != "to_be_bound")
    return emitOpError(
               "[kernel.binding.invalid_mode] binding must be \"to_be_bound\" "
               "if set, got \"")
           << bindingAttr.getValue() << "\"";

  // bind_* policy is only meaningful on a to_be_bound participant.
  if (!flexible && (getBindRuntimes() || getBindMinAssuranceAttr()))
    return emitOpError("[kernel.binding.policy_without_flag] sets "
                       "bind_runtimes/bind_min_assurance without "
                       "binding = \"to_be_bound\"");

  if (flexible) {
    // A late-bound slot must name the org permitted to bind it (the authorized
    // binder); otherwise the emitted policy authorizes no actor to bind.
    if (!getOrgAttr())
      return emitOpError(
          "[kernel.binding.missing_binder] is binding = \"to_be_bound\" but "
          "declares no org (the authorized binder would be unspecified)");
    // bind_runtimes is the allow-list agents will enforce: require a non-empty
    // list of non-empty entries (fail closed on \"\"/whitespace).
    auto rt = getBindRuntimes();
    if (!rt || rt->empty())
      return emitOpError("[kernel.binding.missing_runtimes] is binding = "
                         "\"to_be_bound\" but declares no bind_runtimes");
    for (Attribute a : *rt)
      if (a.cast<StringAttr>().getValue().trim().empty())
        return emitOpError("[kernel.binding.empty_runtime] bind_runtimes "
                           "contains an empty runtime family");
  }

  if (StringAttr ma = getBindMinAssuranceAttr()) {
    StringRef v = ma.getValue();
    if (v != "A1" && v != "A2" && v != "A3" && v != "A4")
      return emitOpError(
                 "[kernel.binding.invalid_assurance] bind_min_assurance "
                 "must be one of A1/A2/A3/A4, got \"")
             << v << "\"";
  }

  return success();
}

// Attestation-policy invariants (oracle S1, ). Enforced at the IR level so
// a hand-written .mlir fed to neutrino-opt/neutrino-gen cannot bypass the
// frontend checks and emit a policy that fires on a partial or unconstrained
// quorum. The self-contained shape checks live here; cross-op checks (the
// referenced input exists and is evidence-typed) are the frontend's, which has
// the input table.
LogicalResult AttestOp::verify() {
  if (getQuorum() <= 0)
    return emitOpError("[kernel.attest.invalid_quorum] quorum must be a "
                       "positive integer (the M-of-N threshold), got ")
           << getQuorum();
  if (getObserverSet().trim().empty())
    return emitOpError("[kernel.attest.missing_observer_set] declares no "
                       "observer-set reference");
  StringRef canon = getCanonicalization();
  if (!llvm::is_contained(attestationCanonicalizationModes(), canon))
    return emitOpError("[kernel.attest.invalid_canonicalization] "
                       "canonicalization must be one of exact/median, got \"")
           << canon << "\"";
  StringRef fb = getFallback();
  if (!llvm::is_contained(attestationFallbacks(), fb))
    return emitOpError("[kernel.attest.invalid_fallback] fallback must be one "
                       "of abort/escalate, got \"")
           << fb << "\"";
  // Optional observer-set trust metadata (oracle S6, ): when declared, must
  // be from the accepted vocabulary. Absent = undeclared (the security spec
  // surfaces it as an advisory), so only a present-but-bad value fails closed.
  if (auto tier = getAssuranceAttr();
      tier && !llvm::is_contained(attestationAssuranceTiers(), tier.getValue()))
    return emitOpError("[kernel.attest.invalid_assurance] observer-set "
                       "assurance must be one of A1/A2/A3/A4, got \"")
           << tier.getValue() << "\"";
  if (auto ind = getIndependenceAttr();
      ind &&
      !llvm::is_contained(attestationIndependenceModes(), ind.getValue()))
    return emitOpError("[kernel.attest.invalid_independence] observer-set "
                       "independence must be one of independent/correlated, "
                       "got \"")
           << ind.getValue() << "\"";
  return success();
}

// Obligation structural verifier (L1 v0.2 O1, ). Purely structural: every
// reference is resolved by op IDENTITY within the enclosing procedure — no
// domain vocabulary, no target/backend name, no CoordinationPlan lowering or
// backend activation. The obligation's lifecycle stays distinct from effect
// execution: it AUTHORIZES an ordered set of value effects (debit/credit) but
// is never itself an effect, and an effect is never accepted as an obligation.
LogicalResult ObligationOp::verify() {
  Operation *proc = (*this)->getParentOp();

  // ALL declarations of a sym_name in the enclosing procedure. A reference must
  // resolve to EXACTLY ONE compatible declaration: ProcedureOp::verify does NOT
  // enforce sym_name uniqueness, so a duplicate name or a cross-kind collision
  // would otherwise resolve order-dependently — that is refused
  // (ambiguous_ref), never silently "first declaration wins".
  auto declarations = [&](StringRef name) -> SmallVector<Operation *> {
    SmallVector<Operation *> out;
    if (proc)
      for (Region &r : proc->getRegions())
        for (Block &b : r)
          for (Operation &o : b)
            if (auto sym = o.getAttrOfType<StringAttr>("sym_name"))
              if (sym.getValue() == name)
                out.push_back(&o);
    return out;
  };
  // Resolve a participant reference to exactly one ParticipantOp, under `code`
  // for the empty/unresolved case. Ambiguity (>1 declaration of the name)
  // always fails as ambiguous_ref.
  auto requireParticipant = [&](const char *code, StringRef role,
                                StringRef name) -> LogicalResult {
    if (name.trim().empty())
      return emitOpError("[kernel.obligation.")
             << code << "] declares no " << role;
    SmallVector<Operation *> decls = declarations(name);
    if (decls.size() > 1)
      return emitOpError("[kernel.obligation.ambiguous_ref] ")
             << role << " '" << name << "' resolves to " << decls.size()
             << " declarations of that name (order-dependent)";
    if (decls.empty() || !isa<ParticipantOp>(decls[0]))
      return emitOpError("[kernel.obligation.")
             << code << "] " << role << " '" << name
             << "' does not resolve to a declared participant";
    return success();
  };

  // (0) the obligation's own identity is non-empty (its lifecycle is distinct
  // from its effects, so it must be nameable for reference / coordination-plan
  // identity).
  if (getSymName().trim().empty())
    return emitOpError(
        "[kernel.obligation.identity] declares an empty identity (sym_name)");

  // (1) obligor + (2) scope: each resolves to exactly one declared participant.
  if (failed(requireParticipant("obligor", "obligor", getObligor())))
    return failure();
  if (failed(requireParticipant("scope", "beneficiary", getBeneficiary())))
    return failure();
  if (failed(requireParticipant("scope", "authority", getAuthority())))
    return failure();

  // (3) activation predicate: when text + when_ast both present, then the SAME
  //  structured-expression contract compute/guards use (dep bijection +
  // typing + provenance). A missing predicate, or an ill-typed/unbound one,
  // fails closed here.
  bool hasText = (bool)getWhenAttr();
  bool hasAst = (bool)getWhenAstAttr();
  if (!hasText || !hasAst)
    return emitOpError("[kernel.obligation.predicate] activation predicate is "
                       "missing (when text and when_ast must both be present)");
  if (failed(verifyTypedExpr(*this, getWhenAstAttr(), getWhenDeps(),
                             getWhenAttr().getValue(), /*guard=*/true)))
    return failure();

  // (4) authorized effects: a non-empty, duplicate-free, ORDERED set of
  // references that each resolve to a declared VALUE EFFECT (debit/credit) — a
  // participant, another obligation, or any non-effect is rejected, keeping the
  // obligation/effect boundary structural.
  ArrayAttr effects = getEffects();
  if (effects.empty())
    return emitOpError(
        "[kernel.obligation.effects_empty] authorizes no value effects");
  std::set<StringRef> seen;
  for (Attribute a : effects) {
    StringRef name = a.cast<StringAttr>().getValue();
    if (!seen.insert(name).second)
      return emitOpError(
                 "[kernel.obligation.duplicate_effect] declares effect '")
             << name << "' more than once";
    SmallVector<Operation *> decls = declarations(name);
    if (decls.size() > 1)
      return emitOpError("[kernel.obligation.ambiguous_ref] effect '")
             << name << "' resolves to " << decls.size()
             << " declarations of that name (order-dependent)";
    if (decls.empty())
      return emitOpError("[kernel.obligation.not_an_effect] effect '")
             << name
             << "' does not resolve to a declared value effect (absent from "
                "the "
                "procedure)";
    if (!isa<DebitOp, CreditOp>(decls[0]))
      return emitOpError("[kernel.obligation.not_an_effect] effect '")
             << name << "' resolves to '" << decls[0]->getName().getStringRef()
             << "', which is not a value effect (debit/credit)";
  }

  return success();
}
