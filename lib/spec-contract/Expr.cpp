#include "Neutrino/Expr.h"

#include "llvm/ADT/StringExtras.h"
#include "llvm/Support/ErrorHandling.h"

#include <cctype>
#include <limits>

using namespace neutrino;

namespace {

std::vector<std::string> tokenize(llvm::StringRef s) {
  std::vector<std::string> toks;
  size_t i = 0;
  while (i < s.size()) {
    char c = s[i];
    if (isspace((unsigned char)c)) {
      ++i;
    } else if (isdigit((unsigned char)c)) {
      size_t j = i;
      while (j < s.size() && isdigit((unsigned char)s[j]))
        ++j;
      toks.push_back(s.substr(i, j - i).str());
      i = j;
    } else if (isalpha((unsigned char)c) || c == '_') {
      size_t j = i;
      while (j < s.size() && (isalnum((unsigned char)s[j]) || s[j] == '_'))
        ++j;
      toks.push_back(s.substr(i, j - i).str());
      i = j;
    } else if (llvm::StringRef("+-*/(),").contains(c)) {
      toks.push_back(std::string(1, c));
      ++i;
    } else if (llvm::StringRef("<>=!").contains(c)) {
      // Comparison operator (guard predicates only): < <= > >= == != . The
      // two-char forms and == / != use a trailing '='; bare '=' and '!' are not
      // operators (only == and !=), so they fail closed.
      if (i + 1 < s.size() && s[i + 1] == '=') {
        toks.push_back(s.substr(i, 2).str());
        i += 2;
      } else if (c == '<' || c == '>') {
        toks.push_back(std::string(1, c));
        ++i;
      } else {
        throw ExprError(std::string("unexpected character in expression: ") +
                        c);
      }
    } else {
      throw ExprError(std::string("unexpected character in expression: ") + c);
    }
  }
  return toks;
}

class Parser {
public:
  explicit Parser(std::vector<std::string> toks) : toks(std::move(toks)) {}

  ExprPtr parse() {
    ExprPtr n = expr();
    if (pos != toks.size())
      throw ExprError("trailing tokens in expression");
    return n;
  }

  // A guard is a single top-level comparison: `<value> <cmp-op> <value>`. The
  // operands are ordinary value expressions (no comparison inside them), so a
  // comparison can appear ONLY here, never as a value (enforced again in
  // typeExpr for the spec-ingestion path).
  ExprPtr parseGuardTop() {
    ExprPtr l = expr();
    const std::string *p = peek();
    if (!p || !isCmpOp(*p)) {
      // A bare accepted(<input>) is a valid boolean guard predicate ();
      // any other bare expression is not a guard.
      if (l && l->kind == ExprNode::Call && l->name == "accepted") {
        if (pos != toks.size())
          throw ExprError("trailing tokens in guard");
        return l;
      }
      throw ExprError("a `when` guard must be a comparison "
                      "(<, <=, >, >=, ==, !=) or accepted(<evidence-input>)");
    }
    std::string op = next();
    auto n = std::make_unique<ExprNode>();
    n->kind = ExprNode::Cmp;
    n->name = op;
    n->lhs = std::move(l);
    n->rhs = expr();
    if (pos != toks.size())
      throw ExprError("trailing tokens in guard");
    return n;
  }

private:
  static bool isCmpOp(const std::string &t) {
    return t == "<" || t == "<=" || t == ">" || t == ">=" || t == "==" ||
           t == "!=";
  }

  std::vector<std::string> toks;
  size_t pos = 0;

  const std::string *peek() { return pos < toks.size() ? &toks[pos] : nullptr; }
  std::string next() { return toks[pos++]; }
  bool isOp(const char *o) {
    const std::string *p = peek();
    return p && *p == o;
  }

  ExprPtr expr() {
    ExprPtr n = term();
    while (isOp("+") || isOp("-")) {
      char op = next()[0];
      auto b = std::make_unique<ExprNode>();
      b->kind = ExprNode::Bin;
      b->op = op;
      b->lhs = std::move(n);
      b->rhs = term();
      n = std::move(b);
    }
    return n;
  }

