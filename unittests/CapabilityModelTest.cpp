// SPDX-License-Identifier: Apache-2.0
#include "Neutrino/GenCapabilityModelSpec.h"

#include "gtest/gtest.h"

using namespace neutrino;

namespace {

backend_package::TargetProfile profile(llvm::StringRef target,
                                       llvm::StringRef digest) {
  backend_package::TargetProfile result;
  result.profileId = "target.profile." + target.str() + ".v1";
  result.schemaVersion = 1;
  result.kind = "neutrino.target-profile";
  result.profileVersion = 1;
  result.target = target.str();
  result.runtimeFamily = "off_chain";
  result.executionMode = "simulated";
  result.fallbackPolicy = "fail_closed";
  result.semanticProfileVersion = 3;
  result.supportedFeatures = {"effect:credit"};
  result.unsupportedConstructs = {"effect:debit"};
  result.semanticFeatures = {"effect:credit"};
  result.limits.maxEffects = 1;
  result.digest = digest.str();
  result.canonicalBytes =
      ("{\"capabilitySpecVersion\":\"v1\",\"executionMode\":\"simulated\","
       "\"fallbackPolicy\":\"fail_closed\",\"kind\":\"neutrino.target-"
       "profile\","
       "\"profileId\":\"" +
       result.profileId +
       "\",\"profileVersion\":1,\"runtimeFamily\":\"off_chain\","
       "\"schemaVersion\":1,\"semanticProfile\":{\"features\":[\"effect:"
       "credit\"],"
       "\"limits\":{\"maxAttestations\":0,\"maxComputes\":0,"
       "\"maxEffectGroups\":0,\"maxEffects\":1,\"maxExpressionDepth\":0,"
       "\"maxOperationSteps\":0},\"version\":3},\"supportedFeatures\":["
       "\"effect:credit\"],"
       "\"target\":\"" +
       result.target + "\",\"unsupportedConstructs\":[\"effect:debit\"]}");
  return result;
}

llvm::json::Object spec() {
  return llvm::json::Object{
      {"identity",
       llvm::json::Object{{"capabilityHash", std::string(64, 'a')}}},
      {"procedure", "sample"},
      {"specVersion", "1.0.0"},
  };
}

TEST(CapabilityModelTest, UsesOnlyProfileAndWitnessFacts) {
  std::vector<backend_package::TargetProfile> profiles{
      profile("alpha", "sha256:one"), profile("solidity", "sha256:two")};
  auto result =
      generateCapabilityModelsFromSpec(spec(), "sha256:catalog", profiles);
  ASSERT_TRUE(static_cast<bool>(result));
  ASSERT_EQ(result->size(), 2u);
  EXPECT_EQ((*result)[0].fileName, "target-616c706861.json");
  EXPECT_EQ((*result)[1].fileName, "solidity.json");
  EXPECT_NE((*result)[0].bytes.find("\"catalogIdentity\": \"sha256:catalog\""),
            std::string::npos);
  EXPECT_NE((*result)[0].bytes.find("\"digest\": \"sha256:one\""),
            std::string::npos);
  EXPECT_EQ((*result)[0].bytes.find("executionEnvironment"), std::string::npos);
  EXPECT_EQ((*result)[0].bytes.find("assurance"), std::string::npos);
  EXPECT_EQ((*result)[0].bytes.find("valueModel"), std::string::npos);
}

TEST(CapabilityModelTest, RefusesEmptyAndUnorderedCatalogs) {
  std::vector<backend_package::TargetProfile> empty;
  EXPECT_FALSE(
      generateCapabilityModelsFromSpec(spec(), "sha256:catalog", empty));
  std::vector<backend_package::TargetProfile> unordered{
      profile("zeta", "sha256:z"), profile("alpha", "sha256:a")};
  EXPECT_FALSE(
      generateCapabilityModelsFromSpec(spec(), "sha256:catalog", unordered));
}

TEST(CapabilityModelTest, ArtifactNamesAreTotalAndInjective) {
  EXPECT_EQ(capabilityModelArtifactName("solidity"), "solidity.json");
  EXPECT_EQ(capabilityModelArtifactName("postgres"), "postgres.json");
  EXPECT_EQ(capabilityModelArtifactName("../x"), "target-2e2e2f78.json");
  EXPECT_EQ(capabilityModelArtifactName("a/b"), "target-612f62.json");
  EXPECT_EQ(capabilityModelArtifactName("a\\b"), "target-615c62.json");
  EXPECT_EQ(capabilityModelArtifactName(u8"λ"), "target-cebb.json");
  EXPECT_NE(capabilityModelArtifactName("/"),
            capabilityModelArtifactName("2f"));
}

TEST(CapabilityModelTest, CatalogCompanionCarriesExactVerifiedProfiles) {
  std::vector<backend_package::TargetProfile> profiles{
      profile("alpha", "sha256:one")};
  auto bytes = capabilityModelCatalogBytes("sha256:catalog", profiles);
  ASSERT_TRUE(static_cast<bool>(bytes));
  auto parsed = llvm::json::parse(*bytes);
  ASSERT_TRUE(static_cast<bool>(parsed));
  const llvm::json::Object *root = parsed->getAsObject();
  ASSERT_NE(root, nullptr);
  ASSERT_TRUE(root->getString("catalogIdentity").hasValue());
  EXPECT_EQ(*root->getString("catalogIdentity"), "sha256:catalog");
  const llvm::json::Array *entries = root->getArray("profiles");
  ASSERT_NE(entries, nullptr);
  ASSERT_EQ(entries->size(), 1u);
  ASSERT_TRUE(entries->front().getAsObject()->getString("target").hasValue());
  EXPECT_EQ(*entries->front().getAsObject()->getString("target"), "alpha");

  profiles.front().canonicalBytes = "not-json";
  EXPECT_FALSE(capabilityModelCatalogBytes("sha256:catalog", profiles));
}

} // namespace
