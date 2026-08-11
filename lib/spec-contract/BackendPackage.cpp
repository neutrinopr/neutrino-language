#include "Neutrino/BackendPackage.h"

#include "Neutrino/JsonUtil.h"
#include "Neutrino/SemanticRequirements.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/SmallString.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/ADT/Twine.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iterator>
#include <limits>
#include <map>
#include <regex>
#include <set>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>

namespace neutrino {
namespace backend_package {
namespace {

using llvm::StringRef;
namespace json = llvm::json;

constexpr StringRef kInvalidDescriptor = "E_PACKAGE_DESCRIPTOR";
constexpr StringRef kManifestMismatch = "E_PACKAGE_MANIFEST_DIGEST";
constexpr StringRef kClosureMismatch = "E_PACKAGE_CLOSURE";
constexpr StringRef kInvalidPath = "E_PACKAGE_PATH";
constexpr StringRef kNonRegularFile = "E_PACKAGE_FILE_TYPE";
constexpr StringRef kEntryUnbound = "E_PACKAGE_ENTRY";
constexpr StringRef kIncompatibleVersion = "E_VERSION";
constexpr StringRef kProjectionSchema = "E_PROJECTION_SCHEMA";
constexpr StringRef kDuplicatePackage = "E_PACKAGE_DUPLICATE";
constexpr StringRef kDuplicateTarget = "E_TARGET_DUPLICATE";
constexpr StringRef kInvalidProfile = "E_PACKAGE_PROFILE";
constexpr StringRef kDuplicateProfile = "E_PROFILE_DUPLICATE";
constexpr StringRef kPackageIo = "E_PACKAGE_IO";

llvm::Error packageError(StringRef code, const llvm::Twine &message) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine(code) + ": " + message).str(),
      llvm::inconvertibleErrorCode());
}

bool isLowerHexDigest(StringRef digest) {
  if (!digest.consume_front("sha256:") || digest.size() != 64)
    return false;
  return llvm::all_of(digest, [](char value) {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
  });
}

llvm::Error requireExactFields(const json::Object &object,
                               std::initializer_list<StringRef> fields,
                               StringRef context, StringRef code) {
  std::set<std::string> expected;
  for (StringRef field : fields)
    expected.insert(field.str());
  for (const auto &entry : object) {
    if (!expected.erase(entry.first.str()))
      return packageError(code, llvm::Twine(context) + ": unknown field " +
                                    entry.first.str());
  }
  if (!expected.empty())
    return packageError(code, llvm::Twine(context) + ": missing field " +
                                  *expected.begin());
  return llvm::Error::success();
}

llvm::Expected<uint32_t> profileU32(const json::Object &object, StringRef field,
                                    StringRef context, bool positive = false) {
  llvm::Optional<int64_t> value = object.getInteger(field);
  if (!value || *value < (positive ? 1 : 0) ||
      static_cast<uint64_t>(*value) > std::numeric_limits<uint32_t>::max())
    return packageError(kInvalidProfile,
                        llvm::Twine(context) + ": missing/invalid " + field);
  return static_cast<uint32_t>(*value);
}

llvm::Expected<uint64_t> profileU64(const json::Object &object, StringRef field,
                                    StringRef context) {
  llvm::Optional<int64_t> value = object.getInteger(field);
  if (!value || *value < 0)
    return packageError(kInvalidProfile,
                        llvm::Twine(context) + ": missing/invalid " + field);
  return static_cast<uint64_t>(*value);
}

llvm::Expected<std::string> profileString(const json::Object &object,
                                          StringRef field, StringRef context) {
  llvm::Optional<StringRef> value = object.getString(field);
  if (!value || value->empty())
    return packageError(kInvalidProfile,
                        llvm::Twine(context) + ": missing/invalid " + field);
  return value->str();
}

bool isFeature(StringRef feature) {
  static const std::regex pattern("^[a-z][a-z_]*:[a-z][a-z0-9_]*$");
  return std::regex_match(feature.str(), pattern);
}

