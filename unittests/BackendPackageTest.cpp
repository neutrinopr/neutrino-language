// SPDX-License-Identifier: Apache-2.0
#include "Neutrino/BackendPackage.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/TargetCatalog.h"

#include "llvm/ADT/SmallVector.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

#include "gtest/gtest.h"

#include <algorithm>
#include <cstdlib>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <unistd.h>

using namespace neutrino;
using namespace neutrino::backend_package;

namespace {

template <typename T> T take(llvm::Expected<T> value) {
  if (!value) {
    ADD_FAILURE() << llvm::toString(value.takeError());
    std::abort();
  }
  return std::move(*value);
}

void expectError(llvm::Error error, llvm::StringRef code) {
  ASSERT_TRUE(static_cast<bool>(error));
  EXPECT_NE(llvm::toString(std::move(error)).find(code.str()),
            std::string::npos);
}

template <typename T>
void expectError(llvm::Expected<T> value, llvm::StringRef code) {
  ASSERT_FALSE(static_cast<bool>(value));
  expectError(value.takeError(), code);
}

std::string digest(llvm::StringRef bytes) {
  return "sha256:" + sha256Hex(bytes);
}

llvm::json::Object targetProfileObject(llvm::StringRef target) {
  std::string profileId = ("target." + target + ".v1").str();
  return llvm::json::Object{
      {"capabilitySpecVersion", "v1"},
      {"executionMode", "simulated"},
      {"fallbackPolicy", "fail_closed"},
      {"kind", "neutrino.target-profile"},
      {"profileId", profileId},
      {"profileVersion", 1},
      {"runtimeFamily", "off_chain"},
      {"schemaVersion", 1},
      {"semanticProfile",
       llvm::json::Object{
           {"features",
            llvm::json::Array{"authorization:explicit", "terminal:success"}},
           {"limits",
            llvm::json::Object{
                {"maxAttestations", 4},
                {"maxComputes", 4},
                {"maxEffectGroups", 4},
                {"maxEffects", 8},
                {"maxExpressionDepth", 8},
                {"maxOperationSteps", 32},
            }},
           {"version", 3},
       }},
      {"supportedFeatures", llvm::json::Array{"effect:credit", "effect:debit"}},
      {"target", target},
      {"unsupportedConstructs", llvm::json::Array{"value_category:extension"}},
  };
}

llvm::json::Object descriptorObject(llvm::StringRef target,
                                    llvm::StringRef entryBytes,
                                    llvm::StringRef resourceBytes) {
  llvm::json::Array closure;
  closure.push_back(llvm::json::Object{
      {"byteLen", static_cast<int64_t>(entryBytes.size())},
      {"path", "bin/backend"},
      {"sha256", digest(entryBytes)},
  });
  closure.push_back(llvm::json::Object{
      {"byteLen", static_cast<int64_t>(resourceBytes.size())},
      {"path", "share/runtime.dat"},
      {"sha256", digest(resourceBytes)},
  });
  return llvm::json::Object{
      {"apiVersion", 1},
      {"capabilities", llvm::json::Array{"emit", "stream"}},
      {"closure", std::move(closure)},
      {"compatibilityBounds",
       llvm::json::Object{
           {"coreProtocol",
            llvm::json::Object{
                {"max", llvm::json::Object{{"major", 1}, {"minor", 0}}},
                {"min", llvm::json::Object{{"major", 1}, {"minor", 0}}},
            }},
           {"projectionSchema",
            llvm::json::Object{
                {"max",
                 static_cast<int64_t>(projection::kProjectionSchemaVersion)},
                {"min",
                 static_cast<int64_t>(projection::kProjectionSchemaVersion)},
            }},
       }},
      {"entry", "bin/backend"},
      {"kind", kDescriptorKind},
      {"licenseIdentity", "MIT"},
      {"profileSummary", targetProfileObject(target)},
      {"protocolMajor", 1},
      {"protocolMinor", 0},
      {"targetIdentity", target},
      {"targetProfileIdentity", ("target." + target + ".v1").str()},
  };
}

std::string seal(llvm::json::Object object) {
  llvm::json::Value value(std::move(object));
  std::string manifestDigest = digest(compactJson(value));
  value.getAsObject()->insert({"manifestDigest", manifestDigest});
  return compactJson(value);
}

std::string reseal(llvm::StringRef bytes,
                   const std::function<void(llvm::json::Object &)> &mutate) {
  llvm::Expected<llvm::json::Value> value = llvm::json::parse(bytes);
  if (!value || !value->getAsObject()) {
    ADD_FAILURE() << "fixture descriptor failed to parse";
    if (!value)
      llvm::consumeError(value.takeError());
    return {};
  }
  llvm::json::Object &object = *value->getAsObject();
  object.erase("manifestDigest");
  mutate(object);
  std::string manifestDigest = digest(compactJson(*value));
  object.insert({"manifestDigest", manifestDigest});
  return compactJson(*value);
}

std::string mutateWithoutResealing(
    llvm::StringRef bytes,
    const std::function<void(llvm::json::Object &)> &mutate) {
  llvm::Expected<llvm::json::Value> value = llvm::json::parse(bytes);
  if (!value || !value->getAsObject()) {
    ADD_FAILURE() << "fixture descriptor failed to parse";
    if (!value)
      llvm::consumeError(value.takeError());
    return {};
  }
  mutate(*value->getAsObject());
  return compactJson(*value);
}

class MemoryHandle final : public PackageFileHandle {
public:
  MemoryHandle(PackageFileKind kind, std::string bytes, std::string identity)
      : Kind(kind), Bytes(std::move(bytes)), Identity(std::move(identity)) {}

