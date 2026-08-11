//===- L2Reduction.cpp - verified L2->L1 reduction () -----------------===//
//
// Reduce a verified l2.domain onto the CLOSED semantic-requirement vocabulary a
// CoordinationPlan induces. This is the ONE authoritative registry — the same
// coordinationPlanRequirements / knownSemanticFeatures that plan-legality uses
// — so the domain model can never grow a second, procedure-local vocabulary
// that drifts from coordination-plan legality. DATA-driven ( §2). The
// reducible content of a domain (its l1_features + reduction edges) is
// extracted into a neutral model from EITHER the l2 MLIR or its emitted v2
// sidecar, then fed to one shared core — so re-ingesting the artifact yields
// the identical reduction as the direct IR.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/L2Reduction.h"
#include "Neutrino/GenDomainSemantics.h"
#include "Neutrino/SemanticRequirements.h"

#include "mlir/IR/BuiltinOps.h"
#include "llvm/ADT/StringMap.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <optional>
#include <tuple>

using namespace mlir;
using namespace neutrino;
using namespace neutrino::l2;

namespace {
// A domain's reducible content, extractable from the l2 MLIR OR its v2 sidecar.
struct L2Model {
  std::string domain;
  std::vector<std::pair<std::string, std::string>> l1Features; // (name, kind)
  struct Edge {
    std::string id, from, to, relation;
  };
  std::vector<Edge> edges;
};

llvm::Error reductionError(const std::string &msg) {
  return llvm::createStringError(llvm::inconvertibleErrorCode(),
                                 "spec.ast: " + msg);
}

// The authoritative primitive/obligation category lives in SemanticRequirements
// (the ONE registry) so the reduction kind-check and the published capability
// registry project the identical rule. The l1_feature kind must agree with it.
llvm::StringRef featureCategory(llvm::StringRef feature) {
  return neutrino::semanticFeatureCategory(feature);
}

L2Model modelOf(DomainOp domain) {
  L2Model m;
  m.domain = domain.getSymName().str();
  for (Operation &op : domain.getBody().front()) {
    if (auto a = dyn_cast<L1FeatureOp>(op))
      m.l1Features.push_back({a.getSymName().str(), a.getKind().str()});
    else if (auto r = dyn_cast<ReduceOp>(op))
      m.edges.push_back({r.getSymName().str(), r.getFrom().str(),
                         r.getTo().str(), r.getRelation().str()});
  }
  return m;
}

llvm::Expected<L2Model> modelOfSidecar(const llvm::json::Object &s) {
  L2Model m;
  if (auto d = s.getString("domain"))
    m.domain = d->str();
  const llvm::json::Array *feats = s.getArray("l1Features");
  const llvm::json::Array *reds = s.getArray("reductions");
  if (!feats || !reds)
    return reductionError("v2 sidecar missing l1Features/reductions");
  for (const auto &v : *feats) {
    const llvm::json::Object *o = v.getAsObject();
    if (!o)
      return reductionError("v2 sidecar l1Feature is not an object");
    auto name = o->getString("name");
    auto kind = o->getString("kind");
    if (!name || !kind)
      return reductionError("v2 sidecar l1Feature missing name/kind");
    m.l1Features.push_back({name->str(), kind->str()});
  }
  for (const auto &v : *reds) {
    const llvm::json::Object *o = v.getAsObject();
    if (!o)
      return reductionError("v2 sidecar reduction is not an object");
    auto id = o->getString("id");
    auto from = o->getString("from");
    auto to = o->getString("to");
    auto rel = o->getString("relation");
    if (!id || !from || !to || !rel)
      return reductionError("v2 sidecar reduction missing id/from/to/relation");
    m.edges.push_back({id->str(), from->str(), to->str(), rel->str()});
  }
  return m;
}

// The shared reduction core: resolve each l1_feature onto the closed vocabulary
// the coordination plan induces, fail-closed and DISTINCTLY, then project
// edges.
llvm::Expected<L2Reduction> reduceModel(const L2Model &model,
                                        const CoordinationPlan &plan) {
  llvm::StringMap<std::string> induced;
  for (const SemanticRequirement &r :
       coordinationPlanRequirements(plan).features)
    induced[r.feature] = r.primitive;
  const std::set<std::string> &known = knownSemanticFeatures();

  llvm::StringMap<std::string> bound; // feature -> inducing construct
  for (const auto &f : model.l1Features) {
    llvm::StringRef feature = f.first, kind = f.second;
    if (!known.count(feature.str()))
      return reductionError(
          ("l1_feature '" + feature +
           "' is not a registered semantic feature (knownSemanticFeatures)")
              .str());
    if (featureCategory(feature) != kind)
      return reductionError(("l1_feature '" + feature + "' is a " +
                             featureCategory(feature) +
                             ", not declared kind '" + kind + "'")
                                .str());
    auto it = induced.find(feature);
    if (it == induced.end())
      return reductionError(
          ("l1_feature '" + feature +
           "' is a registered feature the coordination plan does not induce")
              .str());
    bound[feature] = it->second;
  }

  L2Reduction red;
  red.domain = model.domain;
  for (const L2Model::Edge &e : model.edges) {
    L2Binding b;
    b.conceptName = e.from;
    b.edge = e.id;
    b.relation = e.relation;
    if (e.relation == "failure") {
      b.feature = "failure:" + e.to;
    } else {
      b.feature = e.to;
      b.inducedBy = bound[e.to];
    }
    red.bindings.push_back(std::move(b));
  }
  std::sort(red.bindings.begin(), red.bindings.end(),
            [](const L2Binding &x, const L2Binding &y) {
              return std::tie(x.feature, x.edge) < std::tie(y.feature, y.edge);
            });
  return red;
}
} // namespace

llvm::Expected<L2Reduction>
neutrino::reduceL2ToCoordinationPlan(DomainOp domain,
                                     const CoordinationPlan &coordinationPlan) {
  return reduceModel(modelOf(domain), coordinationPlan);
}

llvm::Expected<L2Reduction> neutrino::reduceSidecarToCoordinationPlan(
    const llvm::json::Object &sidecar,
    const CoordinationPlan &coordinationPlan) {
  // The re-ingest trust seam: an external sidecar is reduced ONLY after it
  // passes the full v2 contract (envelope, the authoritative dialect verifier,
  // recomputed hash). So a stale-hash or dangling-reference artifact is
  // rejected before modelOfSidecar ever reads it.
  if (llvm::Error e = validateDomainSemanticsSidecarV2(sidecar))
    return std::move(e);
  llvm::Expected<L2Model> m = modelOfSidecar(sidecar);
  if (!m)
    return m.takeError();
  return reduceModel(*m, coordinationPlan);
}

std::string neutrino::emitDomainReduction(const L2Reduction &reduction) {
  llvm::json::Array bindings;
  for (const L2Binding &b : reduction.bindings) {
    llvm::json::Object o{{"concept", b.conceptName},
                         {"edge", b.edge},
                         {"relation", b.relation},
                         {"feature", b.feature}};
    if (!b.inducedBy.empty())
      o["inducedBy"] = b.inducedBy;
    bindings.push_back(std::move(o));
  }
  // A deterministic, sorted PROJECTION — no kind/schemaVersion/hash: it is the
  // internal parity-comparison view, not a versioned public artifact.
  llvm::json::Object root{{"domain", reduction.domain},
                          {"bindings", std::move(bindings)}};
  return llvm::formatv("{0:2}", llvm::json::Value(std::move(root))).str() +
         "\n";
}
