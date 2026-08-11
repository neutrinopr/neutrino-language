//===- L2Dialect.cpp - generic L2 domain-semantics meta-model () ------===//
//
// Registration + fail-closed verifiers for the generic `l2` dialect. The closed
// enum vocabularies are pinned here (a laundered spelling is rejected at IR-
// verify time), and the domain container verifies the cross-record rules the
// visible sidecar depends on: a closed body, reference resolution, traceability
// to a DECLARED L1 anchor, that a descriptive concept can never drive an
// executable reduction, and that every behaviour-driving edge carries accepted
// provenance. Diagnostics are plain messages, not bracketed pseudo-codes: the
// shared taxonomy is the single source of coded diagnostics, joined when the
// stdlib validator lands with its drift check.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/L2Dialect.h"
#include "Neutrino/Version.h"

#include "mlir/IR/Builders.h"
#include "mlir/IR/BuiltinAttributes.h"
#include "mlir/IR/OpImplementation.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/StringMap.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/ADT/StringSet.h"

using namespace mlir;
using namespace neutrino::l2;

#include "Neutrino/L2Dialect.cpp.inc"

#define GET_OP_CLASSES
#include "Neutrino/L2Ops.cpp.inc"

void L2Dialect::initialize() {
  addOperations<
#define GET_OP_LIST
#include "Neutrino/L2Ops.cpp.inc"
      >();
}

namespace {
// A closed vocabulary check: membership without accepting a laundered spelling.
bool oneOf(llvm::StringRef v, std::initializer_list<llvm::StringRef> set) {
  return llvm::is_contained(set, v);
}
bool isSha256(llvm::StringRef s) {
  return s.size() == 64 && llvm::all_of(s, [](char c) {
           return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
         });
}
// A reduction relation that lands value on an L1 anchor (vs. a failure edge).
bool isL1Relation(llvm::StringRef rel) {
  return rel == "expands" || rel == "discharges" || rel == "protects";
}
// A relation that actually drives L1 behaviour (needs accepted provenance and
// an executable source concept).
bool isExecutableRelation(llvm::StringRef rel) {
  return rel == "expands" || rel == "discharges";
}
// A lossiness that lets an edge stand as a real trace (not an unsupported
// stub).
bool isSupported(llvm::StringRef loss) {
  return loss == "lossless" || loss == "lossy_preserved";
}
} // namespace

// Every named record needs a stable, non-empty identity — the cross-record
// semantics (reference resolution, the single namespace) depend on it.
template <typename OpT>
static LogicalResult verifyName(OpT op, const char *what) {
  if (op.getSymName().empty())
    return op.emitOpError() << "an l2." << what << " needs a non-empty name";
  return success();
}

LogicalResult L1FeatureOp::verify() {
  if (failed(verifyName(*this, "l1_feature")))
    return failure();
  if (!oneOf(getKind(), {"primitive", "obligation"}))
    return emitOpError() << "L1 feature kind '" << getKind()
                         << "' is not one of primitive/obligation";
  return success();
}

LogicalResult FailureModeOp::verify() {
  return verifyName(*this, "failure_mode");
}

LogicalResult ConceptOp::verify() {
  if (failed(verifyName(*this, "concept")))
    return failure();
  if (!oneOf(getKind(), {"state", "action", "concept"}))
    return emitOpError() << "concept kind '" << getKind()
                         << "' is not one of state/action/concept";
  if (!oneOf(getClassification(), {"executable", "descriptive"}))
    return emitOpError() << "concept classification '" << getClassification()
                         << "' is not one of executable/descriptive";
  return success();
}

LogicalResult ReduceOp::verify() {
  if (getSymName().empty() || getFrom().empty() || getTo().empty())
    return emitOpError()
           << "a reduction edge needs a non-empty id, from-concept "
              "and to-feature";
  if (!oneOf(getRelation(), {"expands", "discharges", "protects", "failure"}))
    return emitOpError()
           << "reduction relation '" << getRelation()
           << "' is not one of expands/discharges/protects/failure";
  if (!oneOf(getLossiness(), {"lossless", "lossy_preserved", "unsupported"}))
    return emitOpError()
           << "reduction lossiness '" << getLossiness()
           << "' is not one of lossless/lossy_preserved/unsupported";
  return success();
}

LogicalResult InvariantOp::verify() {
  if (failed(verifyName(*this, "invariant")))
    return failure();
  if (getPredicate().empty())
    return emitOpError() << "an invariant needs a non-empty predicate";
  return success();
}

LogicalResult ProvenanceOp::verify() {
  if (getSubject().empty() || getSource().empty())
    return emitOpError() << "provenance needs a non-empty subject and source";
  if (!oneOf(getStatus(), {"proposed", "accepted", "rejected"}))
    return emitOpError() << "provenance status '" << getStatus()
                         << "' is not one of proposed/accepted/rejected";
  if (getExcerptHash() && !isSha256(*getExcerptHash()))
    return emitOpError()
           << "provenance excerpt hash is not a 64-char lowercase sha256";
  return success();
}

LogicalResult ImportOp::verify() {
  if (getCapability().empty())
    return emitOpError() << "an l2.import needs a non-empty capability";
  if (!isValidSemVer(getVersion()))
    return emitOpError() << "l2.import version '" << getVersion()
                         << "' is not a semantic version (MAJOR.MINOR.PATCH)";
  return success();
}