llvm::Expected<std::vector<std::string>>
profileStrings(const json::Object &object, StringRef field, StringRef context,
               bool closedSemanticVocabulary) {
  const json::Array *array = object.getArray(field);
  if (!array)
    return packageError(kInvalidProfile,
                        llvm::Twine(context) + ": missing/invalid " + field);
  std::vector<std::string> result;
  for (const json::Value &entry : *array) {
    llvm::Optional<StringRef> value = entry.getAsString();
    if (!value || !isFeature(*value))
      return packageError(kInvalidProfile,
                          llvm::Twine(context) + ": invalid " + field);
    if (closedSemanticVocabulary &&
        !knownSemanticFeatures().count(value->str()))
      return packageError(kInvalidProfile, llvm::Twine(context) +
                                               ": unknown semantic feature " +
                                               *value);
    result.push_back(value->str());
  }
  if (!llvm::is_sorted(result) ||
      std::adjacent_find(result.begin(), result.end()) != result.end())
    return packageError(kInvalidProfile,
                        llvm::Twine(context) + ": " + field +
                            " must be unique and lexicographically ordered");
  return result;
}

llvm::Expected<TargetProfile>
parseTargetProfile(const json::Object &object, StringRef targetIdentity,
                   StringRef targetProfileIdentity) {
  if (llvm::Error error = requireExactFields(
          object,
          {"schemaVersion", "kind", "profileId", "profileVersion", "target",
           "runtimeFamily", "executionMode", "supportedFeatures",
           "unsupportedConstructs", "fallbackPolicy", "capabilitySpecVersion",
           "semanticProfile"},
          "profileSummary", kInvalidProfile))
    return std::move(error);

  TargetProfile profile;
  llvm::Expected<uint32_t> schema =
      profileU32(object, "schemaVersion", "profileSummary", true);
  if (!schema)
    return schema.takeError();
  if (*schema != 1)
    return packageError(kInvalidProfile,
                        "profileSummary schemaVersion must equal 1");
  profile.schemaVersion = *schema;

  llvm::Expected<std::string> kind =
      profileString(object, "kind", "profileSummary");
  if (!kind)
    return kind.takeError();
  if (*kind != "neutrino.target-profile")
    return packageError(kInvalidProfile,
                        "profileSummary kind is not neutrino.target-profile");
  profile.kind = std::move(*kind);

  llvm::Expected<std::string> profileId =
      profileString(object, "profileId", "profileSummary");
  if (!profileId)
    return profileId.takeError();
  llvm::Expected<uint32_t> profileVersion =
      profileU32(object, "profileVersion", "profileSummary", true);
  if (!profileVersion)
    return profileVersion.takeError();
  static const std::regex profileIdPattern(
      "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+\\.v([0-9]+)$");
  std::smatch match;
  uint64_t idVersion = 0;
  std::string idVersionText;
  bool profileIdMatches = std::regex_match(*profileId, match, profileIdPattern);
  if (profileIdMatches && match.size() == 3)
    idVersionText = match[2].str();
  if (!profileIdMatches || match.size() != 3 ||
      StringRef(idVersionText).getAsInteger(10, idVersion) ||
      idVersion != *profileVersion)
    return packageError(
        kInvalidProfile,
        "profileSummary profileId is invalid or disagrees with profileVersion");
  if (*profileId != targetProfileIdentity)
    return packageError(
        kInvalidProfile,
        "profileSummary profileId does not match targetProfileIdentity");
  profile.profileId = std::move(*profileId);
  profile.profileVersion = *profileVersion;

  llvm::Expected<std::string> target =
      profileString(object, "target", "profileSummary");
  if (!target)
    return target.takeError();
  if (*target != targetIdentity)
    return packageError(kInvalidProfile,
                        "profileSummary target does not match targetIdentity");
  profile.target = std::move(*target);

  llvm::Expected<std::string> runtime =
      profileString(object, "runtimeFamily", "profileSummary");
  if (!runtime)
    return runtime.takeError();
  if (*runtime != "on_chain" && *runtime != "relational" &&
      *runtime != "off_chain")
    return packageError(kInvalidProfile,
                        "profileSummary runtimeFamily is unknown");
  profile.runtimeFamily = std::move(*runtime);

  llvm::Expected<std::string> execution =
      profileString(object, "executionMode", "profileSummary");
  if (!execution)
    return execution.takeError();
  if (*execution != "deterministic" && *execution != "simulated" &&
      *execution != "real")
    return packageError(kInvalidProfile,
                        "profileSummary executionMode is unknown");
  profile.executionMode = std::move(*execution);

  llvm::Expected<std::vector<std::string>> supported =
      profileStrings(object, "supportedFeatures", "profileSummary", false);
  if (!supported)
    return supported.takeError();
  profile.supportedFeatures = std::move(*supported);
  llvm::Expected<std::vector<std::string>> unsupported =
      profileStrings(object, "unsupportedConstructs", "profileSummary", false);
  if (!unsupported)
    return unsupported.takeError();
  profile.unsupportedConstructs = std::move(*unsupported);
  std::vector<std::string> intersection;
  std::set_intersection(
      profile.supportedFeatures.begin(), profile.supportedFeatures.end(),
      profile.unsupportedConstructs.begin(),
      profile.unsupportedConstructs.end(), std::back_inserter(intersection));
  if (!intersection.empty())
    return packageError(
        kInvalidProfile,
        "profileSummary supported and unsupported features overlap");

  llvm::Expected<std::string> fallback =
      profileString(object, "fallbackPolicy", "profileSummary");
  if (!fallback)
    return fallback.takeError();
  if (*fallback != "fail_closed" && *fallback != "advisory")
    return packageError(kInvalidProfile,
                        "profileSummary fallbackPolicy is unknown");
  profile.fallbackPolicy = std::move(*fallback);

  llvm::Expected<std::string> capabilityVersion =
      profileString(object, "capabilitySpecVersion", "profileSummary");
  if (!capabilityVersion)
    return capabilityVersion.takeError();
  if (*capabilityVersion != kCapabilitySpecVersion)
    return packageError(kInvalidProfile,
                        "profileSummary capabilitySpecVersion is incompatible");
  profile.capabilitySpecVersion = std::move(*capabilityVersion);

  const json::Object *semantic = object.getObject("semanticProfile");
  if (!semantic)
    return packageError(kInvalidProfile,
                        "profileSummary semanticProfile must be an object");
  if (llvm::Error error =
          requireExactFields(*semantic, {"version", "features", "limits"},
                             "semanticProfile", kInvalidProfile))
    return std::move(error);
  llvm::Expected<uint32_t> semanticVersion =
      profileU32(*semantic, "version", "semanticProfile", true);
  if (!semanticVersion)
    return semanticVersion.takeError();
  if (*semanticVersion != static_cast<uint32_t>(kSemanticProfileVersion))
    return packageError(kInvalidProfile,
                        "semanticProfile version is incompatible");
  profile.semanticProfileVersion = *semanticVersion;
  llvm::Expected<std::vector<std::string>> semanticFeatures =
      profileStrings(*semantic, "features", "semanticProfile", true);
  if (!semanticFeatures)
    return semanticFeatures.takeError();
  profile.semanticFeatures = std::move(*semanticFeatures);

  const json::Object *limits = semantic->getObject("limits");
  if (!limits)
    return packageError(kInvalidProfile,
                        "semanticProfile limits must be an object");
  if (llvm::Error error = requireExactFields(
          *limits,
          {"maxExpressionDepth", "maxEffects", "maxEffectGroups",
           "maxAttestations", "maxComputes", "maxOperationSteps"},
          "semanticProfile limits", kInvalidProfile))
    return std::move(error);
#define READ_PROFILE_LIMIT(Member, Field)                                      \
  do {                                                                         \
    llvm::Expected<uint64_t> value =                                           \
        profileU64(*limits, Field, "semanticProfile limits");                  \
    if (!value)                                                                \
      return value.takeError();                                                \
    profile.limits.Member = *value;                                            \
  } while (false)
  READ_PROFILE_LIMIT(maxExpressionDepth, "maxExpressionDepth");
  READ_PROFILE_LIMIT(maxEffects, "maxEffects");
  READ_PROFILE_LIMIT(maxEffectGroups, "maxEffectGroups");
  READ_PROFILE_LIMIT(maxAttestations, "maxAttestations");
  READ_PROFILE_LIMIT(maxComputes, "maxComputes");
  READ_PROFILE_LIMIT(maxOperationSteps, "maxOperationSteps");
#undef READ_PROFILE_LIMIT

  json::Object copy = object;
  profile.canonicalBytes = compactJson(json::Value(std::move(copy)));
  profile.digest = "sha256:" + sha256Hex(profile.canonicalBytes);
  return profile;
}

