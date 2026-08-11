#ifndef NEUTRINO_VERSION_H
#define NEUTRINO_VERSION_H

#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"

namespace neutrino {

// A capability semantic version is MAJOR.MINOR.PATCH — exactly three
// dot-separated, non-empty runs of ASCII digits (consistent with the SemVer
// policy in docs/process/VERSIONING.md and the split-into-three-ints in
// scripts/generators/fork_capability.py). Shared by the frontend (clear,
// line-numbered errors) and the ProcedureOp IR verifier (so a hand-written
// .mlir cannot bypass the frontend and fail open).
inline bool isValidSemVer(llvm::StringRef v) {
  llvm::SmallVector<llvm::StringRef, 4> parts;
  v.split(parts, '.');
  if (parts.size() != 3)
    return false;
  for (llvm::StringRef p : parts) {
    if (p.empty())
      return false;
    for (char c : p)
      if (c < '0' || c > '9')
        return false;
  }
  return true;
}

} // namespace neutrino

#endif // NEUTRINO_VERSION_H
