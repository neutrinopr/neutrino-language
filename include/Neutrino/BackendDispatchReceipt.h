#ifndef NEUTRINO_BACKEND_DISPATCH_RECEIPT_H
#define NEUTRINO_BACKEND_DISPATCH_RECEIPT_H

#include "Neutrino/BackendInvoker.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstdint>
#include <string>
#include <vector>

namespace neutrino {
namespace backend_dispatch_receipt {

inline constexpr llvm::StringLiteral kKind =
    "neutrino.backend-dispatch-receipt/1";
inline constexpr llvm::StringLiteral kFileName =
    "backend-dispatch-receipt.json";
inline constexpr uint64_t kSchemaVersion = 1;

struct ArtifactIdentity {
  std::string path;
  uint64_t byteLen = 0;
  std::string sha256;
};

struct VerifiedReceipt {
  uint64_t requestId = 0;
  std::string coreIdentity;
  std::string targetIdentity;
  std::string targetProfileIdentity;
  std::string packageManifestDigest;
  std::string projectionEncoding;
  uint64_t projectionByteLen = 0;
  std::string projectionDigest;
  std::string backendReceiptDigest;
  std::vector<ArtifactIdentity> artifacts;
  std::string receiptDigest;
};

// Records the core-side authorization that immediately preceded a verified
// package invocation. The authorization is bound to the exact request and
// canonical projection bytes sent by BackendInvoker, then to the backend
// completion receipt and complete artifact identity set.
llvm::Expected<std::string>
createApproved(const backend_invocation::Result &invocation);

// Parses a closed v1 receipt, verifies its self-digest and all cross-field
// bindings, and rejects malformed or non-canonical bytes.
llvm::Expected<VerifiedReceipt> verify(llvm::StringRef bytes);

} // namespace backend_dispatch_receipt
} // namespace neutrino

#endif // NEUTRINO_BACKEND_DISPATCH_RECEIPT_H