  ExprPtr term() {
    ExprPtr n = factor();
    while (isOp("*") || isOp("/")) {
      char op = next()[0];
      auto b = std::make_unique<ExprNode>();
      b->kind = ExprNode::Bin;
      b->op = op;
      b->lhs = std::move(n);
      b->rhs = factor();
      n = std::move(b);
    }
    return n;
  }

  ExprPtr factor() {
    const std::string *p = peek();
    if (!p)
      throw ExprError("unexpected end of expression");
    std::string t = next();
    if (t == "(") {
      ExprPtr n = expr();
      if (peek() == nullptr || next() != ")")
        throw ExprError("missing ')'");
      return n;
    }
    if (isdigit((unsigned char)t[0])) {
      auto n = std::make_unique<ExprNode>();
      n->kind = ExprNode::Num;
      n->num = std::stoll(t);
      return n;
    }
    if (isalpha((unsigned char)t[0]) || t[0] == '_') {
      if (peek() && *peek() == "(") {
        next(); // consume '('
        auto n = std::make_unique<ExprNode>();
        n->kind = ExprNode::Call;
        n->name = t;
        if (!(peek() && *peek() == ")")) {
          n->args.push_back(expr());
          while (peek() && *peek() == ",") {
            next();
            n->args.push_back(expr());
          }
        }
        if (peek() == nullptr || next() != ")")
          throw ExprError("missing ')' in call");
        return n;
      }
      auto n = std::make_unique<ExprNode>();
      n->kind = ExprNode::Var;
      n->name = t;
      return n;
    }
    throw ExprError("unexpected token: " + t);
  }
};

const ExprNode &unwrapRound(const ExprNode &n) {
  if (n.args.empty())
    throw ExprError("round() needs at least one argument");
  return *n.args[0];
}

#ifndef NEUTRINO_CORE_ONLY
std::string emit(const ExprNode &n, const Resolver &r) {
  switch (n.kind) {
  case ExprNode::Num:
    return std::to_string(n.num);
  case ExprNode::Var:
    return r ? r(n.name) : n.name;
  case ExprNode::Bin:
    return std::string("(") + emit(*n.lhs, r) + " " + n.op + " " +
           emit(*n.rhs, r) + ")";
  case ExprNode::Call:
    if (n.name == "round")
      return emit(unwrapRound(n), r);
    throw ExprError("unsupported function: " + n.name);
  case ExprNode::Cmp:
    // A comparison is a predicate, not a value; it is rendered only at the top
    // of a guard (guardToSql/guardToSolidity), never inlined as a value.
    throw ExprError("expr.type",
                    "a comparison predicate is not a value expression");
  }
  throw ExprError("bad node");
}
#endif

} // namespace

ExprPtr neutrino::cloneExpr(const ExprNode &n) {
  auto c = std::make_unique<ExprNode>();
  c->kind = n.kind;
  c->num = n.num;
  c->name = n.name;
  c->op = n.op;
  c->dtype = n.dtype;
  if (n.lhs)
    c->lhs = cloneExpr(*n.lhs);
  if (n.rhs)
    c->rhs = cloneExpr(*n.rhs);
  for (const auto &a : n.args)
    c->args.push_back(cloneExpr(*a));
  return c;
}

ExprPtr neutrino::parseExpr(llvm::StringRef s) {
  return Parser(tokenize(s)).parse();
}

ExprPtr neutrino::parseGuard(llvm::StringRef s) {
  return Parser(tokenize(s)).parseGuardTop();
}

