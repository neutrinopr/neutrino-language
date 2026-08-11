// SPDX-License-Identifier: Apache-2.0
//===- AgreementEnvelopeTest.cpp - portable agreement identity () -----===//
//
// Direct assertions on the MLIR-free identity core: the versioned envelope
// shape, the length-framed domain-separated preimage (non-vacuous framing), the
// digest's determinism + field sensitivity, and verifyAgreementIdentity failing
// closed on an unknown domain / language / envelope version and on a tampered
// capability-spec or agreementHash.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/AgreementEnvelope.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/Support/JSON.h"
#include "gtest/gtest.h"

using namespace neutrino;
using namespace llvm;

namespace {

// A minimal capability-spec with a correct identity.capabilityHash over the
// stripped semantic core (procedure + inputs).
json::Object validSpec() {
  json::Object core{{"procedure", "p"}, {"inputs", json::Array{}}};
  std::string bytes = compactJson(json::Value(json::Object(core)));
  json::Object spec = std::move(core);
  spec["kind"] = "neutrino.capability-spec";
  spec["schemaVersion"] = 1;
  spec["sourceMap"] = json::Array{}; // realization-only, must be stripped
  spec["identity"] = json::Object{{"capabilityHash", sha256Hex(bytes)}};
  return spec;
}

// Parse an agreement-identity artifact string back to an object.
json::Object parseArtifact(const std::string &s) {
  Expected<json::Value> v = json::parse(s);
  EXPECT_TRUE(static_cast<bool>(v));
  return *v->getAsObject();
}

// A valid (spec, artifact) pair.
std::pair<json::Object, json::Object> validPair() {
  json::Object spec = validSpec();
  Expected<std::string> art = agreementIdentityFromSpec(spec);
  EXPECT_TRUE(static_cast<bool>(art));
  return {std::move(spec), parseArtifact(*art)};
}

} // namespace

TEST(AgreementEnvelope, EnvelopeShapeIsVersionedAndEmptyByDefault) {
  json::Object e = agreementEnvelopeJson();
  EXPECT_EQ(e.getInteger("schemaVersion"), (int64_t)kAgreementEnvelopeVersion);
  EXPECT_TRUE(e.get("consentPolicy") && e.get("consentPolicy")->getAsNull());
  EXPECT_TRUE(e.get("amendmentPolicy") &&
              e.get("amendmentPolicy")->getAsNull());
  const json::Array *cl = e.getArray("clauseSemanticIds");
  ASSERT_TRUE(cl);
  EXPECT_TRUE(cl->empty());
}

TEST(AgreementEnvelope, LengthFramingIsUnambiguous) {
  // Without length framing, ("a" ‖ "bc") and ("ab" ‖ "c") would collide. The
  // BE64 length prefix separates them, so the preimages differ.
  EXPECT_NE(agreementHashPreimage("a", "bc", "", ""),
            agreementHashPreimage("ab", "c", "", ""));
  // The first framed field is BE64(len(domain)) ‖ domain.
  std::string p = agreementHashPreimage("neutrino", "v", "x", "y");
  ASSERT_GE(p.size(), 16u);
  // BE64 length of "neutrino" (8) -> the 8th byte is 8, earlier bytes 0.
  for (int i = 0; i < 7; ++i)
    EXPECT_EQ((unsigned char)p[i], 0u);
  EXPECT_EQ((unsigned char)p[7], 8u);
  EXPECT_EQ(p.substr(8, 8), "neutrino");
}

TEST(AgreementEnvelope, HashIsDeterministicAndFieldSensitive) {
  EXPECT_EQ(agreementHashOf("CAP", "ENV"), agreementHashOf("CAP", "ENV"));
  EXPECT_NE(agreementHashOf("CAP", "ENV"), agreementHashOf("CAP2", "ENV"));
  EXPECT_NE(agreementHashOf("CAP", "ENV"), agreementHashOf("CAP", "ENV2"));
  // 64-char lowercase hex.
  EXPECT_EQ(agreementHashOf("CAP", "ENV").size(), 64u);
}

TEST(AgreementEnvelope, VerifyRoundTripSucceeds) {
  auto [spec, artifact] = validPair();
  Error e = verifyAgreementIdentity(artifact, spec);
  EXPECT_FALSE(static_cast<bool>(e));
  consumeError(std::move(e));
}

TEST(AgreementEnvelope, VerifyUnknownDomainFailsClosed) {
  auto [spec, artifact] = validPair();
  artifact["domain"] = "neutrino.agreement.v999";
  Error e = verifyAgreementIdentity(artifact, spec);
  EXPECT_TRUE(static_cast<bool>(e));
  EXPECT_NE(toString(std::move(e)).find("unknown agreement domain"),
            std::string::npos);
}

TEST(AgreementEnvelope, VerifyUnknownLanguageVersionFailsClosed) {
  auto [spec, artifact] = validPair();
  artifact["semanticLanguageVersion"] = "99.0.0";
  Error e = verifyAgreementIdentity(artifact, spec);
  EXPECT_TRUE(static_cast<bool>(e));
  EXPECT_NE(toString(std::move(e)).find("unknown semantic-language version"),
            std::string::npos);
}

TEST(AgreementEnvelope, VerifyUnknownEnvelopeVersionFailsClosed) {
  auto [spec, artifact] = validPair();
  artifact.getObject("envelope")->operator[]("schemaVersion") = 99;
  Error e = verifyAgreementIdentity(artifact, spec);
  EXPECT_TRUE(static_cast<bool>(e));
  EXPECT_NE(toString(std::move(e)).find("unknown agreement-envelope version"),
            std::string::npos);
}

TEST(AgreementEnvelope, VerifyTamperedSpecFailsClosed) {
  auto [spec, artifact] = validPair();
  spec["procedure"] = "p_TAMPERED"; // semantic change, identity now stale
  Error e = verifyAgreementIdentity(artifact, spec);
  EXPECT_TRUE(static_cast<bool>(e));
  EXPECT_NE(toString(std::move(e)).find("capabilityHash mismatch"),
            std::string::npos);
}

TEST(AgreementEnvelope, VerifyTamperedAgreementHashFailsClosed) {
  auto [spec, artifact] = validPair();
  artifact.getObject("identity")->operator[]("agreementHash") =
      std::string(64, '0');
  Error e = verifyAgreementIdentity(artifact, spec);
  EXPECT_TRUE(static_cast<bool>(e));
  EXPECT_NE(toString(std::move(e)).find("does not recompute"),
            std::string::npos);
}

TEST(AgreementEnvelope, FromSpecFailsClosedOnCapabilityHashMismatch) {
  json::Object spec = validSpec();
  spec.getObject("identity")->operator[]("capabilityHash") =
      std::string(64, 'a'); // wrong declared hash
  Expected<std::string> art = agreementIdentityFromSpec(spec);
  EXPECT_FALSE(static_cast<bool>(art));
  EXPECT_NE(toString(art.takeError()).find("capabilityHash mismatch"),
            std::string::npos);
}