llvm::Expected<uint32_t> requiredU32(const json::Object &object,
                                     StringRef field, StringRef context) {
  llvm::Optional<int64_t> value = object.getInteger(field);
  if (!value || *value < 0 ||
      static_cast<uint64_t>(*value) > std::numeric_limits<uint32_t>::max())
    return packageError(kInvalidDescriptor,
                        llvm::Twine(context) + ": missing/invalid " + field);
  return static_cast<uint32_t>(*value);
}

llvm::Expected<uint64_t> requiredU64(const json::Object &object,
                                     StringRef field, StringRef context) {
  llvm::Optional<int64_t> value = object.getInteger(field);
  if (!value || *value < 0)
    return packageError(kInvalidDescriptor,
                        llvm::Twine(context) + ": missing/invalid " + field);
  return static_cast<uint64_t>(*value);
}

llvm::Expected<std::string> requiredNonemptyString(const json::Object &object,
                                                   StringRef field,
                                                   StringRef context) {
  llvm::Optional<StringRef> value = object.getString(field);
  if (!value || value->empty())
    return packageError(kInvalidDescriptor,
                        llvm::Twine(context) + ": missing/invalid " + field);
  return value->str();
}

llvm::Error validateRelativePath(StringRef path) {
  if (path.empty() || path.size() > 4096 || path.startswith("/") ||
      path.endswith("/") || path.contains('\0') || path.contains('\\'))
    return packageError(kInvalidPath, "invalid relative package path");
  while (!path.empty()) {
    std::pair<StringRef, StringRef> split = path.split('/');
    if (split.first.empty() || split.first == "." || split.first == "..")
      return packageError(kInvalidPath, "invalid relative package path");
    path = split.second;
  }
  return llvm::Error::success();
}

