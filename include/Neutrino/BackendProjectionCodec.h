#ifndef NEUTRINO_BACKEND_PROJECTION_CODEC_H
#define NEUTRINO_BACKEND_PROJECTION_CODEC_H

#include "Neutrino/BackendProjection.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <string>

namespace neutrino {
namespace projection {

// Canonical JSON boundary form defined by
// docs/schemas/finalized-projection-v1.schema.json. Encoding verifies and
// orders a copy of the graph before producing bytes. Decoding accepts only the
// field-complete schema shape and returns a verified, deterministically ordered
// graph.
llvm::Expected<std::string>
encodeFinalizedProjection(const BackendProjectionGraph &graph);

llvm::Expected<BackendProjectionGraph>
decodeFinalizedProjection(llvm::StringRef bytes);

} // namespace projection
} // namespace neutrino

#endif // NEUTRINO_BACKEND_PROJECTION_CODEC_H
