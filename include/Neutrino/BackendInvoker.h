#ifndef NEUTRINO_BACKEND_INVOKER_H
#define NEUTRINO_BACKEND_INVOKER_H

#include "Neutrino/BackendPackage.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProtocol.h"

#include "llvm/Support/Error.h"

#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

namespace neutrino {
namespace backend_invocation {

struct InvocationOptions {
  uint64_t requestId = 1;
  std::string coreIdentity = "neutrino-core";
  backend_protocol::OutputSpec outputSpec;
  std::chrono::milliseconds timeout{30000};
  std::chrono::milliseconds cancellationGrace{1000};
};

struct Artifact {
  std::string path;
  std::string bytes;
  std::string sha256;
};

struct Result {
  uint64_t requestId = 0;
  std::string coreIdentity;
  std::string targetIdentity;
  std::string targetProfileIdentity;
  std::string packageManifestDigest;
  std::string projectionEncoding;
  uint64_t projectionByteLen = 0;
  std::string projectionDigest;
  std::vector<Artifact> artifacts;
  std::string receiptDigest;
};

// Stable identity of this core/protocol build. Deliberately independent of the
// selected package; package identity is negotiated and recorded separately.
std::string coreIdentity();

llvm::Expected<Result> invoke(const backend_package::VerifiedPackage &package,
                              const projection::BackendProjectionGraph &graph,
                              const InvocationOptions &options);

} // namespace backend_invocation
} // namespace neutrino

#endif // NEUTRINO_BACKEND_INVOKER_H
