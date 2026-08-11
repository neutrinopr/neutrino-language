#include "Neutrino/GenCapabilityModelSpec.h"

#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/Support/FormatVariadic.h"

#include <cstdint>
#include <set>

using namespace neutrino;

namespace {

llvm::json::Array strings(llvm::ArrayRef<std::string> values) {
  llvm::json::Array result;
  for (const std::string &value : values)
    result.push_back(value);
  return result;
}

llvm::json::Object
limits(const backend_package::TargetProfileLimits &profileLimits) {
  return llvm::json::Object{
      {"maxAttestations", static_cast<int64_t>(profileLimits.maxAttestations)},
      {"maxComputes", static_cast<int64_t>(profileLimits.maxComputes)},
      {"maxEffectGroups", static_cast<int64_t>(profileLimits.maxEffectGroups)},
      {"maxEffects", static_cast<int64_t>(profileLimits.maxEffects)},
      {"maxExpressionDepth",
       static_cast<int64_t>(profileLimits.maxExpressionDepth)},
      {"maxOperationSteps",
       static_cast<int64_t>(profileLimits.maxOperationSteps)},
  };
}

llvm::Expected<llvm::json::Object>
sourceWitness(const llvm::json::Object &spec) {
  llvm::Expected<llvm::StringRef> procedure =
      requiredString(spec, "procedure", "capability model");
  if (!procedure)
    return procedure.takeError();
  llvm::Expected<llvm::StringRef> specVersion =
      requiredString(spec, "specVersion", "capability model");
  if (!specVersion)
    return specVersion.takeError();
  llvm::Expected<const llvm::json::Object *> identity =
      requiredObject(spec, "identity", "capability model");
  if (!identity)
    return identity.takeError();
  llvm::Expected<llvm::StringRef> capabilityHash =
      requiredString(**identity, "capabilityHash", "capability model identity");
  if (!capabilityHash)
    return capabilityHash.takeError();
  return llvm::json::Object{
      {"capabilityHash", *capabilityHash},
      {"procedure", *procedure},
      {"specVersion", *specVersion},
  };
}

llvm::Expected<std::string>
model(const llvm::json::Object &spec, llvm::StringRef catalogIdentity,
      const backend_package::TargetProfile &profile) {
  llvm::Expected<llvm::json::Object> witness = sourceWitness(spec);
  if (!witness)
    return witness.takeError();
  llvm::json::Object root{
      {"catalogIdentity", catalogIdentity},
      {"kind", "neutrino.backend-capability-model"},
      {"modelVersion", "1.0.0"},
      {"package",
       llvm::json::Object{
           {"executionMode", profile.executionMode},
           {"fallbackPolicy", profile.fallbackPolicy},
           {"runtimeFamily", profile.runtimeFamily},
       }},
      {"semanticProfile",
       llvm::json::Object{
           {"features", strings(profile.semanticFeatures)},
           {"limits", limits(profile.limits)},
           {"version", static_cast<int64_t>(profile.semanticProfileVersion)},
       }},
      {"sourceCapabilityWitness", std::move(*witness)},
      {"supportedFeatures", strings(profile.supportedFeatures)},
      {"target", profile.target},
      {"targetProfile",
       llvm::json::Object{
           {"digest", profile.digest},
           {"identity", profile.profileId},
           {"version", static_cast<int64_t>(profile.profileVersion)},
       }},
      {"unsupportedConstructs", strings(profile.unsupportedConstructs)},
  };
  return llvm::formatv("{0:2}\n", llvm::json::Value(std::move(root))).str();
}

} // namespace

std::string neutrino::capabilityModelArtifactName(llvm::StringRef target) {
  if (target == "solidity" || target == "postgres")
    return (target + ".json").str();
  constexpr char hex[] = "0123456789abcdef";
  std::string result = "target-";
  result.reserve(result.size() + target.size() * 2 + 5);
  for (unsigned char byte : target.bytes()) {
    result.push_back(hex[byte >> 4]);
    result.push_back(hex[byte & 0x0f]);
  }
  result += ".json";
  return result;
}

llvm::Expected<std::string> neutrino::capabilityModelCatalogBytes(
    llvm::StringRef catalogIdentity,
    llvm::ArrayRef<backend_package::TargetProfile> profiles) {
  llvm::json::Array entries;
  for (const backend_package::TargetProfile &profile : profiles) {
    llvm::Expected<llvm::json::Value> parsed =
        llvm::json::parse(profile.canonicalBytes);
    if (!parsed || !parsed->getAsObject())
      return llvm::make_error<llvm::StringError>(
          "capability.catalog.profile: verified profile bytes are invalid",
          llvm::inconvertibleErrorCode());
    entries.push_back(std::move(*parsed));
  }
  llvm::json::Object root{
      {"catalogIdentity", catalogIdentity},
      {"kind", "neutrino.verified-target-profile-catalog/1"},
      {"profiles", std::move(entries)},
  };
  return llvm::formatv("{0:2}\n", llvm::json::Value(std::move(root))).str();
}

llvm::Expected<std::vector<CapabilityModelArtifact>>
neutrino::generateCapabilityModelsFromSpec(
    const llvm::json::Object &spec, llvm::StringRef catalogIdentity,
    llvm::ArrayRef<backend_package::TargetProfile> profiles) {
  if (profiles.empty())
    return llvm::make_error<llvm::StringError>(
        "capability.catalog.empty: no verified external target profiles",
        llvm::inconvertibleErrorCode());
  if (!llvm::is_sorted(profiles, [](const auto &left, const auto &right) {
        return left.target < right.target;
      }))
    return llvm::make_error<llvm::StringError>(
        "capability.catalog.order: verified profiles are not target-sorted",
        llvm::inconvertibleErrorCode());

  std::vector<CapabilityModelArtifact> result;
  result.reserve(profiles.size());
  std::set<std::string> fileNames;
  for (const backend_package::TargetProfile &profile : profiles) {
    std::string fileName = capabilityModelArtifactName(profile.target);
    if (!fileNames.insert(fileName).second)
      return llvm::make_error<llvm::StringError>(
          "capability.catalog.collision: artifact-name collision",
          llvm::inconvertibleErrorCode());
    llvm::Expected<std::string> bytes = model(spec, catalogIdentity, profile);
    if (!bytes)
      return bytes.takeError();
    result.push_back({std::move(fileName), std::move(*bytes)});
  }
  return result;
}