  PackageFileKind kind() const override { return Kind; }
  llvm::StringRef bytes() const override { return Bytes; }
  llvm::StringRef identity() const override { return Identity; }

private:
  PackageFileKind Kind;
  std::string Bytes;
  std::string Identity;
};

struct MemoryFile {
  PackageFileKind kind = PackageFileKind::Regular;
  std::string bytes;
  std::string identity;
};

class MemoryFilesystem final : public PackageFilesystem {
public:
  void add(llvm::StringRef directory, llvm::StringRef path,
           llvm::StringRef bytes,
           PackageFileKind kind = PackageFileKind::Regular,
           llvm::StringRef identity = {}) {
    std::string key = (directory + "/" + path).str();
    Files[key] = {kind, bytes.str(), identity.empty() ? key : identity.str()};
  }

  void setKind(llvm::StringRef directory, llvm::StringRef path,
               PackageFileKind kind) {
    Files[(directory + "/" + path).str()].kind = kind;
  }

  void setBytes(llvm::StringRef directory, llvm::StringRef path,
                llvm::StringRef bytes) {
    Files[(directory + "/" + path).str()].bytes = bytes.str();
  }

  llvm::Expected<std::unique_ptr<PackageFileHandle>>
  openNoFollow(llvm::StringRef directory, llvm::StringRef path) const override {
    std::string key = (directory + "/" + path).str();
    auto found = Files.find(key);
    if (found == Files.end())
      return std::make_unique<MemoryHandle>(PackageFileKind::Missing,
                                            std::string(), key);
    return std::make_unique<MemoryHandle>(
        found->second.kind, found->second.bytes, found->second.identity);
  }

private:
  std::map<std::string, MemoryFile> Files;
};

void addPackage(MemoryFilesystem &filesystem, llvm::StringRef directory,
                llvm::StringRef target, llvm::StringRef entryBytes = "entry",
                llvm::StringRef resourceBytes = "resource") {
  filesystem.add(directory, "bin/backend", entryBytes);
  filesystem.add(directory, "share/runtime.dat", resourceBytes);
  filesystem.add(directory, kDescriptorFileName,
                 seal(descriptorObject(target, entryBytes, resourceBytes)));
}

void writeFile(llvm::StringRef path, llvm::StringRef bytes) {
  std::error_code error;
  llvm::raw_fd_ostream output(path, error);
  ASSERT_FALSE(error) << error.message();
  output << bytes;
}

llvm::json::Object *jsonPointerParent(llvm::json::Object &root,
                                      llvm::StringRef pointer,
                                      llvm::StringRef &field) {
  llvm::SmallVector<llvm::StringRef, 4> parts;
  pointer.consume_front("/");
  pointer.split(parts, "/");
  if (parts.empty())
    return nullptr;
  llvm::json::Object *parent = &root;
  for (llvm::StringRef part :
       llvm::ArrayRef<llvm::StringRef>(parts).drop_back()) {
    parent = parent->getObject(part);
    if (!parent)
      return nullptr;
  }
  field = parts.back();
  return parent;
}

} // namespace