llvm::Expected<ProtocolVersion> parseProtocolVersion(const json::Object &object,
                                                     StringRef context) {
  ProtocolVersion version;
  llvm::Expected<uint32_t> major = requiredU32(object, "major", context);
  if (!major)
    return major.takeError();
  version.major = *major;
  llvm::Expected<uint32_t> minor = requiredU32(object, "minor", context);
  if (!minor)
    return minor.takeError();
  version.minor = *minor;
  return version;
}

int compareVersions(const ProtocolVersion &left, const ProtocolVersion &right) {
  if (left.major != right.major)
    return left.major < right.major ? -1 : 1;
  if (left.minor != right.minor)
    return left.minor < right.minor ? -1 : 1;
  return 0;
}

llvm::Error validateCompatibility(const Descriptor &descriptor,
                                  const Compatibility &compatibility) {
  const CompatibilityBounds &bounds = descriptor.compatibilityBounds;
  if (compareVersions(bounds.coreProtocol.min, bounds.coreProtocol.max) > 0 ||
      bounds.projectionSchema.min > bounds.projectionSchema.max)
    return packageError(kInvalidDescriptor,
                        "compatibility range has min greater than max");

  if (descriptor.protocolMajor != compatibility.coreProtocol.major ||
      compareVersions(compatibility.coreProtocol, bounds.coreProtocol.min) <
          0 ||
      compareVersions(compatibility.coreProtocol, bounds.coreProtocol.max) >
          0 ||
      descriptor.apiVersion != compatibility.apiVersion)
    return packageError(kIncompatibleVersion,
                        "package is incompatible with this core");
  if (compatibility.projectionSchema < bounds.projectionSchema.min ||
      compatibility.projectionSchema > bounds.projectionSchema.max)
    return packageError(kProjectionSchema,
                        "package does not accept this projection schema");
  return llvm::Error::success();
}

class NativeFileHandle final : public PackageFileHandle {
public:
  NativeFileHandle(PackageFileKind kind, std::string bytes,
                   std::string identity, int descriptor = -1)
      : Kind(kind), Bytes(std::move(bytes)), Identity(std::move(identity)),
        Descriptor(descriptor) {}

  ~NativeFileHandle() override {
    if (Descriptor >= 0)
      ::close(Descriptor);
  }

  PackageFileKind kind() const override { return Kind; }
  StringRef bytes() const override { return Bytes; }
  StringRef identity() const override { return Identity; }

private:
  PackageFileKind Kind;
  std::string Bytes;
  std::string Identity;
  int Descriptor;
};

