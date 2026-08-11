// SPDX-License-Identifier: Apache-2.0
//===- spec_contract_smoke.cpp - link-smoke for the NeutrinoSpecContract leaf () -----===//
//
// Proves the capability-spec contract leaf is usable STANDALONE: this executable links ONLY
// `NeutrinoSpecContract` (see CMakeLists.txt) — not NeutrinoEmit, NeutrinoAnalysis, or the MLIR
// dialect. If the carve were leaky (a leaf source pulled a renderer / ProcedureView / dialect
// symbol), this would fail to LINK. It exercises the frozen contract surface: the value model, the
// stable hash, and the typed expression AST rebuilt from spec JSON + lowered (no re-parse).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Attestation.h"
#include "Neutrino/Expr.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/Lifecycle.h"
#include "Neutrino/ValueModel.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <map>
#include <string>
#include <vector>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "spec-contract-smoke: %s\n", msg);
  return 1;
}

int main() {
  // value model ()
  if (classifyValueType("money") != ValueCategory::Money)
    return fail("value model: money misclassified");
  if (!isNumericCategory(classifyValueType("decimal")))
    return fail("value model: decimal not numeric");

  // stable hash (JsonUtil)
  if (sha256Hex("neutrino-spec-contract").size() != 64)
    return fail("hash: sha256Hex length");

  // typed expression contract (): rebuild an AST from spec JSON, type it, lower it via the shared
  // lowerer — no parseExpr (the spec is the source of truth).
  llvm::Expected<llvm::json::Value> j = llvm::json::parse(
      R"({"kind":"bin","op":"+","lhs":{"kind":"var","name":"a"},"rhs":{"kind":"num","num":1}})");
  if (!j)
    return fail("expr: json parse");
  ExprPtr e = exprFromJson(*j);
  if (!e)
    return fail("expr: exprFromJson");
  std::map<std::string, ValueCategory> env{{"a", ValueCategory::Money}};
  typeExpr(*e, env);
  if (toSql(*e).empty() || toSolidity(*e).empty())
    return fail("expr: lowering empty");

  // [] the value/predicate CATEGORY split is a closed contract of this
  // leaf, and BOTH of its refusals must keep biting after the Solidity guard
  // lowering was repointed at the predicate emitter. A projection that
  // mislabels a leaf must fail loudly rather than silently render ill-typed
  // target code.
  llvm::Expected<llvm::json::Value> cj = llvm::json::parse(
      R"({"kind":"cmp","op":"==","lhs":{"kind":"var","name":"a"},"rhs":{"kind":"num","num":1}})");
  if (!cj)
    return fail("expr: guard json parse");
  ExprPtr cmp = exprFromJson(*cj);
  if (!cmp)
    return fail("expr: guard exprFromJson");
  typeGuard(*cmp, env);
  // (a) predicate position: the comparison lowers to a target boolean.
  if (guardToSolidity(*cmp) != "a == 1")
    return fail("guard: predicate lowering");
  if (guardToSql(*cmp) != "a = 1")
    return fail("guard: SQL predicate lowering");
  // (b) predicate-as-VALUE still refuses with the exact typed diagnostic.
  bool refusedValue = false;
  try {
    (void)toSolidity(*cmp);
  } catch (const ExprError &error) {
    refusedValue = error.code == "expr.type" &&
                   std::string(error.what()) ==
                       "a comparison predicate is not a value expression";
  }
  if (!refusedValue)
    return fail("guard: a comparison in a VALUE position no longer refuses");
  // (c) and the mirror: a value expression in a PREDICATE position refuses too,
  // so the fix cannot be abused to smuggle arbitrary expressions into a guard.
  bool refusedPredicate = false;
  try {
    (void)guardToSolidity(*e);
  } catch (const ExprError &) {
    refusedPredicate = true;
  }
  if (!refusedPredicate)
    return fail("guard: a value in a PREDICATE position no longer refuses");

  // lifecycle CONTRACT () — Lifecycle.h must be View.h-free (): including + using it here,
  // while the exe links ONLY the leaf, pins that the header pulls no ProcedureView/dialect symbol.
  llvm::Expected<llvm::json::Value> lj = llvm::json::parse(
      R"({"lifecycle":{"initialState":"INITIAL","transitions":[{"name":"COMMIT","from":"a","to":"b","effects":["post"]}]}})");
  if (!lj)
    return fail("lifecycle: json parse");
  LifecycleModel m = lifecycleModelFromSpec(*lj->getAsObject());
  if (m.operationsWithEffect("post").empty())
    return fail("lifecycle: post op not found");

  // attestation-policy CONTRACT (oracle S1, ) — also leaf, View.h-free. A
  // valid policy passes validation, serializes, and round-trips through the spec
  // shape (attestationPoliciesFromSpec), the same reconstruction the downstream
  //  renderers use.
  AttestationPolicy p;
  p.input = "delivery_proof";
  p.quorum = 2;
  p.observerSet = "delivery_oracles";
  // declared observer-set trust metadata (oracle S6, ) round-trips too.
  p.assurance = "A3";
  p.independence = "independent";
  p.canonicalization = "exact";
  p.fallback = "abort";
  if (!validateAttestationPolicy(p).empty())
    return fail("attest: valid policy rejected");
  llvm::json::Object spec{
      {"attestations", llvm::json::Array{attestationPolicyJson(p)}}};
  std::vector<AttestationPolicy> back = attestationPoliciesFromSpec(spec);
  if (back.size() != 1 || back[0].input != "delivery_proof" ||
      back[0].quorum != 2 || back[0].observerSet != "delivery_oracles" ||
      back[0].assurance != "A3" || back[0].independence != "independent" ||
      back[0].canonicalization != "exact" || back[0].fallback != "abort")
    return fail("attest: round-trip mismatch");

  // the trust metadata is OPTIONAL: an undeclared ("") tier/posture stays valid.
  AttestationPolicy undeclared = p;
  undeclared.assurance = "";
  undeclared.independence = "";
  if (!validateAttestationPolicy(undeclared).empty())
    return fail("attest: undeclared assurance/independence wrongly rejected");

  // fail-closed: each rejected shape returns a non-empty reason.
  AttestationPolicy bad = p;
  bad.quorum = 0;
  if (validateAttestationPolicy(bad).empty())
    return fail("attest: non-positive quorum not rejected");
  bad = p;
  bad.observerSet = "";
  if (validateAttestationPolicy(bad).empty())
    return fail("attest: missing observer-set not rejected");
  bad = p;
  bad.canonicalization = "vibes";
  if (validateAttestationPolicy(bad).empty())
    return fail("attest: unsupported canonicalization not rejected");
  bad = p;
  bad.fallback = "panic";
  if (validateAttestationPolicy(bad).empty())
    return fail("attest: unsupported fallback not rejected");
  bad = p;
  bad.assurance = "A9";
  if (validateAttestationPolicy(bad).empty())
    return fail("attest: unsupported assurance tier not rejected");
  bad = p;
  bad.independence = "solo";
  if (validateAttestationPolicy(bad).empty())
    return fail("attest: unsupported independence posture not rejected");

  puts("spec-contract-smoke OK (leaf links standalone: value model + hash + "
       "typed expr + lifecycle + attestation policy)");
  return 0;
}