TEST(BackendPackage, ParsesVerifiesAndDiscoversInTargetOrder) {
  MemoryFilesystem filesystem;
  addPackage(filesystem, "/packages/zeta", "zeta");
  addPackage(filesystem, "/packages/alpha", "alpha");

  Compatibility compatibility;
  std::vector<VerifiedPackage> first = take(discoverPackages(
      {"/packages/zeta", "/packages/alpha"}, compatibility, filesystem));
  std::vector<VerifiedPackage> second = take(discoverPackages(
      {"/packages/alpha", "/packages/zeta"}, compatibility, filesystem));
  ASSERT_EQ(first.size(), 2u);
  ASSERT_EQ(second.size(), 2u);
  EXPECT_EQ(first[0].descriptor().targetIdentity, "alpha");
  EXPECT_EQ(first[1].descriptor().targetIdentity, "zeta");
  EXPECT_EQ(second[0].descriptor().manifestDigest,
            first[0].descriptor().manifestDigest);
  EXPECT_EQ(first[0].entry().manifest.path, "bin/backend");
  EXPECT_EQ(first[0].entry().file->bytes(), "entry");
  EXPECT_FALSE(first[0].entry().file->identity().empty());
  EXPECT_EQ(first[0].descriptor().profileSummary.profileId, "target.alpha.v1");
  EXPECT_TRUE(llvm::StringRef(first[0].descriptor().profileSummary.digest)
                  .startswith("sha256:"));
}

TEST(BackendPackage, TargetProfileContractFailsClosed) {
  MemoryFilesystem filesystem;
  addPackage(filesystem, "/package", "alpha");
  llvm::Expected<std::unique_ptr<PackageFileHandle>> descriptorFile =
      filesystem.openNoFollow("/package", kDescriptorFileName);
  ASSERT_TRUE(static_cast<bool>(descriptorFile));
  const std::string descriptor = (*descriptorFile)->bytes().str();
  Compatibility compatibility;

  auto rejectProfile =
      [&](const std::function<void(llvm::json::Object &)> &mutate) {
        filesystem.setBytes("/package", kDescriptorFileName,
                            reseal(descriptor, [&](llvm::json::Object &object) {
                              mutate(*object.getObject("profileSummary"));
                            }));
        expectError(verifyPackage("/package", compatibility, filesystem),
                    "E_PACKAGE_PROFILE");
      };

  rejectProfile([](llvm::json::Object &profile) { profile["unknown"] = true; });
  rejectProfile(
      [](llvm::json::Object &profile) { profile["profileVersion"] = 2; });
  rejectProfile(
      [](llvm::json::Object &profile) { profile["target"] = "other"; });
  rejectProfile([](llvm::json::Object &profile) {
    profile["unsupportedConstructs"] = llvm::json::Array{"effect:credit"};
  });
  rejectProfile([](llvm::json::Object &profile) {
    profile.getObject("semanticProfile")
        ->getArray("features")
        ->push_back("unknown:semantic");
  });
  rejectProfile([](llvm::json::Object &profile) {
    profile.getObject("semanticProfile")
        ->getObject("limits")
        ->erase("maxEffects");
  });
  rejectProfile([](llvm::json::Object &profile) {
    (*profile.getObject("semanticProfile")->getObject("limits"))["extraLimit"] =
        1;
  });
  rejectProfile([](llvm::json::Object &profile) {
    profile["supportedFeatures"] =
        llvm::json::Array{"effect:debit", "effect:credit"};
  });

  filesystem.setBytes("/package", kDescriptorFileName, descriptor + "\n");
  expectError(verifyPackage("/package", compatibility, filesystem),
              "E_PACKAGE_DESCRIPTOR");

  filesystem.setBytes(
      "/package", kDescriptorFileName,
      mutateWithoutResealing(descriptor, [](llvm::json::Object &object) {
        object.getObject("profileSummary")->operator[]("executionMode") =
            "real";
      }));
  expectError(verifyPackage("/package", compatibility, filesystem),
              "E_PACKAGE_MANIFEST_DIGEST");
}

