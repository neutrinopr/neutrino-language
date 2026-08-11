//===- L2Imports.cpp - versioned L2 domain import resolution ()
//--------===//
//
// Resolve a domain's l2.import records against a versioned domain REGISTRY (the
// cross-rail catalog). DATA-driven ( §2): the registry is ordinary JSON,
// and resolution is a version-keyed graph walk over it — no compiled-in
// knowledge of any domain.
//
// GOVERNANCE ( review): the transitive graph is NOT read from an unchecked
// catalog annotation. For each (capability, version) target the resolver loads
// the fixture's referenced v2 domain-semantics sidecar, VALIDATES it
// (recomputes its domainSemanticsHash via the same contract the
// emitter/validator use), checks that hash against the catalog pin and the
// sidecar's implements/version against the edge, and reads the transitive edges
// from the SIDECAR's own imports. So every edge traces to a hash-pinned,
// validated artifact and cannot drift. It fails CLOSED and DISTINCTLY on a
// dangling, unknown-version, ambiguous, cyclic, or ungoverned
// (missing/invalid/hash-mismatch) mapping.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/L2Imports.h"
#include "Neutrino/GenDomainSemantics.h"

#include "mlir/IR/BuiltinOps.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/StringMap.h"
#include "llvm/ADT/StringSet.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"

#include <algorithm>
#include <functional>
#include <string>
#include <utility>
#include <vector>

using namespace mlir;
using namespace neutrino;

