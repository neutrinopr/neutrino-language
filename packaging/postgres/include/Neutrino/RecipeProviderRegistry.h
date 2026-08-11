//===- RecipeProviderRegistry.h - target -> provider package discovery ----===//
//
// The mechanical package-discovery seam (boundary contract §8): a target-blind
// map from a governed target name to the factory that builds its
// `TargetRecipeProvider`. The generic runtime resolves a provider purely by the
// target string carried on a `FinalizedIdiomKey`; it never names a backend.
//
// This registry holds only string keys and opaque factory callbacks — it links
// no backend and makes no semantic decision. A backend package registers its
// provider factory from its OWN wiring translation unit; wiring the real
// solidity/postgres factories in is the extraction step (+), NOT part of
// the generic substrate. The synthetic test provider registers itself the same
// way.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_RECIPEPROVIDERREGISTRY_H
#define NEUTRINO_RECIPEPROVIDERREGISTRY_H

#include "Neutrino/RecipeRuntime.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <functional>
#include <memory>
#include <vector>

namespace neutrino {
namespace recipe {

// A factory that builds one fresh provider instance for a target package.
using ProviderFactory = std::function<std::unique_ptr<TargetRecipeProvider>()>;

// The process-wide, target-keyed provider registry. Exactly one factory per
// target; a duplicate registration for the same target fails closed. Discovery
// is by exact target string — no wildcard, priority, or default.
class RecipeProviderRegistry {
public:
  static RecipeProviderRegistry &get();

  // Register a package's provider factory. Fails (`operation_forbidden`) if the
  // target is already registered — registration is exact and single-owner.
  llvm::Error registerProvider(llvm::StringRef target, ProviderFactory factory);

  // Build the provider for an exact target, or fail closed (`resolver_zero`) if
  // no package owns it.
  llvm::Expected<std::unique_ptr<TargetRecipeProvider>>
  create(llvm::StringRef target) const;

  bool has(llvm::StringRef target) const;

  // The sorted set of registered targets (for diagnostics / listing).
  std::vector<llvm::StringRef> targets() const;

  // Test-only: drop a registration so a fixture can re-register cleanly.
  void unregisterForTesting(llvm::StringRef target);

private:
  RecipeProviderRegistry() = default;
  struct Entry {
    std::string target;
    ProviderFactory factory;
  };
  std::vector<Entry> entries;
};

} // namespace recipe
} // namespace neutrino

#endif // NEUTRINO_RECIPEPROVIDERREGISTRY_H