llvm::json::Value neutrino::exprToJson(const ExprNode &n) {
  llvm::json::Object o;
  o["dtype"] = categoryName(n.dtype).str();
  switch (n.kind) {
  case ExprNode::Num:
    o["kind"] = "num";
    o["num"] = n.num;
    break;
  case ExprNode::Var:
    o["kind"] = "var";
    o["name"] = n.name;
    break;
  case ExprNode::Bin:
    o["kind"] = "bin";
    o["op"] = std::string(1, n.op);
    o["lhs"] = exprToJson(*n.lhs);
    o["rhs"] = exprToJson(*n.rhs);
    break;
  case ExprNode::Call: {
    o["kind"] = "call";
    o["name"] = n.name;
    llvm::json::Array args;
    for (const auto &a : n.args)
      args.push_back(exprToJson(*a));
    o["args"] = std::move(args);
    break;
  }
  case ExprNode::Cmp:
    o["kind"] = "cmp";
    o["op"] = n.name;
    o["lhs"] = exprToJson(*n.lhs);
    o["rhs"] = exprToJson(*n.rhs);
    break;
  }
  return llvm::json::Value(std::move(o));
}

ExprPtr neutrino::exprFromJson(const llvm::json::Value &v) {
  const llvm::json::Object *o = v.getAsObject();
  if (!o)
    throw ExprError("spec.ast", "expression node is not an object");
  auto n = std::make_unique<ExprNode>();
  n->dtype = classifyValueType(o->getString("dtype").value_or("extension"));
  llvm::StringRef kind = o->getString("kind").value_or("");
  if (kind == "num") {
    n->kind = ExprNode::Num;
    n->num = o->getInteger("num").value_or(0);
  } else if (kind == "var") {
    n->kind = ExprNode::Var;
    n->name = o->getString("name").value_or("").str();
  } else if (kind == "bin") {
    n->kind = ExprNode::Bin;
    llvm::StringRef op = o->getString("op").value_or("");
    if (op.size() != 1)
      throw ExprError("spec.ast", "bin node op must be a single character");
    n->op = op[0];
    const llvm::json::Value *lhs = o->get("lhs"), *rhs = o->get("rhs");
    if (!lhs || !rhs)
      throw ExprError("spec.ast", "bin node needs lhs and rhs");
    n->lhs = exprFromJson(*lhs);
    n->rhs = exprFromJson(*rhs);
  } else if (kind == "call") {
    n->kind = ExprNode::Call;
    n->name = o->getString("name").value_or("").str();
    if (const llvm::json::Array *args = o->getArray("args"))
      for (const llvm::json::Value &a : *args)
        n->args.push_back(exprFromJson(a));
  } else if (kind == "cmp") {
    // A guard comparison (). Op is a 1-2 char comparison; operands are
    // value nodes. typeGuard re-validates that operands are numeric.
    n->kind = ExprNode::Cmp;
    n->name = o->getString("op").value_or("").str();
    if (n->name != "<" && n->name != "<=" && n->name != ">" &&
        n->name != ">=" && n->name != "==" && n->name != "!=")
      throw ExprError("spec.ast", "cmp node has an invalid operator");
    const llvm::json::Value *lhs = o->get("lhs"), *rhs = o->get("rhs");
    if (!lhs || !rhs)
      throw ExprError("spec.ast", "cmp node needs lhs and rhs");
    n->lhs = exprFromJson(*lhs);
    n->rhs = exprFromJson(*rhs);
  } else {
    throw ExprError("spec.ast", "unknown expression node kind");
  }
  return n;
}

