//===- SelfEmittedSpec.cpp - typed ingestion of translator-owned specs ----===//
//
// The single adapter ( S3 / ) for re-parsing the translator's OWN
// emitted capability-spec. A parse/shape failure here is an internal invariant,
// not user error, so it aborts rather than diagnoses.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SelfEmittedSpec.h"

#include "llvm/Support/ErrorHandling.h"

namespace neutrino {

namespace {

llvm::json::Value parseOwnOutput(llvm::StringRef ownSpecJson) {
  llvm::Expected<llvm::json::Value> v = llvm::json::parse(ownSpecJson);
  if (!v)
    llvm::report_fatal_error(
        llvm::Twine("internal: emitted capability-spec is not valid JSON: ") +
        llvm::toString(v.takeError()));
  return std::move(*v);
}

const llvm::json::Object *requireObject(const llvm::json::Value &v) {
  const llvm::json::Object *o = v.getAsObject();
  if (!o)
    llvm::report_fatal_error(
        "internal: emitted capability-spec is not a JSON object");
  return o;
}

} // namespace

// value_ is declared before object_, so it is constructed first and object_'s
// initializer reads the fully-built value_. The class is non-movable, so the
// pointer stays valid for the object's lifetime.
SelfEmittedSpec::SelfEmittedSpec(FromOwnOutput, llvm::StringRef ownSpecJson)
    : value_(parseOwnOutput(ownSpecJson)), object_(requireObject(value_)) {}

} // namespace neutrino