std::unique_ptr<PackageFileHandle> metadataHandle(PackageFileKind kind,
                                                  StringRef identity) {
  return std::make_unique<NativeFileHandle>(kind, std::string(),
                                            identity.str());
}

llvm::Expected<int> openPackageDirectory(StringRef packageDirectory) {
  std::string path = packageDirectory.str();
  int descriptor =
      ::open(path.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0)
    return packageError(kPackageIo,
                        llvm::Twine("cannot open package directory ") +
                            packageDirectory + ": " + std::strerror(errno));
  return descriptor;
}

llvm::Expected<std::unique_ptr<PackageFileHandle>>
openRelativeNoFollow(StringRef packageDirectory, StringRef relativePath) {
  if (llvm::Error error = validateRelativePath(relativePath))
    return std::move(error);

  llvm::Expected<int> root = openPackageDirectory(packageDirectory);
  if (!root)
    return root.takeError();
  int current = *root;
  StringRef remaining = relativePath;
  while (true) {
    std::pair<StringRef, StringRef> split = remaining.split('/');
    bool final = split.second.empty();
    std::string component = split.first.str();
    int flags = O_RDONLY | O_CLOEXEC | O_NOFOLLOW;
    if (!final)
      flags |= O_DIRECTORY;
    int next = ::openat(current, component.c_str(), flags);
    int savedErrno = errno;
    ::close(current);
    if (next < 0) {
      if (savedErrno == ELOOP)
        return metadataHandle(PackageFileKind::Symlink, relativePath);
      if (savedErrno == ENOENT)
        return metadataHandle(PackageFileKind::Missing, relativePath);
      if (savedErrno == ENOTDIR)
        return metadataHandle(PackageFileKind::Other, relativePath);
      return packageError(kPackageIo, llvm::Twine("cannot open package file ") +
                                          relativePath + ": " +
                                          std::strerror(savedErrno));
    }
    if (!final) {
      current = next;
      remaining = split.second;
      continue;
    }

    struct stat status {};
    if (::fstat(next, &status) != 0) {
      int errorNumber = errno;
      ::close(next);
      return packageError(kPackageIo,
                          llvm::Twine("cannot inspect package file ") +
                              relativePath + ": " + std::strerror(errorNumber));
    }
    if (!S_ISREG(status.st_mode)) {
      ::close(next);
      return metadataHandle(PackageFileKind::Other, relativePath);
    }

    std::string bytes;
    if (status.st_size > 0)
      bytes.reserve(static_cast<size_t>(status.st_size));
    char buffer[16384];
    while (true) {
      ssize_t count = ::read(next, buffer, sizeof(buffer));
      if (count == 0)
        break;
      if (count < 0) {
        if (errno == EINTR)
          continue;
        int errorNumber = errno;
        ::close(next);
        return packageError(
            kPackageIo, llvm::Twine("cannot read package file ") +
                            relativePath + ": " + std::strerror(errorNumber));
      }
      bytes.append(buffer, static_cast<size_t>(count));
    }
    if (::lseek(next, 0, SEEK_SET) < 0) {
      int errorNumber = errno;
      ::close(next);
      return packageError(kPackageIo,
                          llvm::Twine("cannot rewind package file ") +
                              relativePath + ": " + std::strerror(errorNumber));
    }
    std::string identity =
        (llvm::Twine(static_cast<uint64_t>(status.st_dev)) + ":" +
         llvm::Twine(static_cast<uint64_t>(status.st_ino)))
            .str();
    return std::make_unique<NativeFileHandle>(
        PackageFileKind::Regular, std::move(bytes), std::move(identity), next);
  }
}

class NativePackageFilesystem final : public PackageFilesystem {
public:
  llvm::Expected<std::unique_ptr<PackageFileHandle>>
  openNoFollow(StringRef packageDirectory,
               StringRef relativePath) const override {
    return openRelativeNoFollow(packageDirectory, relativePath);
  }
};