void neutrino::typeExpr(ExprNode &n,
                        const std::map<std::string, ValueCategory> &env) {
  switch (n.kind) {
  case ExprNode::Num:
    // A numeric literal is an integer in the decimal minor-units domain.
    n.dtype = ValueCategory::Decimal;
    return;
  case ExprNode::Var: {
    // A variable takes its declared category; an unknown/extension name is
    // unconstrained (ADR D5) and does not constrain arithmetic.
    auto it = env.find(n.name);
    n.dtype = it != env.end() ? it->second : ValueCategory::Extension;
    return;
  }
  case ExprNode::Bin: {
    typeExpr(*n.lhs, env);
    typeExpr(*n.rhs, env);
    for (const ExprNode *side : {n.lhs.get(), n.rhs.get()}) {
      // A GOVERNED non-numeric operand (party/currency/evidence/string) in
      // arithmetic is a type error; Extension is unconstrained.
      if (isCanonicalCategory(side->dtype) && !isNumericCategory(side->dtype))
        throw ExprError("expr.type",
                        std::string("arithmetic operand must be a numeric "
                                    "(money/decimal) value, but a ") +
                            categoryName(side->dtype).str() + " value is used");
    }
    // Numeric join: money-typed arithmetic stays in money minor units.
    n.dtype = (n.lhs->dtype == ValueCategory::Money ||
               n.rhs->dtype == ValueCategory::Money)
                  ? ValueCategory::Money
                  : ValueCategory::Decimal;
    return;
  }
  case ExprNode::Call:
    if (n.name == "accepted")
      // accepted() is a quorum-acceptance PREDICATE (): valid only at the
      // top of a `when` guard (typeGuard), never as a value / arithmetic
      // operand / compute — the value model stays closed (no Boolean value
      // type).
      throw ExprError("expr.type",
                      "accepted() is a quorum-acceptance predicate, valid only "
                      "inside a `when` guard, not as a value");
    if (n.name != "round")
      throw ExprError(
          "expr.unsupported",
          "unsupported function '" + n.name +
              "': a new expression construct must ship with Solidity, SQL, "
              "reference-evaluator, and equivalence-fixture support "
              "(docs/language/EXPRESSION_MODEL.md)");
    // round(x) or round(x, k) only. Fail closed on any other arity so an
    // unsupported call shape cannot be silently reduced to its first argument
    // (emit/evalExpr unwrap args[0] and ignore the rest).
    if (n.args.size() != 1 && n.args.size() != 2)
      throw ExprError(
          "expr.unsupported",
          "round expects 1 or 2 arguments (round(x) or round(x, k)), got " +
              std::to_string(n.args.size()) +
              " (docs/language/EXPRESSION_MODEL.md)");
    for (auto &a : n.args)
      typeExpr(*a, env);
    // The optional scale k selects rounding precision, so it must be a constant
    // integer literal (e.g. round(x, 2)). A computed/variable scale would be
    // silently discarded by the identity lowering, so reject it.
    if (n.args.size() == 2 && n.args[1]->kind != ExprNode::Num)
      throw ExprError("expr.type",
                      "round scale argument must be an integer literal (e.g. "
                      "round(x, 2)), not a computed value");
    // round operates on a numeric value: a governed non-numeric first argument
    // (party/currency/evidence/string) has no rounding meaning and would lower
    // to a type-mismatched backend (uint256 = <string>), so reject it here.
    // Extension is unconstrained (ADR D5), like a Bin operand.
    if (isCanonicalCategory(n.args[0]->dtype) &&
        !isNumericCategory(n.args[0]->dtype))
      throw ExprError("expr.type",
                      std::string("round argument must be a numeric "
                                  "(money/decimal) value, but a ") +
                          categoryName(n.args[0]->dtype).str() +
                          " value is used");
    // round(x, k) is identity today; it resolves to the first argument's dtype.
    n.dtype = n.args[0]->dtype;
    return;
  case ExprNode::Cmp:
    // A comparison is a predicate, not a value. It is valid ONLY at the top of
    // a guard (typeGuard); as a value / arithmetic operand / compute it is a
    // type error. This keeps the value model closed (no Boolean value type) and
    // is the mechanical "predicate only in a guard" enforcement on the
    // ingestion side (a hand-authored spec cannot smuggle a comparison into a
    // value).
    throw ExprError("expr.type",
                    "a comparison predicate (<, <=, >, >=, ==, !=) is only "
                    "valid inside a `when` guard, not as a value");
  }
  // Unreachable: typeExpr's switch is exhaustive over the ExprNode::Kind enum,
  // and every node carries a valid Kind — the parser sets it directly, and
  // exprFromJson validates the serialized `kind` before constructing the node
  // (throwing the user-facing `spec.ast` "unknown expression node kind"
  // otherwise). So a fall-through here is an internal invariant violation,
  // never reachable from user-controlled input — abort rather than raise a
  // recoverable diagnostic ().
  llvm::report_fatal_error("internal: typeExpr fell through its exhaustive "
                           "ExprNode::Kind switch");
}

