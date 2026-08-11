#ifndef NEUTRINO_L2_REDUCTION_H
#define NEUTRINO_L2_REDUCTION_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/L2Dialect.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// One reduction binding: a domain concept, via an identified reduction edge,
// reduced onto a CLOSED semantic-requirement feature the CoordinationPlan
// actually induces (or a declared failure mode, for a failure edge).
struct L2Binding {
  std::string conceptName; // the l2.concept the edge reduces from
  std::string edge;        // the l2.reduce id
  std::string relation;    // expands|discharges|protects|failure
  std::string feature;     // the closed feature string (e.g. "effect:debit",
                           // "invariant:balanced") or "failure:<mode>"
  std::string inducedBy;   // the inducing construct from
                         // coordinationPlanRequirements; "" for a failure edge
};

// The reduction of one domain onto a verified CoordinationPlan (bindings
// sorted).
struct L2Reduction {
  std::string domain;
  std::vector<L2Binding> bindings; // sorted by (feature, edge) — canonical
};

// Reduce a verified l2.domain onto the CLOSED semantic-requirement vocabulary a
// CoordinationPlan induces (coordinationPlanRequirements /
// knownSemanticFeatures — the SAME authoritative registry plan-legality uses),
// DATA-driven ( §2). Each declared l1_feature names a closed feature
// string; the reduction resolves it against that vocabulary, failing CLOSED and
// DISTINCTLY on:
//   * unregistered — the feature is outside knownSemanticFeatures()
//   * misclassified — its category (primitive vs obligation) disagrees with the
//     l1_feature kind
//   * plan-absent — a registered feature the coordination plan does NOT induce
llvm::Expected<L2Reduction>
reduceL2ToCoordinationPlan(l2::DomainOp domain,
                           const CoordinationPlan &coordinationPlan);

// The SAME reduction, driven from an emitted (and separately validated) v2
// domain-semantics sidecar JSON instead of the l2 MLIR — so re-ingesting the
// artifact yields the IDENTICAL reduction as the direct IR (the two feed one
// shared core). Fails closed on a malformed sidecar.
llvm::Expected<L2Reduction>
reduceSidecarToCoordinationPlan(const llvm::json::Object &sidecar,
                                const CoordinationPlan &coordinationPlan);

// Serialize an L2Reduction to a deterministic, sorted JSON PROJECTION — the
// comparison artifact for the parity proof, NOT a versioned public contract (no
// kind / schemaVersion / hash): it is an internal diagnostic view whose only
// job is to be byte-comparable across the two reduction sources and the two
// coordination-plan construction paths.
std::string emitDomainReduction(const L2Reduction &reduction);

} // namespace neutrino

#endif // NEUTRINO_L2_REDUCTION_H