namespace {
using Edge = std::pair<std::string, std::string>; // (capability, version)

llvm::Error importError(llvm::StringRef code, const llvm::Twine &msg) {
  return llvm::createStringError(llvm::inconvertibleErrorCode(),
                                 (code + ": " + msg).str());
}

// A (capability, version) graph key. \x1f (unit separator) cannot appear in a
// capability id or a semantic version, so the join is unambiguous.
std::string nodeKey(llvm::StringRef cap, llvm::StringRef ver) {
  return (cap + llvm::StringRef("\x1f", 1) + ver).str();
}

// A governed registry entry: the v2 sidecar that provides this domain's
// imports, plus the catalog's hash pin for it.
struct Entry {
  std::string l2v2Path;
  std::string l2v2Hash;
};

// The registry, indexed for version-keyed resolution. A capability may be
// published at several versions (normal); a given (capability, version) in more
// than one fixture IS ambiguous.
struct Registry {
  llvm::StringSet<> capabilities;  // every capabilityId present
  llvm::StringMap<int> exactCount; // nodeKey -> #fixtures at that version
  llvm::StringMap<Entry> entry;    // nodeKey -> the (first) governed entry
};

llvm::Expected<Registry> parseRegistry(const llvm::json::Object &registry) {
  const llvm::json::Array *fixtures = registry.getArray("fixtures");
  if (!fixtures)
    return importError("domain.import.dangling",
                       "registry has no 'fixtures' array");
  Registry reg;
  for (const llvm::json::Value &fv : *fixtures) {
    const llvm::json::Object *f = fv.getAsObject();
    if (!f)
      return importError("domain.import.dangling",
                         "registry fixture is not an object");
    auto cap = f->getString("capabilityId");
    auto ver = f->getString("capabilityVersion");
    if (!cap || !ver)
      return importError(
          "domain.import.dangling",
          "registry fixture missing capabilityId/capabilityVersion");
    reg.capabilities.insert(*cap);
    std::string key = nodeKey(*cap, *ver);
    reg.exactCount[key]++;
    Entry e;
    if (auto p = f->getString("l2v2"))
      e.l2v2Path = p->str();
    if (auto h = f->getString("l2v2Hash"))
      e.l2v2Hash = h->str();
    reg.entry.try_emplace(key, std::move(e));
  }
  return reg;
}

// Load, validate, and hash-pin-check the governed v2 sidecar for (cap, ver),
// then return its imports as the transitive edges. Fails closed if the artifact
// is missing, invalid, or does not match the catalog pin / edge identity.
llvm::Expected<std::vector<Edge>> governedEdges(const Entry &e,
                                                llvm::StringRef cap,
                                                llvm::StringRef ver,
                                                llvm::StringRef registryRoot) {
  if (e.l2v2Path.empty() || e.l2v2Hash.empty())
    return importError("domain.import.ungoverned",
                       "import '" + cap + "' at version '" + ver +
                           "' has no governed v2 sidecar (l2v2 + l2v2Hash) in "
                           "the registry");
  // A governed reference is repository-root-relative (the cross-rail catalog
  // path contract). Reject an absolute path or a '..' escape so a registry can
  // only reference committed, in-tree artifacts.
  if (llvm::sys::path::is_absolute(e.l2v2Path))
    return importError("domain.import.ungoverned",
                       "governed v2 sidecar path '" + e.l2v2Path +
                           "' must be repository-root-relative, not absolute");
  for (llvm::StringRef comp :
       llvm::make_range(llvm::sys::path::begin(e.l2v2Path),
                        llvm::sys::path::end(e.l2v2Path)))
    if (comp == "..")
      return importError("domain.import.ungoverned",
                         "governed v2 sidecar path '" + e.l2v2Path +
                             "' must not escape the repository root ('..')");
  llvm::SmallString<256> path(registryRoot);
  llvm::sys::path::append(path, e.l2v2Path);
  auto buf = llvm::MemoryBuffer::getFile(path);
  if (!buf)
    return importError("domain.import.ungoverned",
                       "cannot read governed v2 sidecar '" + e.l2v2Path +
                           "' for import '" + cap + "'");
  llvm::Expected<llvm::json::Value> j = llvm::json::parse((*buf)->getBuffer());
  if (!j || !j->getAsObject())
    return importError("domain.import.ungoverned",
                       "governed v2 sidecar '" + e.l2v2Path +
                           "' is not a JSON object");
  const llvm::json::Object &sidecar = *j->getAsObject();
  // Validate the artifact itself (shape + verifier + RECOMPUTED hash), so a
  // forged sidecar whose internal hash was hand-edited is rejected here.
  if (llvm::Error err = validateDomainSemanticsSidecarV2(sidecar))
    return importError("domain.import.ungoverned",
                       "governed v2 sidecar for import '" + cap +
                           "' is invalid: " + llvm::toString(std::move(err)));
  auto storedHash = sidecar.getString("domainSemanticsHash");
  if (!storedHash || *storedHash != e.l2v2Hash)
    return importError("domain.import.ungoverned",
                       "governed v2 sidecar for import '" + cap +
                           "' has hash that does not match the catalog pin "
                           "l2v2Hash");
  auto impl = sidecar.getString("implements");
  auto sver = sidecar.getString("version");
  if (impl != cap || sver != ver)
    return importError("domain.import.ungoverned",
                       "governed v2 sidecar for import '" + cap + "@" + ver +
                           "' declares implements/version that do not match");
  // The sidecar's imports use {capability, version} (the l2.import shape), and
  // validateDomainSemanticsSidecarV2 already proved their shape.
  std::vector<Edge> edges;
  if (const llvm::json::Array *imps = sidecar.getArray("imports"))
    for (const llvm::json::Value &iv : *imps) {
      const llvm::json::Object *io = iv.getAsObject();
      if (!io)
        return importError("domain.import.ungoverned",
                           "governed v2 sidecar for '" + cap +
                               "' has a malformed import edge");
      auto icap = io->getString("capability");
      auto iver = io->getString("version");
      if (!icap || !iver)
        return importError("domain.import.ungoverned",
                           "governed v2 sidecar for '" + cap +
                               "' has a malformed import edge");
      edges.push_back({icap->str(), iver->str()});
    }
  return edges;
}

// Resolve one edge target to its version-keyed registry node DISTINCTLY, then
// return the governed transitive edges read from its validated v2 sidecar.
llvm::Expected<std::vector<Edge>> resolveNode(const Registry &reg,
                                              llvm::StringRef cap,
                                              llvm::StringRef ver,
                                              llvm::StringRef registryRoot) {
  if (!reg.capabilities.contains(cap))
    return importError("domain.import.dangling",
                       "import '" + cap +
                           "' resolves to no capability in the registry");
  std::string key = nodeKey(cap, ver);
  auto count = reg.exactCount.find(key);
  if (count == reg.exactCount.end())
    return importError("domain.import.unknown",
                       "import '" + cap + "' at version '" + ver +
                           "' is not published in the registry");
  if (count->second > 1)
    return importError("domain.import.ambiguous",
                       "import '" + cap + "' at version '" + ver +
                           "' resolves to " + llvm::Twine(count->second) +
                           " registry entries");
  return governedEdges(reg.entry.find(key)->second, cap, ver, registryRoot);
}
} // namespace