void neutrino::typeGuard(ExprNode &n,
                         const std::map<std::string, ValueCategory> &env) {
  // accepted(<evidence-input>) (): a quorum-acceptance predicate. The
  // `attest` policy makes the input quorum-verified; an effect's `when` guard
  // depends on it via accepted(). Valid ONLY as a guard (typeExpr rejects it as
  // a value), and its argument MUST be a declared `evidence` input.
  if (n.kind == ExprNode::Call && n.name == "accepted") {
    if (n.args.size() != 1 || n.args[0]->kind != ExprNode::Var)
      throw ExprError("expr.type",
                      "accepted() takes a single evidence input, e.g. "
                      "accepted(delivery_proof)");
    const std::string &arg = n.args[0]->name;
    auto it = env.find(arg);
    if (it == env.end())
      throw ExprError("expr.type",
                      "accepted() references undeclared input '" + arg + "'");
    if (it->second != ValueCategory::Evidence)
      throw ExprError("expr.type",
                      "accepted() requires an `evidence` input, but '" + arg +
                          "' is a " + categoryName(it->second).str() +
                          " value");
    n.args[0]->dtype = it->second;
    return; // a predicate carries no value dtype
  }
  if (n.kind != ExprNode::Cmp)
    throw ExprError("expr.type",
                    "a `when` guard must be a comparison predicate "
                    "(<, <=, >, >=, ==, !=) or accepted(<evidence-input>)");
  // Operands are ordinary value expressions; type them and require numeric.
  typeExpr(*n.lhs, env);
  typeExpr(*n.rhs, env);
  for (const ExprNode *side : {n.lhs.get(), n.rhs.get()})
    if (isCanonicalCategory(side->dtype) && !isNumericCategory(side->dtype))
      throw ExprError("expr.type",
                      std::string("a guard operand must be a numeric "
                                  "(money/decimal) value, but a ") +
                          categoryName(side->dtype).str() + " value is used");
  // Every guard variable must resolve to a declared value. typeExpr classifies
  // an unknown Var as Extension (open vocabulary, ADR D5) rather than failing —
  // fine for computes, but a guard whose operand is UNDECLARED would otherwise
  // lower to a bare identifier in SQL/Solidity. The source front-end catches
  // this (computeDeps), but --from-spec is the frozen external contract and
  // must fail closed independently: reject an undeclared guard variable here so
  // a hand-authored / rehashed spec is refused before any backend is written.
  for (const std::string &vn : exprVars(n))
    if (!env.count(vn))
      throw ExprError("expr.type",
                      "guard references undeclared value '" + vn +
                          "' (not a declared input or computed value)");
}

namespace {
// The reference evaluator's SINGLE throw site (the  ratchet): every eval
// failure is funneled through here as a coded ExprError, so a semantic consumer
// (the coordination evaluator, ) turns it into a deterministic refusal.
[[noreturn]] void evalErr(const char *code, const std::string &msg) {
  throw ExprError(code, msg);
}

// CHECKED integer arithmetic (): a reference oracle must be TOTAL — signed
// overflow, division by zero, and the unrepresentable LLONG_MIN / -1 are
// undefined in raw C++, so each becomes a coded refusal (matching a backend's
// revert-on-overflow) rather than host/compiler-dependent behavior.
long long checkedBin(char op, long long a, long long b) {
  long long r;
  switch (op) {
  case '+':
    if (__builtin_add_overflow(a, b, &r))
      evalErr("expr.overflow", "addition overflow");
    return r;
  case '-':
    if (__builtin_sub_overflow(a, b, &r))
      evalErr("expr.overflow", "subtraction overflow");
    return r;
  case '*':
    if (__builtin_mul_overflow(a, b, &r))
      evalErr("expr.overflow", "multiplication overflow");
    return r;
  case '/':
    if (b == 0)
      evalErr("expr.divide_by_zero", "division by zero");
    if (a == std::numeric_limits<long long>::min() && b == -1)
      evalErr("expr.overflow", "division overflow");
    return a / b;
  }
  evalErr("expr.invalid", "bad operator");
}
} // namespace