LogicalResult DomainOp::verify() {
  if (getSymName().empty() || getImplements().empty())
    return emitOpError() << "a domain needs a non-empty name and implements";
  if (!isValidSemVer(getVersion()))
    return emitOpError() << "domain version '" << getVersion()
                         << "' is not a semantic version (MAJOR.MINOR.PATCH)";
  if (getCoverage() && !oneOf(*getCoverage(), {"full", "partial"}))
    return emitOpError() << "domain coverage '" << *getCoverage()
                         << "' is not one of full/partial";

  // The body is CLOSED, and every named record shares ONE global namespace — so
  // a provenance subject (or any reference) resolves to exactly one record and
  // a concept can never collide with an edge id.
  llvm::StringMap<ConceptOp> concepts;
  llvm::StringSet<> l1Features, failureModes, edgeIds, allIds, imports;
  auto claim = [&](Operation *op, llvm::StringRef name,
                   const char *what) -> LogicalResult {
    if (!allIds.insert(name).second)
      return op->emitOpError() << what << " identifier '" << name
                               << "' collides with another record (identities "
                                  "share one namespace)";
    return success();
  };
  for (Operation &op : getBody().front()) {
    if (auto c = dyn_cast<ConceptOp>(op)) {
      if (failed(claim(c, c.getSymName(), "concept")))
        return failure();
      concepts.insert({c.getSymName(), c});
    } else if (auto f = dyn_cast<FailureModeOp>(op)) {
      if (failed(claim(f, f.getSymName(), "failure mode")))
        return failure();
      failureModes.insert(f.getSymName());
    } else if (auto a = dyn_cast<L1FeatureOp>(op)) {
      if (failed(claim(a, a.getSymName(), "L1 feature")))
        return failure();
      l1Features.insert(a.getSymName());
    } else if (auto r = dyn_cast<ReduceOp>(op)) {
      if (failed(claim(r, r.getSymName(), "reduction edge")))
        return failure();
      edgeIds.insert(r.getSymName());
    } else if (auto imp = dyn_cast<ImportOp>(op)) {
      // An import is a foreign reference, not a local identity, so it does not
      // claim the shared namespace — but a domain may import a given capability
      // at most once (importing two versions of it is contradictory).
      if (!imports.insert(imp.getCapability()).second)
        return imp.emitOpError() << "duplicate import of capability '"
                                 << imp.getCapability() << "'";
    } else if (!isa<InvariantOp, ProvenanceOp>(op)) {
      return op.emitOpError() << "is not an l2 domain record (expected "
                                 "l1_feature/concept/reduce/import/"
                                 "failure_mode/invariant/provenance)";
    }
  }

  // Resolve every reduction edge; count a concept as traced only by a
  // SUPPORTED, non-failure edge to a declared L1 anchor. A descriptive concept
  // may not drive an executable reduction.
  llvm::StringSet<> traced;
  for (Operation &op : getBody().front()) {
    auto r = dyn_cast<ReduceOp>(op);
    if (!r)
      continue;
    auto from = concepts.find(r.getFrom());
    if (from == concepts.end())
      return r.emitOpError() << "reduction edge from undeclared concept '"
                             << r.getFrom() << "'";
    if (r.getRelation() == "failure") {
      if (!failureModes.contains(r.getTo()))
        return r.emitOpError()
               << "failure edge targets undeclared failure mode '" << r.getTo()
               << "'";
    } else if (!l1Features.contains(r.getTo())) {
      return r.emitOpError() << "reduction edge targets undeclared L1 feature '"
                             << r.getTo() << "'";
    }
    if (isExecutableRelation(r.getRelation()) &&
        from->second.getClassification() == "descriptive")
      return r.emitOpError() << "descriptive concept '" << r.getFrom()
                             << "' cannot drive an executable "
                             << r.getRelation() << " reduction";
    if (isL1Relation(r.getRelation()) && isSupported(r.getLossiness()))
      traced.insert(r.getFrom());
  }

  // Every concept must trace to a declared L1 anchor (a failure-only or
  // unsupported-only concept is untraced).
  for (auto &c : concepts)
    if (!traced.contains(c.first())) {
      ConceptOp cop = c.second;
      return cop.emitOpError()
             << "concept '" << c.first()
             << "' has no supported reduction to a declared L1 feature";
    }

  // Provenance binds to a declared concept or edge id; every behaviour-driving
  // (executable) edge needs an accepted provenance referencing its id.
  llvm::StringSet<> acceptedSubjects;
  for (Operation &op : getBody().front())
    if (auto p = dyn_cast<ProvenanceOp>(op)) {
      bool resolves =
          concepts.count(p.getSubject()) || edgeIds.count(p.getSubject());
      if (!resolves)
        return p.emitOpError() << "provenance subject '" << p.getSubject()
                               << "' resolves to no declared concept or edge";
      if (p.getStatus() == "accepted")
        acceptedSubjects.insert(p.getSubject());
    }
  for (Operation &op : getBody().front())
    if (auto r = dyn_cast<ReduceOp>(op))
      if (isExecutableRelation(r.getRelation()) &&
          !acceptedSubjects.contains(r.getSymName()))
        return r.emitOpError()
               << "executable reduction edge '" << r.getSymName()
               << "' has no accepted provenance";

  // An invariant's on_failure must reference a declared failure mode.
  for (Operation &op : getBody().front())
    if (auto inv = dyn_cast<InvariantOp>(op))
      if (inv.getOnFailure() && !failureModes.contains(*inv.getOnFailure()))
        return inv.emitOpError()
               << "invariant on_failure references undeclared failure mode '"
               << *inv.getOnFailure() << "'";

  return success();
}
