//===- AgreementEnvelope.cpp - portable agreement identity core () ----===//
//
// The domain-separated agreementHash (model 1 of ): H(domain ‖
// semanticLanguageVersion ‖ canonicalCapabilitySpecBytes ‖
// canonicalAgreementEnvelopeBytes), with explicit big-endian length framing. It
// binds the frozen capability-spec's SEMANTIC bytes (the same
// canonicalSemanticBytes capabilityHash is computed from — so identity can
// never drift from the spec contract) to a versioned envelope carrying
// identity-level semantics absent from the spec. Ingestion from a verified view
// and from an external capability-spec produce byte-identical identity, and a
// tampered spec or an unknown identity-language version fails closed.
// MLIR-free; the view-based emitter wraps this in AgreementIdentityTarget.cpp.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/AgreementEnvelope.h"

#include "Neutrino/JsonUtil.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/Support/FormatVariadic.h"

#include <cstdint>

using namespace llvm;

namespace neutrino {

namespace {
Error agreementError(const Twine &msg) {
  return createStringError(inconvertibleErrorCode(),
                           "agreement identity: " + msg);
}

// frame(x) = BE64(byteLength(x)) ‖ x.
void appendFramed(std::string &out, StringRef field) {
  uint64_t n = field.size();
  for (int shift = 56; shift >= 0; shift -= 8)
    out.push_back(static_cast<char>((n >> shift) & 0xFF));
  out.append(field.data(), field.size());
}

// The compact canonical bytes of a capability-spec's SEMANTIC CORE, recovered
// from an external spec by removing the non-semantic keys (the same subset
// canonicalSemanticBytes omits), then VERIFIED against the spec's declared
// capabilityHash. Fails closed on a tampered / non-canonical spec.
Expected<std::string>
canonicalCapabilitySpecBytesFromSpec(const json::Object &spec) {
  json::Object core;
  for (const auto &kv : spec) {
    StringRef k = kv.first;
    if (k == "kind" || k == "schemaVersion" || k == "identity" ||
        k == "sourceMap" || k == "targetRequirements")
      continue;
    core[k] = kv.second;
  }
  std::string bytes = compactJson(json::Value(std::move(core)));
  const json::Object *id = spec.getObject("identity");
  Optional<StringRef> declared =
      id ? id->getString("capabilityHash") : Optional<StringRef>();
  if (!declared)
    return agreementError("capability-spec has no identity.capabilityHash");
  if (sha256Hex(bytes) != *declared)
    return agreementError(
        "capability-spec capabilityHash mismatch — its semantic core does not "
        "hash to the declared identity (tampered or non-canonical spec)");
  return bytes;
}

// Build the agreement-identity object over already-canonical capability bytes.
json::Object agreementIdentityObject(StringRef canonicalCapabilitySpecBytes) {
  json::Object envelope = agreementEnvelopeJson();
  std::string envelopeBytes = compactJson(json::Value(json::Object(envelope)));
  std::string agreementHash =
      agreementHashOf(canonicalCapabilitySpecBytes, envelopeBytes);
  return json::Object{
      {"kind", "neutrino.agreement-identity"},
      {"domain", kAgreementDomain},
      {"semanticLanguageVersion", kSemanticLanguageVersion},
      {"capabilityHash", sha256Hex(canonicalCapabilitySpecBytes)},
      {"envelope", std::move(envelope)},
      {"identity", json::Object{{"agreementHash", agreementHash}}}};
}
} // namespace

json::Object agreementEnvelopeJson() {
  // Identity-level semantics that live OUTSIDE the capability-spec. S1
  // defaults: no consent/amendment policy authored yet, no clause semantic IDs.
  // The schema is versioned so populating these later is an explicit,
  // hash-moving change.
  return json::Object{{"schemaVersion", kAgreementEnvelopeVersion},
                      {"consentPolicy", nullptr},
                      {"amendmentPolicy", nullptr},
                      {"clauseSemanticIds", json::Array{}}};
}

std::string agreementHashPreimage(StringRef domain,
                                  StringRef semanticLanguageVersion,
                                  StringRef canonicalCapabilitySpecBytes,
                                  StringRef canonicalAgreementEnvelopeBytes) {
  std::string preimage;
  appendFramed(preimage, domain);
  appendFramed(preimage, semanticLanguageVersion);
  appendFramed(preimage, canonicalCapabilitySpecBytes);
  appendFramed(preimage, canonicalAgreementEnvelopeBytes);
  return preimage;
}

std::string agreementHashOf(StringRef canonicalCapabilitySpecBytes,
                            StringRef canonicalAgreementEnvelopeBytes) {
  return sha256Hex(agreementHashPreimage(
      kAgreementDomain, kSemanticLanguageVersion, canonicalCapabilitySpecBytes,
      canonicalAgreementEnvelopeBytes));
}

std::string agreementIdentityFromBytes(StringRef canonicalCapabilitySpecBytes) {
  return formatv("{0:2}", json::Value(agreementIdentityObject(
                              canonicalCapabilitySpecBytes)))
             .str() +
         "\n";
}

Expected<std::string> agreementIdentityFromSpec(const json::Object &spec) {
  Expected<std::string> bytes = canonicalCapabilitySpecBytesFromSpec(spec);
  if (!bytes)
    return bytes.takeError();
  return agreementIdentityFromBytes(*bytes);
}

Error verifyAgreementIdentity(const json::Object &artifact,
                              const json::Object &capabilitySpec) {
  if (artifact.getString("domain").value_or("") != kAgreementDomain)
    return agreementError("unknown agreement domain");
  if (artifact.getString("semanticLanguageVersion").value_or("") !=
      kSemanticLanguageVersion)
    return agreementError("unknown semantic-language version");
  const json::Object *env = artifact.getObject("envelope");
  if (!env || env->getInteger("schemaVersion").value_or(-1) !=
                  kAgreementEnvelopeVersion)
    return agreementError("unknown agreement-envelope version");

  Expected<std::string> bytes =
      canonicalCapabilitySpecBytesFromSpec(capabilitySpec);
  if (!bytes)
    return bytes.takeError();
  if (artifact.getString("capabilityHash").value_or("") != sha256Hex(*bytes))
    return agreementError(
        "capabilityHash does not match the paired capability-spec");

  std::string envelopeBytes = compactJson(json::Value(json::Object(*env)));
  std::string recomputed = agreementHashOf(*bytes, envelopeBytes);
  const json::Object *id = artifact.getObject("identity");
  if (!id || id->getString("agreementHash").value_or("") != recomputed)
    return agreementError(
        "agreementHash does not recompute — the identity is inauthentic "
        "(tampered)");
  return Error::success();
}

} // namespace neutrino