long long neutrino::evalExpr(const ExprNode &n,
                             const std::map<std::string, long long> &env) {
  switch (n.kind) {
  case ExprNode::Num:
    return n.num;
  case ExprNode::Var: {
    auto it = env.find(n.name);
    if (it == env.end())
      evalErr("expr.unbound", "unbound variable: " + n.name);
    return it->second;
  }
  case ExprNode::Bin: {
    long long a = evalExpr(*n.lhs, env), b = evalExpr(*n.rhs, env);
    return checkedBin(n.op, a, b);
  }
  case ExprNode::Call:
    if (n.name == "round")
      return evalExpr(unwrapRound(n), env);
    evalErr("expr.unsupported", "unsupported function: " + n.name);
  case ExprNode::Cmp:
    evalErr("expr.type",
            "a comparison predicate is not a value; use evalGuard");
  }
  evalErr("expr.invalid", "bad node");
}

bool neutrino::evalGuard(const ExprNode &n,
                         const std::map<std::string, long long> &env) {
  // accepted(<input>) (): true iff the input's quorum accepted this
  // invocation. Acceptance is threaded into `env` under the "accepted:" prefix
  // (the reference evaluator seeds it from the transition's attestation map);
  // an absent entry is NOT accepted. A false accepted() guard SUPPRESSES its
  // leg (a balanced no-op), it does NOT refuse the transition.
  if (n.kind == ExprNode::Call && n.name == "accepted") {
    if (n.args.size() != 1 || n.args[0]->kind != ExprNode::Var)
      evalErr("expr.invalid", "malformed accepted() guard");
    auto it = env.find("accepted:" + n.args[0]->name);
    return it != env.end() && it->second != 0;
  }
  if (n.kind != ExprNode::Cmp)
    evalErr("expr.internal", "evalGuard on a non-comparison node");
  long long a = evalExpr(*n.lhs, env), b = evalExpr(*n.rhs, env);
  const std::string &op = n.name;
  if (op == "<")
    return a < b;
  if (op == "<=")
    return a <= b;
  if (op == ">")
    return a > b;
  if (op == ">=")
    return a >= b;
  if (op == "==")
    return a == b;
  if (op == "!=")
    return a != b;
  evalErr("expr.invalid", "bad comparison operator: " + op);
}

#ifndef NEUTRINO_CORE_ONLY
std::string neutrino::toSolidity(const ExprNode &n, Resolver r) {
  return emit(n, r);
}
std::string neutrino::toSql(const ExprNode &n, Resolver r) {
  return emit(n, r);
}
#endif

#ifndef NEUTRINO_CORE_ONLY
std::string neutrino::guardToSolidity(const ExprNode &n, Resolver r) {
  if (n.kind != ExprNode::Cmp)
    throw ExprError("guardToSolidity on a non-comparison node");
  // Solidity comparison operators match the source spelling directly.
  return emit(*n.lhs, r) + " " + n.name + " " + emit(*n.rhs, r);
}

std::string neutrino::guardToSql(const ExprNode &n, Resolver r) {
  if (n.kind != ExprNode::Cmp)
    throw ExprError("guardToSql on a non-comparison node");
  // SQL spells equality `=` and inequality `<>`; the ordering ops are
  // identical.
  std::string op = n.name == "==" ? "=" : (n.name == "!=" ? "<>" : n.name);
  return emit(*n.lhs, r) + " " + op + " " + emit(*n.rhs, r);
}
#endif

std::vector<std::string> neutrino::exprVars(const ExprNode &n) {
  std::vector<std::string> out;
  std::function<void(const ExprNode &)> walk = [&](const ExprNode &x) {
    if (x.kind == ExprNode::Var) {
      if (!llvm::is_contained(out, x.name))
        out.push_back(x.name);
    } else if (x.kind == ExprNode::Bin || x.kind == ExprNode::Cmp) {
      walk(*x.lhs);
      walk(*x.rhs);
    } else if (x.kind == ExprNode::Call) {
      for (auto &a : x.args)
        walk(*a);
    }
  };
  walk(n);
  return out;
}
