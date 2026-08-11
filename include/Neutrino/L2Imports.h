#ifndef NEUTRINO_L2_IMPORTS_H
#define NEUTRINO_L2_IMPORTS_H

#include "Neutrino/L2Dialect.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// One resolved import edge: a foreign capability at the version it resolved to
// in the registry (equal to the imported version — resolution proves the
// match).
struct ResolvedImport {
  std::string capability;
  std::string version;
};

// The resolution of a domain's imports against a registry (edges sorted by
// capability — canonical).
struct DomainImports {
  std::string domain; // the importing domain's `implements` id
  std::vector<ResolvedImport> imports;
};

// Resolve a domain's l2.import records against a versioned domain REGISTRY (the
// cross-rail catalog shape: a `fixtures` array of {capabilityId,
// capabilityVersion, l2v2, l2v2Hash}), DATA-driven ( §2). The graph is
// keyed by (capability, version) and EVERY transitive edge is resolved from a
// GOVERNED v2 artifact: for each target the resolver loads the fixture's
// referenced v2 domain-semantics sidecar (`l2v2`, repository-root-relative
// under `registryRoot`), VALIDATES it (recomputing its domainSemanticsHash),
// checks the hash against the catalog pin
// (`l2v2Hash`) and the sidecar's implements/version against the edge, and reads
// the transitive edges from the SIDECAR's own imports — never a raw, unchecked
// catalog annotation. Fails CLOSED and DISTINCTLY on:
//   * domain.import.dangling   — the capability is absent from the registry
//   * domain.import.unknown    — present, but not at the imported version
//   * domain.import.ambiguous  — duplicate entries for the exact version
//   * domain.import.cyclic     — the transitive import graph contains a cycle
//   * domain.import.ungoverned — the referenced v2 artifact is missing,
//   invalid,
//                                or its hash / identity does not match the pin
llvm::Expected<DomainImports>
resolveDomainImports(l2::DomainOp domain, const llvm::json::Object &registry,
                     llvm::StringRef registryRoot);

// The same resolution driven from an already-extracted set of direct imports
// (capability, version) instead of an l2.domain — so the v2-sidecar re-ingest
// path can gate reduction on the same version-keyed, transitively-validated
// resolution as the direct IR.
llvm::Expected<DomainImports>
resolveDomainImports(llvm::StringRef domainId, llvm::StringRef domainVersion,
                     llvm::ArrayRef<ResolvedImport> directImports,
                     const llvm::json::Object &registry,
                     llvm::StringRef registryRoot);

// Serialize a DomainImports to deterministic, sorted JSON — an internal
// projection (the resolved import graph), no versioned public contract claim.
std::string emitDomainImports(const DomainImports &resolved);

} // namespace neutrino

#endif // NEUTRINO_L2_IMPORTS_H
