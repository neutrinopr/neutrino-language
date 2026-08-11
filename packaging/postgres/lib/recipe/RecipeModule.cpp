//===- RecipeModule.cpp - exact-key resolution over a generated module ----===//
//
// Generic, target-blind resolution of a FinalizedIdiomKey against a generated
// RecipeModule (boundary contract §3.1). The generator already guarantees each
// reachable key is unique; the multiple-match branch is defense in depth.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"

using namespace llvm;

namespace neutrino {
namespace recipe {

Expected<int> resolveRecipe(const RecipeModule &module,
                            const FinalizedIdiomKey &key) {
  int found = -1;
  int count = 0;
  for (const KeyRow &row : module.reachableKeys) {
    if (row.key == key) {
      found = row.recipe;
      ++count;
    }
  }
  std::string k =
      key.target + "|" + key.finalizedKind + "|" + key.mode + "|" + key.role;
  if (count == 0)
    return recipeError(RecipeDiagnostic::ResolverZero, k);
  if (count > 1)
    return recipeError(RecipeDiagnostic::ResolverMultiple, k);
  return found;
}

} // namespace recipe
} // namespace neutrino