llvm::Expected<DomainImports> neutrino::resolveDomainImports(
    llvm::StringRef domainId, llvm::StringRef domainVersion,
    llvm::ArrayRef<ResolvedImport> directImports,
    const llvm::json::Object &registry, llvm::StringRef registryRoot) {
  llvm::Expected<Registry> reg = parseRegistry(registry);
  if (!reg)
    return reg.takeError();

  DomainImports resolved;
  resolved.domain = domainId.str();

  // The root's out-edges are the domain's own imports (the authoritative
  // source), sorted so the first error is deterministic.
  std::vector<Edge> rootEdges;
  for (const ResolvedImport &r : directImports)
    rootEdges.push_back({r.capability, r.version});
  llvm::sort(rootEdges);

  // Version-keyed DFS resolving and validating EVERY transitive edge from the
  // governed v2 artifacts, with version-aware cycle detection over
  // (capability, version) nodes.
  llvm::StringSet<> onStack, done;
  std::vector<std::string> stack;
  std::function<llvm::Error(llvm::StringRef, llvm::StringRef,
                            llvm::ArrayRef<Edge>)>
      dfs = [&](llvm::StringRef cap, llvm::StringRef ver,
                llvm::ArrayRef<Edge> edges) -> llvm::Error {
    std::string key = nodeKey(cap, ver);
    onStack.insert(key);
    stack.push_back((cap + "@" + ver).str());
    for (const Edge &e : edges) {
      std::string ekey = nodeKey(e.first, e.second);
      if (onStack.contains(ekey)) {
        std::string path;
        for (const std::string &n : stack)
          path += n + " -> ";
        path += e.first + "@" + e.second;
        return importError("domain.import.cyclic",
                           "import graph contains a cycle: " + path);
      }
      if (done.contains(ekey))
        continue;
      llvm::Expected<std::vector<Edge>> childEdges =
          resolveNode(*reg, e.first, e.second, registryRoot);
      if (!childEdges)
        return childEdges.takeError();
      if (llvm::Error err = dfs(e.first, e.second, *childEdges))
        return err;
    }
    onStack.erase(key);
    done.insert(key);
    stack.pop_back();
    return llvm::Error::success();
  };

  if (llvm::Error e = dfs(resolved.domain, domainVersion, rootEdges))
    return std::move(e);

  for (const Edge &e : rootEdges)
    resolved.imports.push_back({e.first, e.second});
  return resolved;
}

llvm::Expected<DomainImports>
neutrino::resolveDomainImports(l2::DomainOp domain,
                               const llvm::json::Object &registry,
                               llvm::StringRef registryRoot) {
  std::vector<ResolvedImport> direct;
  for (Operation &op : domain.getBody().front())
    if (auto imp = dyn_cast<l2::ImportOp>(op))
      direct.push_back({imp.getCapability().str(), imp.getVersion().str()});
  return resolveDomainImports(domain.getImplements(), domain.getVersion(),
                              direct, registry, registryRoot);
}

std::string neutrino::emitDomainImports(const DomainImports &resolved) {
  llvm::json::Array imports;
  for (const ResolvedImport &r : resolved.imports)
    imports.push_back(llvm::json::Object{{"capability", r.capability},
                                         {"version", r.version}});
  llvm::json::Object root{{"domain", resolved.domain},
                          {"imports", std::move(imports)}};
  return llvm::formatv("{0:2}", llvm::json::Value(std::move(root))).str() +
         "\n";
}
