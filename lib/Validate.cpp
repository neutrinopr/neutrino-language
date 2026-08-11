//===- Validate.cpp - scenario vs. procedure validation -------------------===//
//
// Checks a scenario against the procedure it targets BEFORE any backend
// generation, so a missing or mistyped input fails fast with a clear message
// instead of producing a broken backend test.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Validate.h"

#include "Neutrino/Expr.h"
#include "Neutrino/ValueModel.h"

#include <cctype>
#include <set>
#include <string>

using namespace neutrino;

namespace {

// A 3-letter ISO-4217-shaped currency code, e.g. "EUR".
bool isCurrencyCode(const std::string &s) {
  if (s.size() != 3)
    return false;
  for (char c : s)
    if (!std::isupper(static_cast<unsigned char>(c)))
      return false;
  return true;
}

// A hashable reference: "<scheme>:<value>" with non-empty scheme and value
// (e.g. "sha256:ab12…", "ref:doc-7"). Rejects bare strings.
bool isEvidenceRef(const std::string &s) {
  auto colon = s.find(':');
  return colon != std::string::npos && colon > 0 && colon + 1 < s.size();
}

// Type-aware check of one scenario value against its declared `.neu` type.
// Phase 10 value model: money/decimal carried as integer minor units; party a
// non-empty string id; currency a 3-letter code; timestamp opaque (epoch int or
// ISO-8601 string); evidence a hashable reference string. Unknown types fall
// back to numeric-vs-string so the model stays open.
void checkTypedInput(const std::string &name, const std::string &ty,
                     const ScenarioInput &v, std::vector<std::string> &errs) {
  auto wantInteger = [&](const char *what) {
    if (!v.isInt)
      errs.push_back("input '" + name + "' must be an integer (" + ty + " " + what +
                     "), got a string");
  };
  auto wantString = [&](const char *what) {
    if (v.isInt)
      errs.push_back("input '" + name + "' must be a string (" + ty + " " + what +
                     "), got an integer");
  };

  if (ty == "money")
    wantInteger("is integer minor units");
  else if (ty == "decimal")
    wantInteger("is carried as a scaled integer");
  else if (ty == "number" || ty == "int" || ty == "integer" || ty == "uint")
    wantInteger("is an integer");
  else if (ty == "string")
    wantString("");
  else if (ty == "party") {
    wantString("a party id");
    if (!v.isInt && v.s.empty())
      errs.push_back("input '" + name + "' party id must be non-empty");
  } else if (ty == "currency") {
    wantString("a currency code");
    if (!v.isInt && !isCurrencyCode(v.s))
      errs.push_back("input '" + name + "' must be a 3-letter ISO currency code "
                     "(e.g. EUR), got '" + v.s + "'");
  } else if (ty == "timestamp" || ty == "time") {
    // opaque: an epoch integer or an ISO-8601 string is accepted as-is.
  } else if (ty == "evidence") {
    wantString("a hashable reference");
    if (!v.isInt && !isEvidenceRef(v.s))
      errs.push_back("input '" + name + "' evidence must be a hashable reference "
                     "like 'sha256:<hex>' or '<scheme>:<id>', got '" + v.s + "'");
  } else {
    // Unknown declared type: keep the open numeric-vs-string behavior.
    bool wantInt = isNumericType(ty);
    if (wantInt && !v.isInt)
      errs.push_back("input '" + name + "' should be an integer (" + ty + "), got a string");
    if (!wantInt && v.isInt)
      errs.push_back("input '" + name + "' should be a string (" + ty + "), got an integer");
  }
}

} // namespace

