//===- SemanticRequirements.cpp - CoordinationPlan -> requirements --------===//
//
// The ONE requirement derivation: coordinationPlanRequirements reads a VERIFIED
// CoordinationPlan and emits the closed set of semantic features it requires
// plus the metrics a profile bounds. Derived purely from the coordination plan
// (the normalized semantic form), never re-reading source or spec text — so the
// reference evaluator and every lowering reason about the same requirements.
//
// SCOPE: this registry covers the normalized-transition semantics the
// CoordinationPlan carries — authorization mode, ledger-effect forms, guards,
// the balance invariant, attestation gating, lifecycle/terminal shapes, replay,
// and explicit TIME via a declared temporal input inventory. The metrics add a
// genuine bounded-STEP measure (operationSteps) beyond the structural counts.
// Realizability of a value category / expression operation (incl. the Extension
// category a temporal type classifies as) stays in the OPEN spec-feature
// namespace, gated by SpecLegality (value_category:* / topology:* …) — nothing
// falls between the two gates. See docs/backends/TARGET_PROFILES.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SemanticRequirements.h"

#include "Neutrino/Expr.h"
#include "Neutrino/ValueModel.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>

namespace neutrino {

namespace {
// The AST depth of an expression (a leaf is depth 1; null is 0).
int exprDepth(const ExprNode *n) {
  if (!n)
    return 0;
  int child = 0;
  if (n->lhs)
    child = std::max(child, exprDepth(n->lhs.get()));
  if (n->rhs)
    child = std::max(child, exprDepth(n->rhs.get()));
  for (const auto &a : n->args)
    child = std::max(child, exprDepth(a.get()));
  return child + 1;
}

// The number of OPERATIONS in an expression (a genuine step count): every
// Bin / Cmp / Call node counts one step; Num / Var leaves count zero.
int exprOps(const ExprNode *n) {
  if (!n)
    return 0;
  int ops = (n->kind == ExprNode::Bin || n->kind == ExprNode::Cmp ||
             n->kind == ExprNode::Call)
                ? 1
                : 0;
  ops += exprOps(n->lhs.get()) + exprOps(n->rhs.get());
  for (const auto &a : n->args)
    ops += exprOps(a.get());
  return ops;
}
} // namespace

const std::set<std::string> &knownSemanticFeatures() {
  // The CLOSED normalized-semantic-requirement vocabulary. Every feature
  // coordinationPlanRequirements can emit is registered here; the reference
  // evaluator's INDEPENDENTLY-declared support set (evaluatorSupportedFeatures)
  // is compared against it by a drift self-test.
  static const std::set<std::string> kRegistry = {
      "authorization:explicit",
      "effect:credit",
      "effect:debit",
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
  return kRegistry;
}

PlanRequirements
coordinationPlanRequirements(const CoordinationPlan &coordinationPlan) {
  PlanRequirements out;
  auto add = [&](std::string feature, std::string primitive) {
    out.features.push_back({std::move(feature), std::move(primitive)});
  };

  // Authorization mode: the normalized transition model authorizes every
  // invocation explicitly (the one mode today; the network binds the decision).
  add("authorization:explicit", "transition authorization");

  // Effect (ledger-delta) forms, one per distinct kind in first-appearance
  // order, plus whether any leg is guarded. An UNREGISTERED kind (a future
  // effect form) yields an effect:<kind> requirement outside the closed
  // registry, so the matcher — even the reference evaluator — refuses it until
  // the vocabulary is explicitly extended (the drift fail-closed).
  std::set<std::string> seenKinds;
  bool guarded = false;
  for (const PlanEffect &e : coordinationPlan.effects) {
    if (seenKinds.insert(e.kind).second)
      add("effect:" + e.kind, "effect " + e.name);
    if (e.guard)
      guarded = true;
  }
  if (guarded)
    add("guard:conditional", "guarded effect");

  // Invariants + attestation gating.
  if (coordinationPlan.balanced)
    add("invariant:balanced", "balance obligation");
  if (!coordinationPlan.attestations.empty())
    add("attestation:quorum", "attestation policy");

  // Lifecycle/terminal shapes the coordination plan projects (success is always
  // required).
  add("terminal:success", "terminal projection");
  if (!coordinationPlan.terminal.aborted.empty())
    add("terminal:aborted", "terminal projection");
  if (!coordinationPlan.terminal.contested.empty())
    add("terminal:contested", "terminal projection");

  // Replay/idempotency obligation.
  if (coordinationPlan.replay.idempotent)
    add("replay:idempotent", "replay obligation");

  // Explicit coordination identity: an instance key declared independently of
  // any ledger effect. Required for an effectless evidence-only coordination
  // and available to any coordination that declares one.
  if (!coordinationPlan.explicitInstanceKey.empty())
    add("identity:explicit_instance_key", "explicit instance key");

  // Evidence-only coordination: acceptance of attested evidence with no ledger
  // movement. A target that does not realize zero-value coordination refuses it
  // before dispatch.
  if (coordinationPlan.evidenceOnly)
    add("coordination:evidence_acceptance", "evidence acceptance action");

  // Explicit time: a declared temporal input makes the coordination
  // time-dependent, so it requires a target that realizes explicit time
  // semantics. An otherwise-identical numeric coordination declares no temporal
  // input and derives no such requirement.
  for (const PlanInput &in : coordinationPlan.inputs)
    if (isTemporalType(in.type)) {
      add("time:explicit_input", "input " + in.name);
      break;
    }

  // Parameterized metrics (bounded by profile limits, not feature flags):
  // structural counts + expression depth, plus operationSteps — a genuine
  // bounded-step / compute-cost measure distinct from the counts.
  out.metrics.effectCount = (int)coordinationPlan.effects.size();
  out.metrics.effectGroupCount = (int)coordinationPlan.effectGroups.size();
  out.metrics.attestationCount = (int)coordinationPlan.attestations.size();
  out.metrics.computeCount = (int)coordinationPlan.computes.size();
  int depth = 0, ops = 0;
  for (const PlanCompute &c : coordinationPlan.computes) {
    depth = std::max(depth, exprDepth(c.expr.get()));
    ops += exprOps(c.expr.get());
  }
  for (const PlanEffect &e : coordinationPlan.effects) {
    depth = std::max(depth, exprDepth(e.guard.get()));
    ops += exprOps(e.guard.get());
  }
  out.metrics.expressionDepth = depth;
  out.metrics.operationSteps = ops;

  return out;
}

llvm::StringRef semanticFeatureCategory(llvm::StringRef feature) {
  // invariant:/replay: are OBLIGATIONS (constraints the coordination must
  // uphold); every other dimension is a PRIMITIVE (a thing it does).
  if (feature.startswith("invariant:") || feature.startswith("replay:"))
    return "obligation";
  return "primitive";
}

std::string semanticCapabilityRegistryJson() {
  // knownSemanticFeatures() is a std::set, so iteration is the sorted,
  // deterministic order the byte-match relies on. Each capability is a pure
  // projection of one closed feature: its stable id, the dimension/value split,
  // and its authoritative category — nothing hand-authored, no domain identity.
  llvm::json::Array capabilities;
  for (const std::string &f : knownSemanticFeatures()) {
    llvm::StringRef feature(f);
    auto colon = feature.find(':');
    capabilities.push_back(llvm::json::Object{
        {"id", f},
        {"dimension", feature.take_front(colon).str()},
        {"value", feature.drop_front(colon + 1).str()},
        {"category", semanticFeatureCategory(feature).str()},
    });
  }
  llvm::json::Object root{
      {"schemaVersion", 1},
      {"kind", "neutrino.semantic-capability-registry"},
      {"semanticProfileVersion", kSemanticProfileVersion},
      {"capabilities", std::move(capabilities)},
  };
  return llvm::formatv("{0:2}", llvm::json::Value(std::move(root))).str();
}

bool handleCapabilityRegistryFlag(int argc, char **argv) {
  for (int i = 1; i < argc; ++i) {
    if (llvm::StringRef(argv[i]) == "--capability-registry") {
      llvm::outs() << semanticCapabilityRegistryJson() << "\n";
      return true;
    }
  }
  return false;
}

std::string semanticFeatureVocabularyJson() {
  // knownSemanticFeatures() is a std::set, so iteration is already the sorted,
  // deterministic order the byte-match relies on.
  llvm::json::Array features;
  for (const std::string &f : knownSemanticFeatures())
    features.push_back(f);
  llvm::json::Object root{
      {"schemaVersion", 1},
      {"kind", "neutrino.semantic-feature-vocabulary"},
      {"semanticProfileVersion", kSemanticProfileVersion},
      {"features", std::move(features)},
  };
  return llvm::formatv("{0:2}", llvm::json::Value(std::move(root))).str();
}

bool handleSemanticVocabularyFlag(int argc, char **argv) {
  for (int i = 1; i < argc; ++i) {
    if (llvm::StringRef(argv[i]) == "--semantic-feature-vocabulary") {
      llvm::outs() << semanticFeatureVocabularyJson() << "\n";
      return true;
    }
  }
  return false;
}

} // namespace neutrino
