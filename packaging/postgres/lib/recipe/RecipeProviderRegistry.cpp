//===- RecipeProviderRegistry.cpp - target -> provider package discovery --===//
//
// The mechanical, target-blind discovery map (boundary contract §8). It stores
// only string keys and opaque factory callbacks and links no backend; the
// concrete factories are registered by each backend package's own wiring TU
// (extraction, +) or, in tests, by the synthetic fixture.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeProviderRegistry.h"

#include "llvm/ADT/STLExtras.h"

#include <algorithm>

using namespace llvm;

namespace neutrino {
namespace recipe {

RecipeProviderRegistry &RecipeProviderRegistry::get() {
  static RecipeProviderRegistry instance;
  return instance;
}

Error RecipeProviderRegistry::registerProvider(StringRef target,
                                               ProviderFactory factory) {
  if (has(target))
    return recipeError(RecipeDiagnostic::OperationForbidden,
                       "duplicate provider registration for target " + target);
  entries.push_back({target.str(), std::move(factory)});
  return Error::success();
}

Expected<std::unique_ptr<TargetRecipeProvider>>
RecipeProviderRegistry::create(StringRef target) const {
  for (const Entry &e : entries)
    if (e.target == target)
      return e.factory();
  return recipeError(RecipeDiagnostic::ResolverZero,
                     "no provider registered for target " + target);
}

bool RecipeProviderRegistry::has(StringRef target) const {
  return llvm::any_of(entries,
                      [&](const Entry &e) { return e.target == target; });
}

std::vector<StringRef> RecipeProviderRegistry::targets() const {
  std::vector<StringRef> out;
  out.reserve(entries.size());
  for (const Entry &e : entries)
    out.push_back(e.target);
  llvm::sort(out);
  return out;
}

void RecipeProviderRegistry::unregisterForTesting(StringRef target) {
  entries.erase(
      std::remove_if(entries.begin(), entries.end(),
                     [&](const Entry &e) { return e.target == target; }),
      entries.end());
}

} // namespace recipe
} // namespace neutrino