TEST(BackendPackage, TargetProfileValidatorsShareAcceptanceAndMutations) {
  llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> buffer =
      llvm::MemoryBuffer::getFile(
          NEUTRINO_SOURCE_ROOT
          "/test/ir/compat/Inputs/target-profile-validator-agreement.json");
  ASSERT_TRUE(static_cast<bool>(buffer)) << buffer.getError().message();
  llvm::Expected<llvm::json::Value> fixture =
      llvm::json::parse((*buffer)->getBuffer());
  ASSERT_TRUE(static_cast<bool>(fixture));
  llvm::json::Object *fixtureObject = fixture->getAsObject();
  ASSERT_NE(fixtureObject, nullptr);
  llvm::json::Value *positiveValue = fixtureObject->get("positive");
  llvm::json::Object *positive =
      positiveValue ? positiveValue->getAsObject() : nullptr;
  llvm::json::Array *mutations = fixtureObject->getArray("mutations");
  ASSERT_NE(positive, nullptr);
  ASSERT_NE(mutations, nullptr);

  MemoryFilesystem filesystem;
  Compatibility compatibility;
  llvm::json::Object positiveDescriptor =
      descriptorObject("alpha", "entry", "resource");
  positiveDescriptor["targetProfileIdentity"] =
      positive->getString("profileId")->str();
  positiveDescriptor["profileSummary"] =
      take(llvm::json::parse(compactJson(*positiveValue)));
  filesystem.add("/package", "bin/backend", "entry");
  filesystem.add("/package", "share/runtime.dat", "resource");
  filesystem.add("/package", kDescriptorFileName,
                 seal(std::move(positiveDescriptor)));
  ASSERT_TRUE(
      static_cast<bool>(verifyPackage("/package", compatibility, filesystem)));

  for (const llvm::json::Value &mutationValue : *mutations) {
    const llvm::json::Object *mutation = mutationValue.getAsObject();
    ASSERT_NE(mutation, nullptr);
    llvm::Optional<llvm::StringRef> name = mutation->getString("name");
    llvm::Optional<llvm::StringRef> operation =
        mutation->getString("operation");
    llvm::Optional<bool> packageAccepted =
        mutation->getBoolean("packageAccepted");
    ASSERT_TRUE(name && operation && packageAccepted);

    llvm::Expected<llvm::json::Value> candidate =
        llvm::json::parse(compactJson(*positiveValue));
    ASSERT_TRUE(static_cast<bool>(candidate));
    llvm::json::Object *profile = candidate->getAsObject();
    ASSERT_NE(profile, nullptr);
    if (*operation == "erase" || *operation == "reverse") {
      llvm::Optional<llvm::StringRef> pointer = mutation->getString("pointer");
      ASSERT_TRUE(pointer);
      llvm::StringRef field;
      llvm::json::Object *parent = jsonPointerParent(*profile, *pointer, field);
      ASSERT_NE(parent, nullptr);
      if (*operation == "erase") {
        ASSERT_TRUE(parent->erase(field));
      } else {
        llvm::json::Array *array = parent->getArray(field);
        ASSERT_NE(array, nullptr);
        std::reverse(array->begin(), array->end());
      }
    } else if (*operation == "assign") {
      const llvm::json::Array *assignments = mutation->getArray("assignments");
      ASSERT_NE(assignments, nullptr);
      for (const llvm::json::Value &assignmentValue : *assignments) {
        const llvm::json::Object *assignment = assignmentValue.getAsObject();
        ASSERT_NE(assignment, nullptr);
        llvm::Optional<llvm::StringRef> pointer =
            assignment->getString("pointer");
        const llvm::json::Value *value = assignment->get("value");
        ASSERT_TRUE(pointer && value);
        llvm::StringRef field;
        llvm::json::Object *parent =
            jsonPointerParent(*profile, *pointer, field);
        ASSERT_NE(parent, nullptr);
        (*parent)[field] = take(llvm::json::parse(compactJson(*value)));
      }
    } else {
      FAIL() << "unsupported mutation operation for " << name->str();
    }

    llvm::json::Object descriptor =
        descriptorObject("alpha", "entry", "resource");
    descriptor["targetProfileIdentity"] =
        profile->getString("profileId")->str();
    descriptor["profileSummary"] = std::move(*candidate);
    filesystem.setBytes("/package", kDescriptorFileName,
                        seal(std::move(descriptor)));
    llvm::Expected<VerifiedPackage> verified =
        verifyPackage("/package", compatibility, filesystem);
    if (*packageAccepted) {
      EXPECT_TRUE(static_cast<bool>(verified)) << name->str();
      if (!verified)
        llvm::consumeError(verified.takeError());
    } else {
      expectError(std::move(verified), "E_PACKAGE_PROFILE");
    }
  }
}

