#include "Neutrino/BackendStartup.h"

#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/Twine.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"

namespace neutrino {
namespace backend_startup {
namespace {

llvm::Error startupError(llvm::StringRef diagnostic) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine("E_STARTUP_CONTRACT: ") + diagnostic).str(),
      llvm::inconvertibleErrorCode());
}

bool isLowerHexDigest(llvm::StringRef digest) {
  if (!digest.consume_front("sha256:") || digest.size() != 64)
    return false;
  return llvm::all_of(digest, [](char value) {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
  });
}

} // namespace

llvm::Expected<Binding> parseArguments(int argc, char *const argv[]) {
  if (argc != 3)
    return startupError("expected version and package descriptor arguments");

  llvm::StringRef contract(argv[1]);
  if (!contract.consume_front(kContractArgument) ||
      contract != kContractIdentity)
    return startupError("unsupported startup contract identity");

  llvm::StringRef descriptor(argv[2]);
  if (!descriptor.consume_front(kDescriptorArgument) || descriptor.empty() ||
      !llvm::sys::path::is_absolute(descriptor))
    return startupError("package descriptor path must be absolute");

  return Binding{descriptor.str()};
}

llvm::Expected<std::string>
verifiedPackageManifestDigest(llvm::StringRef descriptorBytes) {
  llvm::Expected<llvm::json::Value> parsed = llvm::json::parse(descriptorBytes);
  if (!parsed)
    return startupError("package descriptor is not valid JSON");
  llvm::json::Object *object = parsed->getAsObject();
  if (!object)
    return startupError("package descriptor must be an object");

  llvm::Optional<llvm::StringRef> kind = object->getString("kind");
  if (!kind || *kind != "neutrino.backend-package/1")
    return startupError("unsupported package descriptor kind");
  llvm::Optional<llvm::StringRef> manifestDigest =
      object->getString("manifestDigest");
  if (!manifestDigest || !isLowerHexDigest(*manifestDigest))
    return startupError("package manifest digest is invalid");
  std::string expected = manifestDigest->str();
  object->erase("manifestDigest");
  std::string computed = "sha256:" + sha256Hex(compactJson(*parsed));
  if (computed != expected)
    return startupError("package manifest digest does not match descriptor");
  return expected;
}

llvm::Expected<std::string> loadPackageManifestDigest(const Binding &binding) {
  llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> descriptor =
      llvm::MemoryBuffer::getFile(binding.descriptorPath);
  if (!descriptor)
    return startupError("cannot read staged package descriptor");
  return verifiedPackageManifestDigest((*descriptor)->getBuffer());
}

} // namespace backend_startup
} // namespace neutrino
