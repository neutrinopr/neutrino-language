#ifndef NEUTRINO_AGREEMENT_ENVELOPE_H
#define NEUTRINO_AGREEMENT_ENVELOPE_H

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

// The portable semantic-agreement identity (), model 1 of :
//   agreementHash = H( DOMAIN("neutrino.agreement.v1")
//                    ‖ semanticLanguageVersion
//                    ‖ canonicalCapabilitySpecBytes
//                    ‖ canonicalAgreementEnvelopeBytes )
// The frozen capability-spec stays the external semantic contract; this binds
// it to the identity-level semantics that live OUTSIDE the spec
// (consent/amendment policy + clause semantic IDs) without turning the internal
// CoordinationPlan into a wire contract. Domain-separated + version-included so
// an agreement digest can never collide with any other neutrino hash. This is
// the MLIR-free identity core; the view-based emitter is in
// GenAgreementEnvelope.h.

// The versioned agreement envelope: the identity-level semantics carried
// ALONGSIDE the capability-spec. Greenfield in S1 — the policies default to
// null and clauseSemanticIds is empty (later slices author them). Its compact
// canonical bytes are the fourth agreementHash preimage component.
llvm::json::Object agreementEnvelopeJson();

// The length-framed, domain-separated agreementHash PREIMAGE bytes:
//   frame(domain) ‖ frame(semanticLanguageVersion)
//     ‖ frame(canonicalCapabilitySpecBytes) ‖
//     frame(canonicalAgreementEnvelopeBytes)
// where frame(x) = BE64(byteLength(x)) ‖ x — an unsigned 64-bit big-endian
// length prefix. The framing makes the concatenation unambiguous: no field
// boundary can shift to forge a colliding preimage. Raw component bytes are
// concatenated (NOT their digests), per the model-1 identity.
std::string
agreementHashPreimage(llvm::StringRef domain,
                      llvm::StringRef semanticLanguageVersion,
                      llvm::StringRef canonicalCapabilitySpecBytes,
                      llvm::StringRef canonicalAgreementEnvelopeBytes);

// agreementHash = sha256Hex over the preimage, using this translator's domain
// tag + semantic-language version.
std::string agreementHashOf(llvm::StringRef canonicalCapabilitySpecBytes,
                            llvm::StringRef canonicalAgreementEnvelopeBytes);

// The agreement-identity artifact JSON built over already-canonical capability
// semantic bytes (the pretty-printed, sorted-key, trailing-newline file form).
std::string
agreementIdentityFromBytes(llvm::StringRef canonicalCapabilitySpecBytes);

// Reconstruct the agreement-identity from an external capability-spec (the
// consumer / --from-spec path). Fails closed (Error) BEFORE producing an
// artifact on a capability-spec whose recomputed capabilityHash does not match
// its declared identity.capabilityHash (a tampered / non-canonical spec).
llvm::Expected<std::string>
agreementIdentityFromSpec(const llvm::json::Object &spec);

// Verify an agreement-identity artifact against its capability-spec. Fails
// closed on: an unknown domain / semanticLanguage / envelope version; a
// capability-spec whose capabilityHash does not match the artifact; or an
// agreementHash that does not recompute (a tampered identity). Succeeds only
// for an authentic identity expressed in a known identity language.
llvm::Error verifyAgreementIdentity(const llvm::json::Object &artifact,
                                    const llvm::json::Object &capabilitySpec);

} // namespace neutrino

#endif // NEUTRINO_AGREEMENT_ENVELOPE_H