TEST(BackendPackage, ManifestClosureAndEntryTamperingFailClosed) {
  Compatibility compatibility;

  MemoryFilesystem manifestFilesystem;
  addPackage(manifestFilesystem, "/package", "alpha");
  llvm::Expected<std::unique_ptr<PackageFileHandle>> manifestDescriptor =
      manifestFilesystem.openNoFollow("/package", kDescriptorFileName);
  ASSERT_TRUE(static_cast<bool>(manifestDescriptor));
  manifestFilesystem.setBytes(
      "/package", kDescriptorFileName,
      mutateWithoutResealing((*manifestDescriptor)->bytes(),
                             [](llvm::json::Object &object) {
                               object["targetIdentity"] = "tampered";
                             }));
  expectError(verifyPackage("/package", compatibility, manifestFilesystem),
              "E_PACKAGE_MANIFEST_DIGEST");

  MemoryFilesystem closureFilesystem;
  addPackage(closureFilesystem, "/package", "alpha");
  closureFilesystem.setBytes("/package", "share/runtime.dat", "tampered");
  expectError(verifyPackage("/package", compatibility, closureFilesystem),
              "E_PACKAGE_CLOSURE");

  MemoryFilesystem lengthFilesystem;
  addPackage(lengthFilesystem, "/package", "alpha");
  lengthFilesystem.setBytes("/package", "share/runtime.dat", "short");
  expectError(verifyPackage("/package", compatibility, lengthFilesystem),
              "E_PACKAGE_CLOSURE");

  MemoryFilesystem entryFilesystem;
  addPackage(entryFilesystem, "/package", "alpha");
  llvm::Expected<std::unique_ptr<PackageFileHandle>> descriptorFile =
      entryFilesystem.openNoFollow("/package", kDescriptorFileName);
  ASSERT_TRUE(static_cast<bool>(descriptorFile));
  std::string unbound =
      reseal((*descriptorFile)->bytes(), [](llvm::json::Object &object) {
        object["entry"] = "bin/unlisted";
      });
  entryFilesystem.setBytes("/package", kDescriptorFileName, unbound);
  expectError(verifyPackage("/package", compatibility, entryFilesystem),
              "E_PACKAGE_ENTRY");
}