std::vector<std::string> neutrino::validateScenario(const ProcedureView &view,
                                                    const Scenario &scenario) {
  std::vector<std::string> errs;

  std::set<std::string> declared;
  for (const auto &p : view.inputs) {
    declared.insert(p.first);
    auto it = scenario.inputs.find(p.first);
    if (it == scenario.inputs.end()) {
      errs.push_back("missing scenario input '" + p.first + "' (declared as " + p.second + ")");
      continue;
    }
    checkTypedInput(p.first, p.second, it->second, errs);
  }

  for (const auto &kv : scenario.inputs)
    if (!declared.count(kv.first))
      errs.push_back("scenario input '" + kv.first +
                     "' is not declared by procedure '" + view.name + "'");

  std::set<std::string> computes;
  for (const auto &c : view.computes)
    computes.insert(c.name);
  for (const auto &kv : scenario.computed)
    if (!computes.count(kv.first))
      errs.push_back("expected computed value '" + kv.first +
                     "' is not a declared compute in '" + view.name + "'");

  // Every `accepted` key must name a declared attestation policy input ().
  // A key that names no policy is rejected, not silently treated as "accepted"
  // — so a mistyped policy name cannot quietly disable the suppress it
  // intended.
  std::set<std::string> policyInputs;
  for (const auto &a : view.attestations)
    policyInputs.insert(a.input);
  for (const auto &kv : scenario.accepted)
    if (!policyInputs.count(kv.first))
      errs.push_back("scenario 'accepted' key '" + kv.first +
                     "' is not a declared attestation policy input in '" +
                     view.name + "'");

  // Money non-negativity (M5 release-review, ). A `money` value is unsigned
  // minor units by the value model (ValueModel.h: Money = integer minor units)
  // — a settlement AMOUNT, never a signed balance. A negative money input or a
  // money-typed compute result (e.g. `net = gross_position - fee` driven below
  // zero) is an invalid money shape: the backends would render it as a
  // non-compiling `uint256 constant EXPECT_NET = -30` (Solidity) or invert a
  // PostgreSQL transfer direction — BROKEN artifacts instead of an honest
  // refusal. Reject here, before any renderer emits, grounded in the value
  // model rather than any renderer-local patch. NOTE: ledger NET deltas are
  // directional and legitimately signed (a debit leg is negative), so they are
  // intentionally NOT covered — this constrains money AMOUNTS (inputs) and
  // money-typed compute RESULTS only. A capability that genuinely needs signed
  // balances must model them as such, not smuggle them through a `money`
  // amount.
  for (const auto &p : view.inputs) {
    if (classifyValueType(p.second) != ValueCategory::Money)
      continue;
    auto it = scenario.inputs.find(p.first);
    if (it == scenario.inputs.end() || !it->second.isInt)
      continue; // absence / type already reported above
    if (it->second.i < 0)
      errs.push_back("money input '" + p.first + "' is negative (" +
                     std::to_string(it->second.i) +
                     "); a money amount is unsigned minor units and cannot be "
                     "negative");
  }
  // Compute RESULTS are checked against the value EVALUATED from the scenario
  // inputs — the source of truth. Evaluate each compute in declaration order,
  // seeding the env with the numeric inputs and feeding each result forward so
  // a dependent compute (e.g. `net` on `fee`) sees it.
  //
  // Two independent refusals share this evaluation:
  //   1. Money non-negativity (): a money-typed result that evaluates
  //      negative fails closed, whether or not expect.computed echoes it.
  //   2. Declared expect.computed agreement (): when the scenario declares
  //      an expect.computed[name], it MUST equal the evaluated result. The
  //      author-supplied echo is not copied into backends unchecked — a
  //      mis-declared non-negative value (e.g. subsidy: 999 for inputs that
  //      compute 10000) is scenario.invalid, same as an extra/unknown compute
  //      key above. Omitting a compute from expect.computed remains allowed
  //      (the existing contract does not require every compute to be echoed).
  std::map<std::string, long long> env;
  for (const auto &p : view.inputs) {
    auto in = scenario.inputs.find(p.first);
    if (in != scenario.inputs.end() && in->second.isInt)
      env[p.first] = in->second.i;
  }
  for (const auto &c : view.computes) {
    if (!c.ast)
      continue;
    long long val;
    try {
      val = evalExpr(*c.ast, env);
    } catch (const std::exception &) {
      continue; // an unbound / ill-formed compute is reported by typing
    }
    env[c.name] = val;
    // A money-typed compute result is unsigned minor units — a negative
    // evaluated result is the invalid money shape (), refused before
    // render. Evaluated, not the declared echo: a scenario that omits or
    // misstates the expectation still cannot slip a negative money result past
    // this gate.
    if (c.ast->dtype == ValueCategory::Money && val < 0)
      errs.push_back(
          "computed money value '" + c.name + "' evaluates to " +
          std::to_string(val) +
          " for these inputs; a money result cannot be negative before "
          "rendering — guard the compute so it cannot underflow, or model a "
          "signed balance explicitly");
    // Declared expect.computed must match evaluation ().
    auto declared = scenario.computed.find(c.name);
    if (declared != scenario.computed.end() && declared->second != val)
      errs.push_back(
          "declared computed value '" + c.name + "' = " +
          std::to_string(declared->second) + " does not match the value " +
          std::to_string(val) + " evaluated from the scenario inputs");
  }

  // Every leg's idempotency_key must reference a string-like input. The backends
  // hash/emit it as a string (Solidity `bytes(key)`, string-keyed events), so a
  // numeric key (e.g. money/number) or a computed value produces uncompilable
  // output. Fail here as a user-correctable diagnostic, before any backend reports
  // success on artifacts that will not build.
  auto inputType = [&](const std::string &n) -> const std::string * {
    for (const auto &p : view.inputs)
      if (p.first == n)
        return &p.second;
    return nullptr;
  };
  for (const auto &e : view.entries) {
    const auto &k = e.idempotency_key; // (isLit, text)
    if (k.first) {
      errs.push_back("leg '" + e.name +
                     "' idempotency_key must reference a string-like input, not a literal");
      continue;
    }
    if (computes.count(k.second)) {
      errs.push_back("leg '" + e.name + "' idempotency_key references computed value '" +
                     k.second + "', which is numeric; it must be a string-like input");
      continue;
    }
    const std::string *ty = inputType(k.second);
    if (!ty) {
      errs.push_back("leg '" + e.name + "' idempotency_key references unknown name '" +
                     k.second + "'");
      continue;
    }
    if (isNumericType(*ty))
      errs.push_back("leg '" + e.name + "' idempotency_key must reference a string-like "
                     "input (e.g. string/party), but '" + k.second + "' is declared " + *ty);
  }

  // All legs must share ONE idempotency_key — it is the single workflow key the
  // execution backends key every posting/event/test on. They derive it from the
  // first leg only (entries[0].idempotency_key), so a divergent per-leg key would
  // be silently collapsed to the first and the others ignored for coordination.
  // Reject that here instead.
  if (!view.entries.empty()) {
    const auto &first = view.entries[0].idempotency_key;
    for (const auto &e : view.entries) {
      const auto &k = e.idempotency_key;
      if (k.first != first.first || k.second != first.second)
        errs.push_back("leg '" + e.name + "' idempotency_key '" + k.second +
                       "' differs from leg '" + view.entries[0].name + "' key '" +
                       first.second + "'; all legs must share one workflow "
                       "idempotency_key (the backends key all coordination on it)");
    }
  }

  return errs;
}
