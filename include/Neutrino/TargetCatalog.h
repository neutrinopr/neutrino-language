#ifndef NEUTRINO_TARGET_CATALOG_H
#define NEUTRINO_TARGET_CATALOG_H

#include "Neutrino/BackendPackage.h"
#include "Neutrino/Targets.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstddef>
#include <string>
#include <vector>

namespace neutrino {

struct CatalogTarget {
  std::string name;
  bool gated = false;
  bool scenarioFree = false;
  bool driverSerialized = false;
  bool externalPackage = false;
  bool hasTargetProfile = false;
  int targetProfileVersion = 0;
  int semanticProfileVersion = 0;
  std::string targetProfileIdentity;
  std::string canonicalProfileSummary;
  std::string targetProfileDigest;
  const TargetSpec *builtin = nullptr;
  size_t packageIndex = 0;
};

class TargetCatalog {
public:
  TargetCatalog(TargetCatalog &&) = default;
  TargetCatalog &operator=(TargetCatalog &&) = default;
  TargetCatalog(const TargetCatalog &) = delete;
  TargetCatalog &operator=(const TargetCatalog &) = delete;

  llvm::ArrayRef<CatalogTarget> targets() const { return Targets; }
  llvm::ArrayRef<backend_package::TargetProfile> profiles() const {
    return Profiles;
  }
  const CatalogTarget *find(llvm::StringRef name) const;
  const backend_package::VerifiedPackage &
  packageFor(const CatalogTarget &target) const;
  std::vector<std::string> packageDirectories() const;
  std::string identity() const;
  std::string usageList() const;

private:
  TargetCatalog() = default;

  friend llvm::Expected<TargetCatalog>
      loadTargetCatalog(llvm::ArrayRef<std::string>);
  friend llvm::Expected<TargetCatalog>
      loadExternalTargetCatalog(llvm::ArrayRef<std::string>);
  friend llvm::Expected<TargetCatalog>
      loadTargetCatalogWithBuiltins(llvm::ArrayRef<std::string>,
                                    llvm::ArrayRef<TargetSpec>);

  std::vector<backend_package::VerifiedPackage> Packages;
  std::vector<backend_package::TargetProfile> Profiles;
  std::vector<CatalogTarget> Targets;
};

llvm::Expected<TargetCatalog>
loadTargetCatalog(llvm::ArrayRef<std::string> packageDirectories);

// Loads only verified external package targets. Integration consumers that do
// not dispatch the in-process TargetRegistry use this backend-free catalog.
llvm::Expected<TargetCatalog>
loadExternalTargetCatalog(llvm::ArrayRef<std::string> packageDirectories);

// Internal composition seam for the in-process registry plus external
// packages. TargetRegistry.cpp owns the public loadTargetCatalog wrapper.
llvm::Expected<TargetCatalog>
loadTargetCatalogWithBuiltins(llvm::ArrayRef<std::string> packageDirectories,
                              llvm::ArrayRef<TargetSpec> builtins);

// Resolves the repeatable command-line option first, then the environment
// package path, then the install-relative default package root. Both
// neutrino-gen and higher-level drivers use this one policy.
llvm::Expected<std::vector<std::string>>
resolveBackendPackageDirectories(int argc, char **argv);

} // namespace neutrino

#endif // NEUTRINO_TARGET_CATALOG_H