llvm::Error requireRegular(const PackageFileHandle &file, StringRef path,
                           StringRef missingCode = kClosureMismatch) {
  switch (file.kind()) {
  case PackageFileKind::Regular:
    return llvm::Error::success();
  case PackageFileKind::Symlink:
    return packageError(kNonRegularFile, llvm::Twine(path) + " is a symlink");
  case PackageFileKind::Other:
    return packageError(kNonRegularFile,
                        llvm::Twine(path) + " is not a regular file");
  case PackageFileKind::Missing:
    return packageError(missingCode, llvm::Twine(path) + " is missing");
  }
  return packageError(kNonRegularFile,
                      llvm::Twine(path) + " has an unknown file kind");
}

} // namespace

std::unique_ptr<PackageFilesystem> createNativePackageFilesystem() {
  return std::make_unique<NativePackageFilesystem>();
}

llvm::Expected<Descriptor> parseDescriptor(StringRef bytes) {
  llvm::Expected<json::Value> parsed = json::parse(bytes);
  if (!parsed)
    return packageError(kInvalidDescriptor,
                        llvm::Twine("malformed JSON: ") +
                            llvm::toString(parsed.takeError()));
  json::Object *object = parsed->getAsObject();
  if (!object)
    return packageError(kInvalidDescriptor, "top level must be an object");
  if (compactJson(*parsed) != bytes)
    return packageError(kInvalidDescriptor,
                        "descriptor must use canonical JSON encoding");

  llvm::Expected<std::string> kind =
      requiredNonemptyString(*object, "kind", "package descriptor");
  if (!kind)
    return kind.takeError();
  if (*kind != kDescriptorKind)
    return packageError(kIncompatibleVersion,
                        llvm::Twine("unsupported descriptor kind ") + *kind);

  Descriptor descriptor;
  llvm::Expected<std::string> manifestDigest =
      requiredNonemptyString(*object, "manifestDigest", "package descriptor");
  if (!manifestDigest)
    return manifestDigest.takeError();
  if (!isLowerHexDigest(*manifestDigest))
    return packageError(kInvalidDescriptor,
                        "manifestDigest must be lowercase sha256");
  descriptor.manifestDigest = *manifestDigest;
  object->erase("manifestDigest");
  std::string computed = "sha256:" + sha256Hex(compactJson(*parsed));
  if (computed != descriptor.manifestDigest)
    return packageError(kManifestMismatch,
                        "descriptor manifestDigest does not match");

  llvm::Expected<std::string> targetIdentity =
      requiredNonemptyString(*object, "targetIdentity", "package descriptor");
  if (!targetIdentity)
    return targetIdentity.takeError();
  descriptor.targetIdentity = std::move(*targetIdentity);
  llvm::Expected<uint32_t> protocolMajor =
      requiredU32(*object, "protocolMajor", "package descriptor");
  if (!protocolMajor)
    return protocolMajor.takeError();
  descriptor.protocolMajor = *protocolMajor;
  llvm::Expected<uint32_t> protocolMinor =
      requiredU32(*object, "protocolMinor", "package descriptor");
  if (!protocolMinor)
    return protocolMinor.takeError();
  descriptor.protocolMinor = *protocolMinor;
  llvm::Expected<uint32_t> apiVersion =
      requiredU32(*object, "apiVersion", "package descriptor");
  if (!apiVersion)
    return apiVersion.takeError();
  descriptor.apiVersion = *apiVersion;
  llvm::Expected<std::string> profile = requiredNonemptyString(
      *object, "targetProfileIdentity", "package descriptor");
  if (!profile)
    return profile.takeError();
  descriptor.targetProfileIdentity = std::move(*profile);
  llvm::Expected<std::string> entry =
      requiredNonemptyString(*object, "entry", "package descriptor");
  if (!entry)
    return entry.takeError();
  if (llvm::Error error = validateRelativePath(*entry))
    return std::move(error);
  descriptor.entry = std::move(*entry);
  llvm::Expected<std::string> license =
      requiredNonemptyString(*object, "licenseIdentity", "package descriptor");
  if (!license)
    return license.takeError();
  descriptor.licenseIdentity = std::move(*license);

  const json::Array *capabilities = object->getArray("capabilities");
  if (!capabilities)
    return packageError(kInvalidDescriptor,
                        "package descriptor: missing/invalid capabilities");
  std::set<std::string> seenCapabilities;
  for (size_t index = 0; index < capabilities->size(); ++index) {
    llvm::Optional<StringRef> value = (*capabilities)[index].getAsString();
    if (!value || value->empty() ||
        !seenCapabilities.insert(value->str()).second)
      return packageError(kInvalidDescriptor,
                          "capabilities must be unique nonempty strings");
    descriptor.capabilities.push_back(value->str());
  }

  const json::Object *profileSummary = object->getObject("profileSummary");
  if (!profileSummary)
    return packageError(kInvalidDescriptor,
                        "package descriptor: missing/invalid profileSummary");
  llvm::Expected<TargetProfile> parsedProfile =
      parseTargetProfile(*profileSummary, descriptor.targetIdentity,
                         descriptor.targetProfileIdentity);
  if (!parsedProfile)
    return parsedProfile.takeError();
  descriptor.profileSummary = std::move(*parsedProfile);

  const json::Object *bounds = object->getObject("compatibilityBounds");
  if (!bounds)
    return packageError(
        kInvalidDescriptor,
        "package descriptor: missing/invalid compatibilityBounds");
  const json::Object *coreProtocol = bounds->getObject("coreProtocol");
  const json::Object *projectionSchema = bounds->getObject("projectionSchema");
  if (!coreProtocol || !projectionSchema)
    return packageError(kInvalidDescriptor,
                        "compatibilityBounds is missing a required range");
  const json::Object *protocolMin = coreProtocol->getObject("min");
  const json::Object *protocolMax = coreProtocol->getObject("max");
  if (!protocolMin || !protocolMax)
    return packageError(kInvalidDescriptor, "coreProtocol is missing min/max");
  llvm::Expected<ProtocolVersion> minVersion =
      parseProtocolVersion(*protocolMin, "coreProtocol.min");
  if (!minVersion)
    return minVersion.takeError();
  descriptor.compatibilityBounds.coreProtocol.min = *minVersion;
  llvm::Expected<ProtocolVersion> maxVersion =
      parseProtocolVersion(*protocolMax, "coreProtocol.max");
  if (!maxVersion)
    return maxVersion.takeError();
  descriptor.compatibilityBounds.coreProtocol.max = *maxVersion;
  llvm::Expected<uint32_t> schemaMin =
      requiredU32(*projectionSchema, "min", "projectionSchema");
  if (!schemaMin)
    return schemaMin.takeError();
  descriptor.compatibilityBounds.projectionSchema.min = *schemaMin;
  llvm::Expected<uint32_t> schemaMax =
      requiredU32(*projectionSchema, "max", "projectionSchema");
  if (!schemaMax)
    return schemaMax.takeError();
  descriptor.compatibilityBounds.projectionSchema.max = *schemaMax;

  const json::Array *closure = object->getArray("closure");
  if (!closure || closure->empty())
    return packageError(kInvalidDescriptor,
                        "package descriptor closure must be nonempty");
  std::string previousPath;
  for (size_t index = 0; index < closure->size(); ++index) {
    const json::Object *entryObject = (*closure)[index].getAsObject();
    if (!entryObject)
      return packageError(kInvalidDescriptor,
                          "closure entry must be an object");
    ClosureEntry closureEntry;
    llvm::Expected<std::string> path =
        requiredNonemptyString(*entryObject, "path", "closure entry");
    if (!path)
      return path.takeError();
    if (llvm::Error error = validateRelativePath(*path))
      return std::move(error);
    closureEntry.path = std::move(*path);
    if (!previousPath.empty() && previousPath >= closureEntry.path)
      return packageError(
          kInvalidDescriptor,
          "closure paths must be unique and lexicographically ordered");
    previousPath = closureEntry.path;
    llvm::Expected<std::string> digest =
        requiredNonemptyString(*entryObject, "sha256", "closure entry");
    if (!digest)
      return digest.takeError();
    if (!isLowerHexDigest(*digest))
      return packageError(kInvalidDescriptor,
                          "closure sha256 must be lowercase");
    closureEntry.sha256 = std::move(*digest);
    llvm::Expected<uint64_t> byteLen =
        requiredU64(*entryObject, "byteLen", "closure entry");
    if (!byteLen)
      return byteLen.takeError();
    closureEntry.byteLen = *byteLen;
    descriptor.closure.push_back(std::move(closureEntry));
  }

  return descriptor;
}

