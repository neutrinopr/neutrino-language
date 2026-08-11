#ifndef NEUTRINO_ARTIFACT_PUBLICATION_H
#define NEUTRINO_ARTIFACT_PUBLICATION_H

#include "Neutrino/BackendInvoker.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstdint>
#include <string>
#include <vector>

namespace neutrino {
namespace artifact_publication {

struct PublishedArtifact {
  std::string path;
  std::string sha256;
  uint64_t byteLen = 0;
};

struct CoreArtifact {
  std::string path;
  std::string bytes;
};

struct Result {
  uint64_t requestId = 0;
  std::string targetIdentity;
  std::string receiptDigest;
  std::vector<PublishedArtifact> artifacts;
};

// Publishes into an existing directory without following symlinks or replacing
// an existing artifact. Each final directory entry becomes visible when its
// exclusive descriptor is created; a successful result is returned only after
// every entry is complete, synced, re-opened, and verified. On any failure,
// already-visible paths remain in place and the error reports that condition;
// publication never re-resolves and deletes names from the shared namespace.
llvm::Expected<Result> publish(const backend_invocation::Result &manifest,
                               llvm::StringRef outputRoot);

// Publishes one core-owned metadata artifact through the same no-follow,
// exclusive-create, descriptor-verified path as backend artifacts.
llvm::Expected<PublishedArtifact>
publishCoreArtifact(llvm::StringRef path, llvm::StringRef bytes,
                    llvm::StringRef outputRoot);

// Publishes a complete prevalidated set of core-owned artifacts through one
// ordered no-follow/exclusive-create operation.
llvm::Expected<std::vector<PublishedArtifact>>
publishCoreArtifacts(llvm::ArrayRef<CoreArtifact> artifacts,
                     llvm::StringRef outputRoot);

} // namespace artifact_publication
} // namespace neutrino

#endif // NEUTRINO_ARTIFACT_PUBLICATION_H