TEST(BackendPackage, MissingSymlinkAndNonRegularClosureFilesFailClosed) {
  Compatibility compatibility;

  MemoryFilesystem missing;
  addPackage(missing, "/package", "alpha");
  missing.setKind("/package", "share/runtime.dat", PackageFileKind::Missing);
  expectError(verifyPackage("/package", compatibility, missing),
              "E_PACKAGE_CLOSURE");

  MemoryFilesystem symlink;
  addPackage(symlink, "/package", "alpha");
  symlink.setKind("/package", "bin/backend", PackageFileKind::Symlink);
  expectError(verifyPackage("/package", compatibility, symlink),
              "E_PACKAGE_FILE_TYPE");

  MemoryFilesystem other;
  addPackage(other, "/package", "alpha");
  other.setKind("/package", "share/runtime.dat", PackageFileKind::Other);
  expectError(verifyPackage("/package", compatibility, other),
              "E_PACKAGE_FILE_TYPE");
}

TEST(BackendPackage, DescriptorShapeAndCompatibilityFailClosed) {
  MemoryFilesystem filesystem;
  addPackage(filesystem, "/package", "alpha");
  llvm::Expected<std::unique_ptr<PackageFileHandle>> descriptorFile =
      filesystem.openNoFollow("/package", kDescriptorFileName);
  ASSERT_TRUE(static_cast<bool>(descriptorFile));
  std::string descriptor = (*descriptorFile)->bytes().str();

  filesystem.setBytes("/package", kDescriptorFileName,
                      reseal(descriptor, [](llvm::json::Object &object) {
                        object["kind"] = "neutrino.backend-package/2";
                      }));
  expectError(verifyPackage("/package", Compatibility(), filesystem),
              "E_VERSION");

  filesystem.setBytes("/package", kDescriptorFileName,
                      reseal(descriptor, [](llvm::json::Object &object) {
                        object["protocolMajor"] = 2;
                      }));
  expectError(verifyPackage("/package", Compatibility(), filesystem),
              "E_VERSION");

  filesystem.setBytes(
      "/package", kDescriptorFileName,
      reseal(descriptor, [](llvm::json::Object &object) {
        llvm::json::Object *bounds = object.getObject("compatibilityBounds");
        llvm::json::Object *schema = bounds->getObject("projectionSchema");
        (*schema)["min"] =
            static_cast<int64_t>(projection::kProjectionSchemaVersion + 1);
        (*schema)["max"] =
            static_cast<int64_t>(projection::kProjectionSchemaVersion + 1);
      }));
  expectError(verifyPackage("/package", Compatibility(), filesystem),
              "E_PROJECTION_SCHEMA");

  filesystem.setBytes("/package", kDescriptorFileName,
                      reseal(descriptor, [](llvm::json::Object &object) {
                        object.erase("targetProfileIdentity");
                      }));
  expectError(verifyPackage("/package", Compatibility(), filesystem),
              "E_PACKAGE_DESCRIPTOR");

  filesystem.setBytes("/package", kDescriptorFileName,
                      reseal(descriptor, [](llvm::json::Object &object) {
                        object["entry"] = "../escape";
                      }));
  expectError(verifyPackage("/package", Compatibility(), filesystem),
              "E_PACKAGE_PATH");
}

TEST(BackendPackage, AdditiveMinorAcceptsOlderPackageWhenBoundsIncludeCore) {
  MemoryFilesystem filesystem;
  addPackage(filesystem, "/package", "alpha");
  llvm::Expected<std::unique_ptr<PackageFileHandle>> descriptorFile =
      filesystem.openNoFollow("/package", kDescriptorFileName);
  ASSERT_TRUE(static_cast<bool>(descriptorFile));
  filesystem.setBytes(
      "/package", kDescriptorFileName,
      reseal((*descriptorFile)->bytes(), [](llvm::json::Object &object) {
        llvm::json::Object *bounds = object.getObject("compatibilityBounds");
        llvm::json::Object *protocol = bounds->getObject("coreProtocol");
        (*protocol->getObject("max"))["minor"] = 1;
      }));

  Compatibility core;
  core.coreProtocol = {1, 1};
  VerifiedPackage package = take(verifyPackage("/package", core, filesystem));
  EXPECT_EQ(package.descriptor().protocolMinor, 0u);
  EXPECT_EQ(core.coreProtocol.minor, 1u);
}