llvm::Expected<VerifiedPackage>
verifyPackage(StringRef packageDirectory, const Compatibility &compatibility,
              const PackageFilesystem &filesystem) {
  llvm::Expected<std::unique_ptr<PackageFileHandle>> descriptorFile =
      filesystem.openNoFollow(packageDirectory, kDescriptorFileName);
  if (!descriptorFile)
    return descriptorFile.takeError();
  if (llvm::Error error = requireRegular(**descriptorFile, kDescriptorFileName,
                                         kInvalidDescriptor))
    return std::move(error);

  llvm::Expected<Descriptor> descriptor =
      parseDescriptor((*descriptorFile)->bytes());
  if (!descriptor)
    return descriptor.takeError();
  if (llvm::Error error = validateCompatibility(*descriptor, compatibility))
    return std::move(error);

  VerifiedPackage package;
  package.PackageDirectory = packageDirectory.str();
  package.PackageDescriptor = std::move(*descriptor);
  package.DescriptorFile = std::move(*descriptorFile);
  bool foundEntry = false;
  for (const ClosureEntry &manifest : package.PackageDescriptor.closure) {
    llvm::Expected<std::unique_ptr<PackageFileHandle>> file =
        filesystem.openNoFollow(packageDirectory, manifest.path);
    if (!file)
      return file.takeError();
    if (llvm::Error error = requireRegular(**file, manifest.path))
      return std::move(error);
    if ((*file)->bytes().size() != manifest.byteLen ||
        "sha256:" + sha256Hex((*file)->bytes()) != manifest.sha256)
      return packageError(kClosureMismatch,
                          llvm::Twine(manifest.path) +
                              " length or digest does not match");
    if (manifest.path == package.PackageDescriptor.entry) {
      package.EntryIndex = package.Closure.size();
      foundEntry = true;
    }
    package.Closure.push_back({manifest, std::move(*file)});
  }
  if (!foundEntry)
    return packageError(kEntryUnbound,
                        "entry is not bound to an exact closure file");
  return package;
}

