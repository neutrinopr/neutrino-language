//===- SpecLegality.cpp - in-process spec/target-profile legality gate ----===//
//
// The C++ twin of scripts/gates/check_spec_legality.py (M5 WP4/), wired
// into neutrino-gen by WP6/ so a render fails closed BEFORE dispatch when
// the spec's targetRequirements are illegal for the target profile. The two
// implementations must agree byte-for-byte on accept/reject; a parity self-test
// pins that. Keep this in lockstep with the Python gate's check() — same
// bad_input checks, same advisory-waiver rule, same messages.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SpecLegality.h"

#include <algorithm>
#include <set>
#include <string>

using namespace llvm;

namespace neutrino {

namespace {

Diagnostic diag(std::string code, std::string message,
                std::string severity = "error") {
  return Diagnostic{std::move(severity), std::move(code), std::move(message)};
}

// A JSON array of strings (mirrors the Python _str_list).
bool isStrList(const json::Value *v) {
  const json::Array *a = v ? v->getAsArray() : nullptr;
  if (!a)
    return false;
  for (const json::Value &e : *a)
    if (!e.getAsString())
      return false;
  return true;
}

// A {line, column} integer span (mirrors the Python _is_span).
bool isSpan(const json::Value *v) {
  const json::Object *o = v ? v->getAsObject() : nullptr;
  if (!o || o->size() != 2)
    return false;
  auto line = o->getInteger("line");
  auto col = o->getInteger("column");
  return line && col;
}

int srcLine(const json::Value *source) {
  const json::Object *o = source ? source->getAsObject() : nullptr;
  if (!o)
    return 0;
  return (int)o->getInteger("line").value_or(0);
}

} // namespace

std::vector<Diagnostic> checkSpecLegality(const json::Object &spec,
                                          const json::Object &profile,
                                          StringRef expectedTarget) {
  std::vector<Diagnostic> out;

  const json::Object *tr = spec.getObject("targetRequirements");
  const json::Array *reqs = tr ? tr->getArray("requirements") : nullptr;
  const json::Value *supportedV = profile.get("supportedFeatures");
  const json::Value *unsupportedV = profile.get("unsupportedConstructs");
  Optional<StringRef> fallback = profile.getString("fallbackPolicy");

  // FAIL CLOSED on malformed input — the pre-render gate must never crash and
  // never silently coerce a schema-invalid piece. Shape validation is the
  // validators' job; the gate checks just enough to match safely, mirrored
  // from check_spec_legality.py.
  if (!reqs)
    return {diag(
        "legality.bad_input",
        "spec.targetRequirements.requirements is missing or not an array")};
  if (!isStrList(supportedV))
    return {diag("legality.bad_input",
                 "profile.supportedFeatures must be an array of strings")};
  if (!isStrList(unsupportedV))
    return {diag("legality.bad_input",
                 "profile.unsupportedConstructs must be an array of strings")};

  std::set<std::string> supported, unsupported;
  for (const json::Value &e : *supportedV->getAsArray())
    supported.insert(e.getAsString()->str());
  for (const json::Value &e : *unsupportedV->getAsArray())
    unsupported.insert(e.getAsString()->str());

  std::string profileId = profile.getString("profileId").value_or("").str();

  for (const json::Value &rv : *reqs) {
    const json::Object *r = rv.getAsObject();
    Optional<StringRef> feature = r ? r->getString("feature") : None;
    Optional<StringRef> primitive = r ? r->getString("primitive") : None;
    Optional<StringRef> level = r ? r->getString("requirement") : None;
    const json::Value *source = r ? r->get("source") : nullptr;
    bool levelOk = level && (*level == "required" || *level == "optional");
    bool sourceOk = !source || source->getAsNull() || isSpan(source);
    if (!(r && feature && primitive && levelOk && sourceOk)) {
      out.push_back(
          diag("legality.bad_input", "a spec requirement record is malformed"));
      continue;
    }
    if (supported.count(feature->str()))
      continue;
    bool explicitUnsup = unsupported.count(feature->str()) > 0;
    std::string src = source && isSpan(source)
                          ? (" [line " + std::to_string(srcLine(source)) + "]")
                          : "";
    // An OPTIONAL requirement may be waived when the profile's fallback is
    // advisory.
    if (*level == "optional" && fallback && *fallback == "advisory" &&
        !explicitUnsup) {
      out.push_back(diag("legality.advisory",
                         "optional feature '" + feature->str() + "' (" +
                             primitive->str() +
                             ") is unmet; allowed by advisory fallback" + src,
                         "warning"));
      continue;
    }
    std::string reason =
        explicitUnsup ? "explicitly unsupported by" : "not supported by";
    out.push_back(diag("legality.unsupported_feature",
                       level->str() + " feature '" + feature->str() + "' (" +
                           primitive->str() + ") is " + reason +
                           " target profile '" + profileId + "'" + src));
  }

  // Target sanity: a solidity profile must not gate a postgres render, and vice
  // versa.
  if (!expectedTarget.empty()) {
    Optional<StringRef> govern = profile.getString("target");
    if (!govern || *govern != expectedTarget)
      out.push_back(diag("legality.target_mismatch",
                         "profile governs target '" +
                             (govern ? govern->str() : std::string("")) +
                             "', not '" + expectedTarget.str() + "'"));
  }

  // Root-cause ordering (): earliest source line first, then code (feature
  // is in the message).
  std::stable_sort(
      out.begin(), out.end(),
      [](const Diagnostic &a, const Diagnostic &b) { return a.code < b.code; });
  return out;
}

bool specIsLegal(const std::vector<Diagnostic> &diags) {
  for (const Diagnostic &d : diags)
    if (d.severity == "error")
      return false;
  return true;
}

} // namespace neutrino