TEST(BackendPackage, AdditiveMinorRejectsOlderPackageWhenBoundsExcludeCore) {
  MemoryFilesystem filesystem;
  addPackage(filesystem, "/package", "alpha");

  Compatibility core;
  core.coreProtocol = {1, 1};
  expectError(verifyPackage("/package", core, filesystem), "E_VERSION");
}

TEST(BackendPackage, DuplicateDirectoriesManifestsAndTargetsFailClosed) {
  Compatibility compatibility;
  MemoryFilesystem filesystem;
  addPackage(filesystem, "/packages/one", "alpha");

  expectError(discoverPackages({"/packages/one", "/packages/one"},
                               compatibility, filesystem),
              "E_PACKAGE_DUPLICATE");

  addPackage(filesystem, "/packages/two", "alpha", "other-entry",
             "other-resource");
  expectError(discoverPackages({"/packages/one", "/packages/two"},
                               compatibility, filesystem),
              "E_TARGET_DUPLICATE");

  MemoryFilesystem duplicateManifest;
  addPackage(duplicateManifest, "/packages/one", "alpha");
  addPackage(duplicateManifest, "/packages/two", "alpha");
  expectError(discoverPackages({"/packages/one", "/packages/two"},
                               compatibility, duplicateManifest),
              "E_PACKAGE_DUPLICATE");

  MemoryFilesystem duplicateProfile;
  addPackage(duplicateProfile, "/packages/one", "alpha");
  addPackage(duplicateProfile, "/packages/two", "beta", "other-entry",
             "other-resource");
  llvm::Expected<std::unique_ptr<PackageFileHandle>> betaDescriptor =
      duplicateProfile.openNoFollow("/packages/two", kDescriptorFileName);
  ASSERT_TRUE(static_cast<bool>(betaDescriptor));
  duplicateProfile.setBytes(
      "/packages/two", kDescriptorFileName,
      reseal((*betaDescriptor)->bytes(), [](llvm::json::Object &object) {
        object["targetProfileIdentity"] = "target.alpha.v1";
        object.getObject("profileSummary")->operator[]("profileId") =
            "target.alpha.v1";
      }));
  expectError(discoverPackages({"/packages/one", "/packages/two"},
                               compatibility, duplicateProfile),
              "E_PROFILE_DUPLICATE");
}

TEST(BackendPackage, NativeFilesystemKeepsFilesOpenAndRejectsSymlinks) {
  llvm::SmallString<128> packageDirectory;
  ASSERT_FALSE(llvm::sys::fs::createUniqueDirectory("neutrino-backend-package",
                                                    packageDirectory));
  llvm::SmallString<128> binDirectory(packageDirectory);
  llvm::sys::path::append(binDirectory, "bin");
  llvm::SmallString<128> shareDirectory(packageDirectory);
  llvm::sys::path::append(shareDirectory, "share");
  ASSERT_FALSE(llvm::sys::fs::create_directory(binDirectory));
  ASSERT_FALSE(llvm::sys::fs::create_directory(shareDirectory));

  llvm::SmallString<128> entryPath(binDirectory);
  llvm::sys::path::append(entryPath, "backend");
  llvm::SmallString<128> resourcePath(shareDirectory);
  llvm::sys::path::append(resourcePath, "runtime.dat");
  llvm::SmallString<128> descriptorPath(packageDirectory);
  llvm::sys::path::append(descriptorPath, kDescriptorFileName);
  writeFile(entryPath, "entry");
  writeFile(resourcePath, "resource");
  writeFile(descriptorPath,
            seal(descriptorObject("alpha", "entry", "resource")));

  std::unique_ptr<PackageFilesystem> filesystem =
      createNativePackageFilesystem();
  VerifiedPackage package =
      take(verifyPackage(packageDirectory, Compatibility(), *filesystem));
  EXPECT_EQ(package.entry().file->bytes(), "entry");
  EXPECT_FALSE(package.entry().file->identity().empty());

  ASSERT_FALSE(llvm::sys::fs::remove(entryPath));
  writeFile(entryPath, "replacement");
  EXPECT_EQ(package.entry().file->bytes(), "entry");

  llvm::SmallString<128> realEntryPath(binDirectory);
  llvm::sys::path::append(realEntryPath, "real-backend");
  writeFile(realEntryPath, "entry");
  ASSERT_FALSE(llvm::sys::fs::remove(entryPath));
  ASSERT_EQ(::symlink(realEntryPath.c_str(), entryPath.c_str()), 0);
  expectError(verifyPackage(packageDirectory, Compatibility(), *filesystem),
              "E_PACKAGE_FILE_TYPE");

  ASSERT_FALSE(llvm::sys::fs::remove_directories(packageDirectory));
}

