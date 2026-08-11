#ifndef NEUTRINO_SELFEMITTEDSPEC_H
#define NEUTRINO_SELFEMITTEDSPEC_H

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

namespace neutrino {

// Owns the translator's re-parse of its OWN emitted capability-spec for a use
// lifetime, and exposes the validated json::Object that every registry entry
// hands to its frozen-spec renderer (D1). Emitting capabilitySpecJson(view)
// then re-parsing it is a round-trip through our OWN output, so a parse or
// shape failure is an INTERNAL invariant violation — it aborts via
// report_fatal_error, it is NOT a user diagnostic. Externally supplied specs
// keep their own diagnostic/validation path and never reach here (that
// distinction is the whole point of the FromOwnOutput tag).
//
// This is the ONE shared adapter for translator-owned spec ingestion ( S3 /
// ): it lives in the spec-contract leaf (backend-neutral — no
// ProcedureView, no renderer), so a backend/policy module can consume the
// object without the emit layer. The emit-side convenience that first emits the
// spec from a verified view, `ingestSelfEmittedSpec(view)`, is declared in
// GenSpec.h and keeps the ProcedureView on the emit side of the boundary.
//
// Non-copyable and non-movable: object() returns a reference into the owned
// json::Value, so the storage must not relocate. Constructing it by value out
// of ingestSelfEmittedSpec() is fine — C++17 guaranteed copy elision
// initializes the caller's local directly, with no move.
class SelfEmittedSpec {
public:
  // Disambiguating tag so a call site cannot accidentally route an EXTERNAL
  // spec through this fail-closed-abort path. External ingestion is
  // fail-WITH-diagnostics and uses a different surface.
  struct FromOwnOutput {};

  // Ingest an already-emitted, translator-OWNED spec buffer. Aborts (internal
  // invariant) if it is not valid JSON, or is valid JSON but not an object.
  SelfEmittedSpec(FromOwnOutput, llvm::StringRef ownSpecJson);

  SelfEmittedSpec(const SelfEmittedSpec &) = delete;
  SelfEmittedSpec &operator=(const SelfEmittedSpec &) = delete;

  // The validated capability-spec object. Valid for this SelfEmittedSpec's
  // lifetime.
  const llvm::json::Object &object() const { return *object_; }

private:
  llvm::json::Value value_;
  const llvm::json::Object *object_;
};

} // namespace neutrino

#endif // NEUTRINO_SELFEMITTEDSPEC_H
