//===- PlanLegality.cpp - the semantic realization-legality matcher -------===//
//
// The ONE plan matcher (): checkPlanLegality derives a verified plan's
// normalized semantic requirements + metrics (SemanticRequirements) and matches
// them against a SemanticProfile — the built-in reference evaluator profile or
// a file-backed target profile's `semanticProfile` block — failing closed
// BEFORE evaluator/lowering dispatch. Version is pinned to
// kSemanticProfileVersion (a distinct semantic-profile contract version, not
// the target-profile schema or tool version); a missing/unknown version is
// rejected first.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/PlanLegality.h"

#include "Neutrino/SemanticRequirements.h"
#include "Neutrino/VersionInfo.h"

#include <algorithm>
#include <climits>

using namespace llvm;

namespace neutrino {

namespace {
Diagnostic diag(std::string code, std::string message,
                std::string severity = "error") {
  return Diagnostic{std::move(severity), std::move(code), std::move(message)};
}
} // namespace

const std::set<std::string> &evaluatorSupportedFeatures() {
  // What  evaluateTransition ACTUALLY realizes, declared independently of
  // the registry so the drift self-test is non-vacuous:
  //   authorization:explicit                — the recorded authorization step
  //   effect:debit / effect:credit          — signed ledger deltas
  //   guard:conditional                     — evalGuard-gated legs
  //   invariant:balanced                    — the balance obligation
  //   attestation:quorum                    — attestation-gated legs
  //   terminal:success/aborted/contested    — the terminal projection + refusal
  //   replay:idempotent                     — the postedKeys idempotency guard
  //   time:explicit_input                   — a temporal input in the env,
  //   which
  //                                           the evaluator evaluates like any
  //                                           other explicit numeric input
  //   identity:explicit_instance_key        — a declared instance key resolved
  //                                           independently of any effect
  //   coordination:evidence_acceptance      — the zero-ledger evidence-only
  //                                           accept/reject/terminal path
  static const std::set<std::string> kEval = {
      "authorization:explicit",
      "effect:debit",
      "effect:credit",
      "guard:conditional",
      "invariant:balanced",
      "attestation:quorum",
      "terminal:success",
      "terminal:aborted",
      "terminal:contested",
      "replay:idempotent",
      "time:explicit_input",
      "identity:explicit_instance_key",
      "coordination:evidence_acceptance",
  };
  return kEval;
}

SemanticProfile referenceEvaluatorProfile() {
  SemanticProfile p;
  p.id = "reference.v3";
  p.versionPresent = true;
  p.version = kSemanticProfileVersion;
  p.features = evaluatorSupportedFeatures(); // INDEPENDENT support declaration
  p.limits = {INT_MAX, INT_MAX, INT_MAX, INT_MAX, INT_MAX, INT_MAX};
  return p;
}

SemanticProfile builtinSemanticProfile(StringRef target) {
  if (target == "coordination-trace" || target == "reference")
    return referenceEvaluatorProfile();
  SemanticProfile p;
  p.versionPresent = true;
  p.version = kSemanticProfileVersion;
  if (target == "solidity") {
    // On-chain: realizes the terminal:contested dispute shape and explicit
    // caller-supplied temporal inputs as uint256 values (never
    // block.timestamp), but remains gas-bounded by tight depth + step caps.
    p.id = "target.evm.v1";
    p.features = {"attestation:quorum",
                  "authorization:explicit",
                  "coordination:evidence_acceptance",
                  "effect:credit",
                  "effect:debit",
                  "guard:conditional",
                  "identity:explicit_instance_key",
                  "invariant:balanced",
                  "replay:idempotent",
                  "terminal:aborted",
                  "terminal:contested",
                  "terminal:success",
                  "time:explicit_input"};
    p.limits = {16, 32, 16, 8, 32, 64};
  } else if (target == "postgres") {
    // Relational settlement: no on-chain contested dispute; deeper/larger/
    // more-step plans; realizes explicit temporal inputs (SQL time/bigint).
    p.id = "target.postgres.v1";
    p.features = {"attestation:quorum",
                  "authorization:explicit",
                  "coordination:evidence_acceptance",
                  "effect:credit",
                  "effect:debit",
                  "guard:conditional",
                  "identity:explicit_instance_key",
                  "invariant:balanced",
                  "replay:idempotent",
                  "terminal:aborted",
                  "terminal:success",
                  "time:explicit_input"};
    p.limits = {32, 256, 64, 32, 128, 1024};
  } else {
    p.versionPresent = false; // unknown target -> matcher fails closed
    p.version = 0;
  }
  return p;
}

SemanticProfile semanticProfileFromJson(const json::Object &targetProfile) {
  SemanticProfile p;
  p.id = targetProfile.getString("profileId").value_or("").str();
  const json::Object *sp = targetProfile.getObject("semanticProfile");
  if (!sp)
    return p; // versionPresent stays false -> matcher fails closed
  if (Optional<int64_t> v = sp->getInteger("version")) {
    p.versionPresent = true;
    p.version = (int)*v;
  }
  if (const json::Array *feats = sp->getArray("features"))
    for (const json::Value &f : *feats)
      if (Optional<StringRef> s = f.getAsString())
        p.features.insert(s->str());
  if (const json::Object *lim = sp->getObject("limits")) {
    auto cap = [&](const char *k) {
      return (int)lim->getInteger(k).value_or(0);
    };
    p.limits.maxExpressionDepth = cap("maxExpressionDepth");
    p.limits.maxEffects = cap("maxEffects");
    p.limits.maxEffectGroups = cap("maxEffectGroups");
    p.limits.maxAttestations = cap("maxAttestations");
    p.limits.maxComputes = cap("maxComputes");
    p.limits.maxOperationSteps = cap("maxOperationSteps");
  }
  return p;
}

json::Value semanticProfileToJson(const SemanticProfile &profile) {
  json::Array feats;
  for (const std::string &f : profile.features) // std::set -> sorted
    feats.push_back(f);
  return json::Object{
      {"version", profile.version},
      {"features", std::move(feats)},
      {"limits",
       json::Object{{"maxExpressionDepth", profile.limits.maxExpressionDepth},
                    {"maxEffects", profile.limits.maxEffects},
                    {"maxEffectGroups", profile.limits.maxEffectGroups},
                    {"maxAttestations", profile.limits.maxAttestations},
                    {"maxComputes", profile.limits.maxComputes},
                    {"maxOperationSteps", profile.limits.maxOperationSteps}}}};
}

std::vector<Diagnostic> checkPlanLegality(const CoordinationPlan &plan,
                                          const SemanticProfile &profile) {
  // 1. Version pin — checked FIRST, fail closed before any matching. A missing
  // or unknown semantic-profile contract version is rejected before dispatch.
  if (!profile.versionPresent)
    return {diag("legality.unknown_profile_version",
                 "target '" + profile.id +
                     "' declares no semanticProfile.version")};
  if (profile.version != kSemanticProfileVersion)
    return {diag("legality.unknown_profile_version",
                 "target '" + profile.id + "' pins semantic profile version " +
                     std::to_string(profile.version) +
                     ", not the supported version " +
                     std::to_string(kSemanticProfileVersion))};

  std::vector<Diagnostic> out;
  const std::set<std::string> &registry = knownSemanticFeatures();
  PlanRequirements reqs = coordinationPlanRequirements(plan);

  // 2. Feature requirements: an unregistered feature is a drift bug (fail
  // closed); a registered-but-unadvertised feature is unsupported by this
  // realization.
  for (const SemanticRequirement &r : reqs.features) {
    if (!registry.count(r.feature)) {
      out.push_back(diag("legality.unknown_requirement",
                         "requirement '" + r.feature + "' (" + r.primitive +
                             ") is outside the closed semantic registry"));
      continue;
    }
    if (!profile.features.count(r.feature))
      out.push_back(diag("legality.unsupported_feature",
                         "required feature '" + r.feature + "' (" +
                             r.primitive + ") is not supported by target '" +
                             profile.id + "'"));
  }

  // 3. Numeric/resource limits.
  auto limit = [&](int usage, int cap, const char *what) {
    if (usage > cap)
      out.push_back(diag("legality.limit_exceeded",
                         std::string(what) + " " + std::to_string(usage) +
                             " exceeds target '" + profile.id + "' limit " +
                             std::to_string(cap)));
  };
  limit(reqs.metrics.expressionDepth, profile.limits.maxExpressionDepth,
        "expression depth");
  limit(reqs.metrics.effectCount, profile.limits.maxEffects, "effect count");
  limit(reqs.metrics.effectGroupCount, profile.limits.maxEffectGroups,
        "effect group count");
  limit(reqs.metrics.attestationCount, profile.limits.maxAttestations,
        "attestation count");
  limit(reqs.metrics.computeCount, profile.limits.maxComputes, "compute count");
  limit(reqs.metrics.operationSteps, profile.limits.maxOperationSteps,
        "operation steps");

  // Deterministic order: code, then message.
  std::stable_sort(out.begin(), out.end(),
                   [](const Diagnostic &a, const Diagnostic &b) {
                     if (a.code != b.code)
                       return a.code < b.code;
                     return a.message < b.message;
                   });
  return out;
}

bool planIsLegal(const std::vector<Diagnostic> &diags) {
  for (const Diagnostic &d : diags)
    if (d.severity == "error")
      return false;
  return true;
}

} // namespace neutrino
