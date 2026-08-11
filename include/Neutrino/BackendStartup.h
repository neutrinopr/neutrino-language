#ifndef NEUTRINO_BACKEND_STARTUP_H
#define NEUTRINO_BACKEND_STARTUP_H

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <string>

namespace neutrino {
namespace backend_startup {

constexpr llvm::StringLiteral kContractIdentity = "neutrino.backend-startup/1";
constexpr llvm::StringLiteral kContractArgument = "--neutrino-backend-startup=";
constexpr llvm::StringLiteral kDescriptorArgument = "--package-descriptor=";

struct Binding {
  std::string descriptorPath;
};

llvm::Expected<Binding> parseArguments(int argc, char *const argv[]);
llvm::Expected<std::string>
verifiedPackageManifestDigest(llvm::StringRef descriptorBytes);
llvm::Expected<std::string> loadPackageManifestDigest(const Binding &binding);

} // namespace backend_startup
} // namespace neutrino

#endif // NEUTRINO_BACKEND_STARTUP_H
