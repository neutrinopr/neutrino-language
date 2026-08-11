//===- SolidityEmit.cpp - shared Solidity-render helpers () -----------===//
//
// The type/escape/operand primitives shared by the coordination-contract and
// Foundry-harness renderers (extracted from GenSoliditySpec.cpp, ). Moved
// verbatim — output is byte-identical (the lit Solidity/oracle goldens prove
// it).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SolidityEmit.h"

#include "Neutrino/Expr.h"
#include "Neutrino/ValueModel.h"

#include "llvm/ADT/Twine.h"

#include <cctype>

using namespace llvm;

namespace neutrino {
namespace sol_detail {

std::string solType(StringRef ty) {
  // Explicit temporal inputs are caller-supplied integer instants/durations on
  // the EVM rail. They remain Extension in the target-neutral value model, but
  // the Solidity realization is a typed uint256 parameter so comparisons are
  // genuine value predicates; no implicit block clock is substituted.
  if (isTemporalType(ty))
    return "uint256";
  switch (classifyValueType(ty)) {
  case ValueCategory::Money:
  case ValueCategory::Decimal:
    return "uint256";
  default:
    return "string";
  }
}

std::string param(StringRef n, StringRef ty) {
  return solType(ty) == "uint256" ? ("uint256 " + n).str()
                                  : ("string calldata " + n).str();
}

std::string solString(StringRef t) {
  std::string out = "\"";
  for (char c : t) {
    if (c == '\\')
      out += "\\\\";
    else if (c == '"')
      out += "\\\"";
    else
      out += c;
  }
  out += "\"";
  return out;
}

bool isInt(StringRef t) {
  StringRef s = t;
  if (!s.empty() && s.front() == '-')
    s = s.drop_front();
  if (s.empty())
    return false;
  for (char c : s)
    if (!isdigit((unsigned char)c))
      return false;
  return true;
}

std::string uref(StringRef name) { return ("u_" + name).str(); }

std::string upper(StringRef s) {
  std::string out = s.str();
  for (char &c : out)
    c = (char)toupper((unsigned char)c);
  return out;
}

std::string contractStr(const json::Object &op) {
  bool lit = op.getString("kind").value_or("") == "literal";
  std::string v = op.getString("value").value_or("").str();
  return lit ? solString(v) : uref(v);
}

std::string contractUint(const json::Object &op) {
  bool lit = op.getString("kind").value_or("") == "literal";
  std::string v = op.getString("value").value_or("").str();
  if (lit && !isInt(v))
    throw ExprError(
        "spec.ast",
        "numeric operand expected for Solidity, got string literal " + v);
  return lit ? v : uref(v);
}

const json::Object &obj(const json::Value *v, const char *what) {
  const json::Object *o = v ? v->getAsObject() : nullptr;
  if (!o)
    throw ExprError("spec.ast",
                    std::string("capability-spec: missing/invalid ") + what);
  return *o;
}

} // namespace sol_detail
} // namespace neutrino
