#ifndef NEUTRINO_PLAN_LEGALITY_H
#define NEUTRINO_PLAN_LEGALITY_H

// The semantic realization-legality gate (): the ONE matcher that decides
// whether a verified CoordinationPlan is legal for a given realization — the
// reference evaluator OR a rigid lowering — BEFORE execution/rendering. It is
// the plan-level companion to the  spec-legality gate (SpecLegality.h),
// which stays as-is for the OPEN spec-feature namespace; this gate governs the
// CLOSED normalized-semantic-requirement registry (SemanticRequirements.h).
//
// One requirement derivation (coordinationPlanRequirements), one matcher
// (checkPlanLegality), MANY profile sources: a file-backed target profile's
// `semanticProfile` block (semanticProfileFromJson) or the built-in reference
// evaluator profile (referenceEvaluatorProfile). There is deliberately NO
// separate evaluator legality path — the evaluator matches through this same
// contract, so a plan the evaluator would refuse is refused the same way a
// renderer refuses it.

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Diagnostics.h"

#include "llvm/Support/JSON.h"

#include <set>
#include <string>
#include <vector>

namespace neutrino {

// A target's declared semantic realization capability. Built identically from a
// file-backed profile or the built-in reference, and matched by the one
// matcher. Numeric caps model parameterized limits (expression depth,
// effect/group/ attestation/compute counts); the supported terminal SHAPES and
// the other semantic forms are features.
struct SemanticProfileLimits {
  int maxExpressionDepth = 0;
  int maxEffects = 0;
  int maxEffectGroups = 0;
  int maxAttestations = 0;
  int maxComputes = 0;
  int maxOperationSteps = 0; // genuine compute-cost / bounded-step cap
};

struct SemanticProfile {
  std::string id; // e.g. "reference.v1", "target.evm.v1"
  bool versionPresent =
      false;       // false => the profile declares no contract version
  int version = 0; // must equal kSemanticProfileVersion to match
  std::set<std::string> features; // supported closed-registry semantic features
  SemanticProfileLimits limits;
};

// The reference evaluator's INDEPENDENTLY-declared semantic support: exactly
// the features 's evaluateTransition implements. Deliberately NOT aliased
// to knownSemanticFeatures() — a drift self-test compares the two, so a
// registry addition the evaluator has not yet implemented is caught (and, until
// the evaluator claims it here, a coordination plan needing it is refused
// legality.unsupported_feature). This is the support declaration the drift
// guard audits; it must not alias the registry it is meant to audit.
const std::set<std::string> &evaluatorSupportedFeatures();

// The built-in reference evaluator profile: its features are the
// evaluator's declared support (above), with unbounded limits. A future
// coordination-plan node whose feature is not registered is refused
// (legality.unknown_requirement); a registered feature the evaluator has not
// claimed is refused (legality.unsupported_feature) — the evaluator cannot
// silently realize an unsupported construct.
SemanticProfile referenceEvaluatorProfile();

// The built-in, AUTHORITATIVE SemanticProfile for a realization target
// ("coordination-trace"/"reference", "solidity", "postgres"): the DEFAULT the
// coordination-plan legality gate matches against when no --profile is
// supplied, so semantic legality is MANDATORY — a no-profile render still
// refuses an unsupported coordination plan, never silently meaning
// "unbounded/all semantics". An unknown target yields versionPresent == false
// (the matcher fails closed). The committed file profiles' `semanticProfile`
// block must equal this builtin (pinned by a drift self-test via
// --dump-semantic-profile).
SemanticProfile builtinSemanticProfile(llvm::StringRef target);

// Build a SemanticProfile from a file-backed target profile's optional
// `semanticProfile` block. A missing block (or a missing/non-integer version)
// yields versionPresent == false, which the matcher fails closed on. Never
// throws; malformed pieces are surfaced by the matcher, not here.
SemanticProfile
semanticProfileFromJson(const llvm::json::Object &targetProfile);

// Serialize a SemanticProfile as the canonical `semanticProfile` block (version
// + sorted features + limits) — the inverse of semanticProfileFromJson. Backs
// the `--dump-semantic-profile` surface and the file<->builtin drift self-test.
llvm::json::Value semanticProfileToJson(const SemanticProfile &profile);

// Match a verified plan against a profile, fail-closed and deterministic.
// Emits (with the  legality taxonomy), in order of precedence:
//   legality.unknown_profile_version — the profile declares no / an unsupported
//                                       semantic contract version (checked
//                                       FIRST, before dispatch);
//   legality.unknown_requirement     — the plan requires a feature outside the
//                                       closed registry (drift / unregistered
//                                       node);
//   legality.unsupported_feature     — a registered feature the profile does
//   not
//                                       advertise (incl. an unsupported
//                                       terminal shape);
//   legality.limit_exceeded          — a metric exceeds the profile's numeric
//                                       cap.
std::vector<Diagnostic> checkPlanLegality(const CoordinationPlan &plan,
                                          const SemanticProfile &profile);

// True when `diags` contains no error-severity diagnostic.
bool planIsLegal(const std::vector<Diagnostic> &diags);

} // namespace neutrino

#endif // NEUTRINO_PLAN_LEGALITY_H
