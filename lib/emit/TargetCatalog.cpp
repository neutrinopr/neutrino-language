#include "Neutrino/TargetCatalog.h"

#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/Program.h"

#include <cstdlib>
#include <filesystem>
#include <set>
#include <utility>

namespace neutrino {
namespace {

llvm::Error catalogError(llvm::StringRef code, const llvm::Twine &diagnostic) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine(code) + ":catalog:" + diagnostic).str(),
      llvm::inconvertibleErrorCode());
}

llvm::Expected<CatalogTarget>
externalTarget(const backend_package::VerifiedPackage &package,
               size_t packageIndex) {
  const backend_package::Descriptor &descriptor = package.descriptor();
  const backend_package::TargetProfile &profile = descriptor.profileSummary;

  CatalogTarget result;
  result.name = descriptor.targetIdentity;
  result.gated = true;
  result.scenarioFree = false;
  result.externalPackage = true;
  result.hasTargetProfile = true;
  result.targetProfileVersion = static_cast<int>(profile.profileVersion);
  result.semanticProfileVersion =
      static_cast<int>(profile.semanticProfileVersion);
  result.targetProfileIdentity = profile.profileId;
  result.canonicalProfileSummary = profile.canonicalBytes;
  result.targetProfileDigest = profile.digest;
  result.packageIndex = packageIndex;
  return result;
}

} // namespace

const CatalogTarget *TargetCatalog::find(llvm::StringRef name) const {
  auto found = llvm::find_if(Targets, [&](const CatalogTarget &target) {
    return target.name == name;
  });
  return found == Targets.end() ? nullptr : &*found;
}

const backend_package::VerifiedPackage &
TargetCatalog::packageFor(const CatalogTarget &target) const {
  return Packages[target.packageIndex];
}

std::vector<std::string> TargetCatalog::packageDirectories() const {
  std::vector<std::string> result;
  result.reserve(Packages.size());
  for (const backend_package::VerifiedPackage &package : Packages)
    result.push_back(package.packageDirectory().str());
  return result;
}

std::string TargetCatalog::identity() const {
  llvm::json::Array targets;
  for (const CatalogTarget &target : Targets) {
    llvm::json::Object entry{
        {"driverSerialized", target.driverSerialized},
        {"externalPackage", target.externalPackage},
        {"gated", target.gated},
        {"name", target.name},
        {"scenarioFree", target.scenarioFree},
    };
    if (target.externalPackage) {
      const backend_package::Descriptor &descriptor =
          packageFor(target).descriptor();
      entry.insert({"packageManifestDigest", descriptor.manifestDigest});
      entry.insert({"targetProfileIdentity", descriptor.targetProfileIdentity});
      entry.insert({"targetProfileDigest", descriptor.profileSummary.digest});
    }
    targets.push_back(std::move(entry));
  }
  return "sha256:" +
         sha256Hex(compactJson(llvm::json::Value(std::move(targets))));
}

std::string TargetCatalog::usageList() const {
  std::string result;
  for (size_t index = 0; index < Targets.size(); ++index) {
    if (index)
      result += index + 1 == Targets.size() ? ", or " : ", ";
    result += "'" + Targets[index].name + "'";
  }
  return result;
}

