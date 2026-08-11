#ifndef NEUTRINO_BACKEND_PACKAGE_H
#define NEUTRINO_BACKEND_PACKAGE_H

#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProtocol.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace neutrino {
namespace backend_package {

constexpr llvm::StringLiteral kDescriptorKind = "neutrino.backend-package/1";
constexpr llvm::StringLiteral kDescriptorFileName = "backend-package.json";

enum class PackageFileKind {
  Regular,
  Symlink,
  Other,
  Missing,
};

class PackageFileHandle {
public:
  virtual ~PackageFileHandle() = default;

  // A verified package retains these handles. Native handles keep the opened
  // descriptor alive, so later staging can consume the already-verified bytes
  // without resolving the package path again.
  virtual PackageFileKind kind() const = 0;
  virtual llvm::StringRef bytes() const = 0;
  virtual llvm::StringRef identity() const = 0;
};

class PackageFilesystem {
public:
  virtual ~PackageFilesystem() = default;

  virtual llvm::Expected<std::unique_ptr<PackageFileHandle>>
  openNoFollow(llvm::StringRef packageDirectory,
               llvm::StringRef relativePath) const = 0;
};

std::unique_ptr<PackageFilesystem> createNativePackageFilesystem();

struct ProtocolVersion {
  uint32_t major = 0;
  uint32_t minor = 0;
};

struct ProtocolRange {
  ProtocolVersion min;
  ProtocolVersion max;
};

struct ProjectionSchemaRange {
  uint32_t min = 0;
  uint32_t max = 0;
};

struct CompatibilityBounds {
  ProtocolRange coreProtocol;
  ProjectionSchemaRange projectionSchema;
};

struct ClosureEntry {
  std::string path;
  std::string sha256;
  uint64_t byteLen = 0;
};

struct TargetProfileLimits {
  uint64_t maxExpressionDepth = 0;
  uint64_t maxEffects = 0;
  uint64_t maxEffectGroups = 0;
  uint64_t maxAttestations = 0;
  uint64_t maxComputes = 0;
  uint64_t maxOperationSteps = 0;
};

struct TargetProfile {
  uint32_t schemaVersion = 0;
  std::string kind;
  std::string profileId;
  uint32_t profileVersion = 0;
  std::string target;
  std::string runtimeFamily;
  std::string executionMode;
  std::vector<std::string> supportedFeatures;
  std::vector<std::string> unsupportedConstructs;
  std::string fallbackPolicy;
  std::string capabilitySpecVersion;
  uint32_t semanticProfileVersion = 0;
  std::vector<std::string> semanticFeatures;
  TargetProfileLimits limits;
  std::string canonicalBytes;
  std::string digest;
};

struct Descriptor {
  std::string targetIdentity;
  uint32_t protocolMajor = 0;
  uint32_t protocolMinor = 0;
  uint32_t apiVersion = 0;
  std::string targetProfileIdentity;
  std::string entry;
  std::vector<ClosureEntry> closure;
  CompatibilityBounds compatibilityBounds;
  std::vector<std::string> capabilities;
  TargetProfile profileSummary;
  std::string licenseIdentity;
  std::string manifestDigest;
};

struct Compatibility {
  ProtocolVersion coreProtocol{backend_protocol::kProtocolMajor,
                               backend_protocol::kProtocolMinor};
  uint32_t apiVersion = 1;
  uint32_t projectionSchema =
      static_cast<uint32_t>(projection::kProjectionSchemaVersion);
};

struct VerifiedClosureEntry {
  ClosureEntry manifest;
  std::unique_ptr<PackageFileHandle> file;
};

class VerifiedPackage {
public:
  ~VerifiedPackage() = default;
  VerifiedPackage(VerifiedPackage &&) = default;
  VerifiedPackage &operator=(VerifiedPackage &&) = default;
  VerifiedPackage(const VerifiedPackage &) = delete;
  VerifiedPackage &operator=(const VerifiedPackage &) = delete;

  llvm::StringRef packageDirectory() const { return PackageDirectory; }
  const Descriptor &descriptor() const { return PackageDescriptor; }
  llvm::ArrayRef<VerifiedClosureEntry> closure() const { return Closure; }
  const PackageFileHandle &descriptorFile() const { return *DescriptorFile; }
  const VerifiedClosureEntry &entry() const { return Closure[EntryIndex]; }

private:
  VerifiedPackage() = default;

  friend llvm::Expected<VerifiedPackage>
  verifyPackage(llvm::StringRef, const Compatibility &,
                const PackageFilesystem &);
  friend llvm::Expected<std::vector<VerifiedPackage>>
  discoverPackages(llvm::ArrayRef<std::string>, const Compatibility &,
                   const PackageFilesystem &);

  std::string PackageDirectory;
  Descriptor PackageDescriptor;
  std::unique_ptr<PackageFileHandle> DescriptorFile;
  std::vector<VerifiedClosureEntry> Closure;
  size_t EntryIndex = 0;
};

llvm::Expected<Descriptor> parseDescriptor(llvm::StringRef bytes);

llvm::Expected<VerifiedPackage>
verifyPackage(llvm::StringRef packageDirectory,
              const Compatibility &compatibility,
              const PackageFilesystem &filesystem);

llvm::Expected<std::vector<VerifiedPackage>>
discoverPackages(llvm::ArrayRef<std::string> configuredPackageDirectories,
                 const Compatibility &compatibility,
                 const PackageFilesystem &filesystem);

} // namespace backend_package
} // namespace neutrino

#endif // NEUTRINO_BACKEND_PACKAGE_H
