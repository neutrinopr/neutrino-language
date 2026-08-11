#ifndef NEUTRINO_GEN_DOMAIN_SEMANTICS_H
#define NEUTRINO_GEN_DOMAIN_SEMANTICS_H

#include "mlir/IR/BuiltinOps.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

// The visible L2 domain-semantics artifact (): a deterministic, hashed JSON
// projection of a verified `l2.domain` — concepts, reduction edges, provenance,
// declared lossiness, and executable/descriptive classification, as inspectable
// DATA. Emitted under the SETTLED identity `neutrino.l2-domain-semantics`
// schemaVersion 2 (the executable-graph contract that supersedes the v1
// descriptive form). It is a SIBLING artifact: rigid backends never consume it
// ( §7), so emitting it cannot change any capability-spec or backend bytes.
//
// `module` must contain exactly one `l2.domain`. Returns the sidecar text (2-
// space, sorted-key JSON with a trailing newline) or a `spec.ast` error. The
// bytes are byte-reproducible: no timestamps, sorted keys, records sorted by
// identity, and a `domainSemanticsHash` = sha256 over the compact canonical
// form with the hash field removed (the same discipline as capabilityHash /
// domainDialectHash).
llvm::Expected<std::string> emitDomainSemanticsSidecar(mlir::ModuleOp module);

// Validate an EXTERNAL v2 domain-semantics sidecar at the re-ingest trust seam,
// before it is trusted as a reduction source. Fails CLOSED unless the artifact
// (a) carries the settled envelope identity (kind / schemaVersion 2 / a well-
// shaped domainSemanticsHash) with no unknown or missing top-level fields, (b)
// reconstructs into an l2.domain that passes the AUTHORITATIVE dialect verifier
// — the SAME cross-record contract the emitter's input satisfied: enum shape,
// one identifier namespace, reduction endpoint resolution, the descriptive/
// executable restriction, accepted provenance, traceability, and on_failure
// references — and (c) matches its canonical domainSemanticsHash recomputed
// over the raw body (arrays re-sorted, hash removed). It reuses the dialect
// verifier and the emitter's canonicalization, so it cannot grow a third
// contract that drifts from either. Returns a `spec.ast` error describing the
// first failure.
llvm::Error validateDomainSemanticsSidecarV2(const llvm::json::Object &sidecar);

} // namespace neutrino

#endif // NEUTRINO_GEN_DOMAIN_SEMANTICS_H
