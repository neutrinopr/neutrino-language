#ifndef NEUTRINO_SEMANTIC_REQUIREMENTS_H
#define NEUTRINO_SEMANTIC_REQUIREMENTS_H

// The normalized semantic-requirement derivation: from a VERIFIED
// CoordinationPlan — never from source or spec text — compute the closed set of
// semantic features the coordination plan places on any realization, plus the
// parameterized metrics a profile bounds with numeric limits. This is the ONE
// requirement derivation; the reference evaluator and every lowering match its
// output against their SemanticProfile through the one shared matcher
// (PlanLegality.h). Requirement features live in a CLOSED registry
// (knownSemanticFeatures): a derived feature outside it is a drift bug the
// matcher fails closed on, so an unregistered future coordination-plan node
// cannot be silently realized.

#include "Neutrino/CoordinationPlan.h"

#include "llvm/ADT/StringRef.h"

#include <set>
#include <string>
#include <vector>

namespace neutrino {

// One normalized semantic requirement: a closed-registry feature string plus
// the coordination-plan construct that induced it (for the diagnostic; NO
// source line — the coordination plan is source-neutral).
struct SemanticRequirement {
  std::string feature;   // e.g. "effect:debit", "terminal:contested"
  std::string primitive; // e.g. "effect pay_out", "terminal projection"
};

// The parameterized measures a profile bounds as LIMITS (not feature flags):
// expression depth, effect/group/attestation counts, and a compute/resource
// proxy. Each is the coordination plan's actual value; the matcher refuses when
// it exceeds the profile's cap.
struct PlanMetrics {
  int expressionDepth = 0; // max AST depth over computes + guards (structural)
  int effectCount = 0;
  int effectGroupCount = 0;
  int attestationCount = 0;
  int computeCount = 0;
  // A genuine compute-cost / bounded-step measure: the TOTAL number of
  // arithmetic/comparison/call OPERATIONS across every compute + guard (leaves
  // excluded). Distinct from the structural counts above — a wide-but-shallow
  // coordination has many steps at low depth — so a step-bounded backend caps
  // it via maxOperationSteps.
  int operationSteps = 0;
};

struct PlanRequirements {
  std::vector<SemanticRequirement> features; // in a stable, deterministic order
  PlanMetrics metrics;
};

// Derive the normalized semantic requirements + metrics from a verified
// coordination plan.
PlanRequirements
coordinationPlanRequirements(const CoordinationPlan &coordinationPlan);

// The CLOSED registry of semantic-requirement feature strings the normalized
// vocabulary defines. The built-in reference evaluator profile supports exactly
// this set; a requirement feature absent here is unknown and fails closed.
// Distinct from the OPEN spec-feature namespace (value_category:* / topology:*
// / binding:* …), which stays open — this registry governs only the
// normalized-transition semantic requirements derived from the
// CoordinationPlan.
const std::set<std::string> &knownSemanticFeatures();

// The closed semantic-feature vocabulary as a deterministic JSON artifact
// (kind "neutrino.semantic-feature-vocabulary"): schemaVersion, the pinned
// kSemanticProfileVersion, and the sorted closed feature set. This is the ONE
// published projection of knownSemanticFeatures(); the Python tooling (target-
// profile validator, bundle generator, released domain-pack verifier) consumes
// this artifact rather than re-declaring the set, so there is no parallel
// hand-maintained table. Byte-matched against
// docs/semantic-feature-vocabulary.json by CI, exactly like the diagnostic
// taxonomy.
std::string semanticFeatureVocabularyJson();

// Handle `--semantic-feature-vocabulary`: print the vocabulary JSON and return
// true (a pure query needing no input file), else false. Dispatched before cl
// parsing, like --diagnostic-taxonomy.
bool handleSemanticVocabularyFlag(int argc, char **argv);

// The authoritative category of a closed semantic feature: "obligation" for the
// constraint dimensions a coordination must uphold (invariant:/replay:),
// "primitive" otherwise. This is the ONE definition the L2->L1 reduction checks
// an l1_feature's declared kind against and the capability registry projects,
// so the two can never disagree about a feature's type.
llvm::StringRef semanticFeatureCategory(llvm::StringRef feature);

// The closed capability registry as a deterministic JSON artifact (kind
// "neutrino.semantic-capability-registry"): schemaVersion, the pinned
// kSemanticProfileVersion, and the sorted closed capability set, each carrying
// only metadata the vocabulary authoritatively supports — the stable `id`
// (the <dimension>:<value> feature string), its `dimension` (role) and `value`,
// and its `category` (primitive/obligation type, from semanticFeatureCategory).
// A pure projection of knownSemanticFeatures(); it introduces NO capability of
// its own and NO domain/backend identity. Byte-matched against
// docs/semantic-capability-registry.json by CI, exactly like the vocabulary.
std::string semanticCapabilityRegistryJson();

// Handle `--capability-registry`: print the capability-registry JSON and return
// true (a pure query needing no input file), else false. Dispatched before cl
// parsing, like --semantic-feature-vocabulary.
bool handleCapabilityRegistryFlag(int argc, char **argv);

} // namespace neutrino

#endif // NEUTRINO_SEMANTIC_REQUIREMENTS_H
