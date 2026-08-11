#ifndef NEUTRINO_EXPR_H
#define NEUTRINO_EXPR_H

#include "Neutrino/ValueModel.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace neutrino {

// A compute expression compiler. The same expression is parsed ONCE and typed
// into a shared AST that lowers to Solidity and SQL (and evaluates in C++) so
// every backend computes identical values and no renderer re-parses. Integer
// minor units, non-negative operands; `/` is integer division; round(x,k)==x
// today. Each node carries the value dtype it resolves to; `typeExpr` infers it
// and rejects unsupported constructs (see docs/language/EXPRESSION_MODEL.md).
struct ExprNode {
  enum Kind { Num, Var, Bin, Call, Cmp } kind;
  long long num = 0;
  std::string name; // Var name / Call callee / Cmp operator ("<","<=","==",...)
  char op = 0;      // Bin operator
  std::unique_ptr<ExprNode> lhs, rhs;
  std::vector<std::unique_ptr<ExprNode>> args;
  // The value dtype this node resolves to. Set by
  // typeExpr: a numeric literal is Decimal, a Var takes its declared category,
  // a Bin/round result is the numeric join of its operands.
  ValueCategory dtype = ValueCategory::Extension;
};
using ExprPtr = std::unique_ptr<ExprNode>;

struct ExprError : std::runtime_error {
  // Stable machine-readable diagnostic code (dotted, e.g. "expr.unsupported",
  // "expr.type"), mirroring ScenarioError so a consumer never has to scrape the
  // code out of the message text. Defaults to the family code "expr.invalid".
  std::string code;
  explicit ExprError(const std::string &m)
      : std::runtime_error(m), code("expr.invalid") {}
  ExprError(std::string code, const std::string &m)
      : std::runtime_error(m), code(std::move(code)) {}
};

ExprPtr parseExpr(llvm::StringRef s);

// A deep copy of a typed AST (the nodes own their children by unique_ptr, so
// the tree is not copyable by value). Used to carry an owned expression into
// the target-neutral CoordinationPlan without a shared_ptr ().
ExprPtr cloneExpr(const ExprNode &n);

// Lossless canonical serialization of a typed expression. This is the shared
// wire form used when an already-typed expression crosses a compiler waist;
// consumers reconstruct it with `exprFromJson` and never parse source text.
llvm::json::Value exprToJson(const ExprNode &n);

// Reconstruct a typed AST from its canonical-spec JSON serialization — the
// shared inverse of GenSpec's `exprToJson`. Every renderer that consumes the
// spec (both the PostgreSQL and Solidity renderers reuse THIS reconstruction,
// not their own) rebuilds the AST from the spec and lowers it via
// toSql/toSolidity, so it never re-parses raw expression text (`parseExpr`) —
// the spec is the source of truth. Callers should re-run `typeExpr` to verify
// (not trust) the carried dtypes. Throws ExprError (code `spec.ast`) on a
// malformed node.
ExprPtr exprFromJson(const llvm::json::Value &v);

// Infer + attach the dtype of every node. `env` maps each referenced variable
// name to its declared value category. Rejects
// unsupported constructs with a coded ExprError: code `expr.unsupported` (a
// function other than round, or a bad round arity) and `expr.type` (a governed
// non-numeric operand in arithmetic, or a non-literal round scale). An
// Extension-typed variable is unconstrained (ADR D5), preserving today's
// open-vocabulary behavior. Idempotent; call once when building the shared AST.
// See docs/language/EXPRESSION_MODEL.md for the full spec + extension process.
void typeExpr(ExprNode &n, const std::map<std::string, ValueCategory> &env);

long long evalExpr(const ExprNode &n,
                   const std::map<std::string, long long> &env);

// --- Conditional guards -----------------------------------------------------
//
// A GUARD is a boolean predicate that conditionally gates an effect (a leg
// posts iff the guard holds). A guard is a single comparison `<lhs> <op> <rhs>`
// (op in < <= > >= == !=) whose operands are NUMERIC value expressions
// (money/decimal). A comparison is a `Cmp` node and is DELIBERATELY NOT a
// value: it is only valid at the top of a guard, never as a compute value or an
// arithmetic operand — so the value model stays closed (no Boolean value type).
// That "predicate only in a guard" rule is enforced mechanically on BOTH sides:
// `parseExpr`/`typeExpr` (value context) reject a `Cmp`, and
// `parseGuard`/`typeGuard` (guard context) require the top node to be a `Cmp`.
// See docs/language/EXPRESSION_MODEL.md.

// Parse a guard predicate (a single top-level comparison). Throws ExprError.
ExprPtr parseGuard(llvm::StringRef s);

// Type a guard: the top node must be a `Cmp`, both operands numeric (money/
// decimal) or Extension. Rejects a non-comparison top or a non-numeric operand
// with `expr.type`. `env` is the same value-category map as `typeExpr`.
void typeGuard(ExprNode &n, const std::map<std::string, ValueCategory> &env);

// Evaluate a guard to its boolean truth over integer minor units (reference
// evaluator: the single source of truth for whether the guarded effect fires).
bool evalGuard(const ExprNode &n, const std::map<std::string, long long> &env);

// Resolver maps a variable name to its target-language reference (default:
// identity).
using Resolver = std::function<std::string(llvm::StringRef)>;
#ifndef NEUTRINO_CORE_ONLY
std::string toSolidity(const ExprNode &n, Resolver r = nullptr);
std::string toSql(const ExprNode &n, Resolver r = nullptr);
#endif

// Render a guard predicate to a target boolean expression (== lowers to SQL
// `=`,
// != to `<>`; Solidity uses == / !=). Throws if `n` is not a `Cmp`.
#ifndef NEUTRINO_CORE_ONLY
std::string guardToSolidity(const ExprNode &n, Resolver r = nullptr);
std::string guardToSql(const ExprNode &n, Resolver r = nullptr);
#endif

// --- Expression CATEGORY at a lowering position () ---------------------
//
// The value/predicate split above is a property of the POSITION an expression
// was projected for, not of the node that landed there: a compute value lowers
// through toSql/toSolidity, a guard condition through guardToSql/
// guardToSolidity. When a projection hands a typed AST to a target lowering it
// must therefore also hand over WHICH of the two positions it came from, or the
// lowering has to guess — and guessing from the node shape is exactly what
// would silently turn a comparison into a value.
//
// `ExprCategory` is that carried fact. It is target-neutral, closed, and always
// PROJECTED from an already-finalized fact (e.g. a posting's
// FinalizedPostingGuardKind), never inferred. Because it is carried rather than
// inferred, BOTH refusals survive: a comparison projected as a Value still
// fails `expr.type` in the value emitter, and a non-comparison projected as a
// Predicate still fails in the guard emitter.
enum class ExprCategory { Value = 0, Predicate = 1 };

// A finalized expression paired with the category of the position it was
// projected for. Backends carry this, not a bare `const ExprNode *`, so the
// category cannot be lost between projection and lowering.
struct CategorizedExpr {
  const ExprNode *node = nullptr;
  ExprCategory category = ExprCategory::Value;
};

std::vector<std::string> exprVars(const ExprNode &n);

} // namespace neutrino

#endif // NEUTRINO_EXPR_H