llvm::Expected<std::vector<VerifiedPackage>>
discoverPackages(llvm::ArrayRef<std::string> configuredPackageDirectories,
                 const Compatibility &compatibility,
                 const PackageFilesystem &filesystem) {
  std::vector<std::string> directories(configuredPackageDirectories.begin(),
                                       configuredPackageDirectories.end());
  std::sort(directories.begin(), directories.end());
  for (size_t index = 1; index < directories.size(); ++index) {
    if (directories[index - 1] == directories[index])
      return packageError(kDuplicatePackage,
                          llvm::Twine("configured package directory ") +
                              directories[index] + " appears more than once");
  }

  std::vector<VerifiedPackage> packages;
  std::set<std::string> manifestDigests;
  std::map<std::string, std::string> targets;
  std::map<std::string, std::string> profiles;
  for (const std::string &directory : directories) {
    llvm::Expected<VerifiedPackage> package =
        verifyPackage(directory, compatibility, filesystem);
    if (!package)
      return package.takeError();
    if (!manifestDigests.insert(package->PackageDescriptor.manifestDigest)
             .second)
      return packageError(kDuplicatePackage,
                          llvm::Twine("duplicate package manifest ") +
                              package->PackageDescriptor.manifestDigest);
    auto inserted =
        targets.emplace(package->PackageDescriptor.targetIdentity, directory);
    if (!inserted.second)
      return packageError(kDuplicateTarget,
                          llvm::Twine("target ") +
                              package->PackageDescriptor.targetIdentity +
                              " is provided by both " + inserted.first->second +
                              " and " + directory);
    auto profileInserted = profiles.emplace(
        package->PackageDescriptor.profileSummary.profileId, directory);
    if (!profileInserted.second)
      return packageError(
          kDuplicateProfile,
          llvm::Twine("profile ") +
              package->PackageDescriptor.profileSummary.profileId +
              " is provided by both " + profileInserted.first->second +
              " and " + directory);
    packages.push_back(std::move(*package));
  }
  std::sort(packages.begin(), packages.end(),
            [](const VerifiedPackage &left, const VerifiedPackage &right) {
              return left.PackageDescriptor.targetIdentity <
                     right.PackageDescriptor.targetIdentity;
            });
  return packages;
}

} // namespace backend_package
} // namespace neutrino