llvm::Expected<TargetCatalog>
loadTargetCatalogWithBuiltins(llvm::ArrayRef<std::string> packageDirectories,
                              llvm::ArrayRef<TargetSpec> builtins) {
  TargetCatalog catalog;
  std::set<std::string> names;
  for (const TargetSpec &builtin : builtins) {
    CatalogTarget target;
    target.name = builtin.name;
    target.gated = builtin.gated;
    target.scenarioFree = builtin.scenarioFree;
    target.driverSerialized = builtin.driverSerialized;
    target.hasTargetProfile = builtin.gated && !builtin.scenarioFree;
    target.builtin = &builtin;
    names.insert(target.name);
    catalog.Targets.push_back(std::move(target));
  }

  std::unique_ptr<backend_package::PackageFilesystem> filesystem =
      backend_package::createNativePackageFilesystem();
  backend_package::Compatibility compatibility;
  llvm::Expected<std::vector<backend_package::VerifiedPackage>> packages =
      backend_package::discoverPackages(packageDirectories, compatibility,
                                        *filesystem);
  if (!packages)
    return packages.takeError();
  catalog.Packages = std::move(*packages);
  catalog.Profiles.reserve(catalog.Packages.size());
  for (size_t index = 0; index < catalog.Packages.size(); ++index) {
    llvm::Expected<CatalogTarget> target =
        externalTarget(catalog.Packages[index], index);
    if (!target)
      return target.takeError();
    if (!names.insert(target->name).second)
      return catalogError("E_PACKAGE_DUPLICATE_TARGET",
                          llvm::Twine("target '") + target->name +
                              "' is already registered");
    catalog.Profiles.push_back(
        catalog.Packages[index].descriptor().profileSummary);
    catalog.Targets.push_back(std::move(*target));
  }
  llvm::sort(catalog.Profiles, [](const backend_package::TargetProfile &left,
                                  const backend_package::TargetProfile &right) {
    return left.target < right.target;
  });
  return catalog;
}

llvm::Expected<TargetCatalog>
loadExternalTargetCatalog(llvm::ArrayRef<std::string> packageDirectories) {
  return loadTargetCatalogWithBuiltins(packageDirectories, {});
}

llvm::Expected<std::vector<std::string>>
resolveBackendPackageDirectories(int argc, char **argv) {
  std::vector<std::string> directories;
  constexpr llvm::StringLiteral flag = "--backend-package-dir";
  for (int index = 1; index < argc; ++index) {
    llvm::StringRef argument(argv[index]);
    if (argument.consume_front("--backend-package-dir=")) {
      if (argument.empty())
        return catalogError("E_PACKAGE_LOCATION",
                            "--backend-package-dir cannot be empty");
      directories.push_back(argument.str());
      continue;
    }
    if (argument != flag)
      continue;
    if (++index == argc || llvm::StringRef(argv[index]).empty())
      return catalogError(
          "E_PACKAGE_LOCATION",
          "--backend-package-dir requires a directory argument");
    directories.emplace_back(argv[index]);
  }
  if (!directories.empty())
    return directories;

  if (const char *environment = std::getenv("NEUTRINO_BACKEND_PACKAGE_PATH")) {
    llvm::StringRef remaining(environment);
    while (!remaining.empty()) {
      std::pair<llvm::StringRef, llvm::StringRef> split =
          remaining.split(llvm::sys::EnvPathSeparator);
      if (split.first.empty())
        return catalogError(
            "E_PACKAGE_LOCATION",
            "NEUTRINO_BACKEND_PACKAGE_PATH contains an empty entry");
      directories.push_back(split.first.str());
      remaining = split.second;
    }
    return directories;
  }

  namespace fs = std::filesystem;
  std::string executable = llvm::sys::fs::getMainExecutable(
      argv[0], reinterpret_cast<void *>(&resolveBackendPackageDirectories));
  if (executable.empty())
    return directories;
  fs::path root = fs::path(executable).parent_path().parent_path() / "lib" /
                  "neutrino" / "backend-packages";
  std::error_code error;
  if (!fs::exists(root, error)) {
    if (error)
      return catalogError("E_PACKAGE_LOCATION",
                          llvm::Twine("cannot inspect default package root: ") +
                              error.message());
    return directories;
  }
  if (!fs::is_directory(root, error) || error)
    return catalogError("E_PACKAGE_LOCATION",
                        "default package root is not a directory");
  for (fs::directory_iterator entry(root, error), end; !error && entry != end;
       entry.increment(error)) {
    if (!entry->is_directory(error)) {
      if (error)
        break;
      continue;
    }
    fs::path descriptor =
        entry->path() / backend_package::kDescriptorFileName.str();
    if (fs::is_regular_file(descriptor, error))
      directories.push_back(entry->path().string());
    if (error)
      break;
  }
  if (error)
    return catalogError("E_PACKAGE_LOCATION",
                        llvm::Twine("cannot enumerate default package root: ") +
                            error.message());
  llvm::sort(directories);
  return directories;
}

} // namespace neutrino