TEST(BackendPackage, CatalogProfilesAreTargetSortedAndDigestBound) {
  llvm::SmallString<128> root;
  ASSERT_FALSE(
      llvm::sys::fs::createUniqueDirectory("neutrino-profile-catalog", root));
  auto writePackage = [&](llvm::StringRef name) -> std::string {
    llvm::SmallString<128> directory(root);
    llvm::sys::path::append(directory, name);
    llvm::SmallString<128> bin(directory);
    llvm::sys::path::append(bin, "bin");
    llvm::SmallString<128> share(directory);
    llvm::sys::path::append(share, "share");
    EXPECT_FALSE(llvm::sys::fs::create_directory(directory));
    EXPECT_FALSE(llvm::sys::fs::create_directory(bin));
    EXPECT_FALSE(llvm::sys::fs::create_directory(share));
    llvm::SmallString<128> entry(bin);
    llvm::sys::path::append(entry, "backend");
    llvm::SmallString<128> resource(share);
    llvm::sys::path::append(resource, "runtime.dat");
    llvm::SmallString<128> descriptor(directory);
    llvm::sys::path::append(descriptor, kDescriptorFileName);
    writeFile(entry, "entry");
    writeFile(resource, "resource");
    writeFile(descriptor, seal(descriptorObject(name, "entry", "resource")));
    return directory.str().str();
  };

  std::string zeta = writePackage("zeta");
  std::string alpha = writePackage("alpha");
  TargetCatalog first = take(loadExternalTargetCatalog({zeta, alpha}));
  TargetCatalog second = take(loadExternalTargetCatalog({alpha, zeta}));
  ASSERT_EQ(first.profiles().size(), 2u);
  EXPECT_EQ(first.profiles()[0].target, "alpha");
  EXPECT_EQ(first.profiles()[1].target, "zeta");
  EXPECT_EQ(first.identity(), second.identity());

  llvm::SmallString<128> descriptor(alpha);
  llvm::sys::path::append(descriptor, kDescriptorFileName);
  llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> original =
      llvm::MemoryBuffer::getFile(descriptor);
  ASSERT_TRUE(static_cast<bool>(original));
  writeFile(descriptor,
            reseal((*original)->getBuffer(), [](llvm::json::Object &object) {
              auto *limits = object.getObject("profileSummary")
                                 ->getObject("semanticProfile")
                                 ->getObject("limits");
              (*limits)["maxComputes"] = 5;
            }));
  TargetCatalog changed = take(loadExternalTargetCatalog({alpha, zeta}));
  EXPECT_NE(first.profiles()[0].digest, changed.profiles()[0].digest);
  EXPECT_NE(first.identity(), changed.identity());

  ASSERT_FALSE(llvm::sys::fs::remove_directories(root));
}
