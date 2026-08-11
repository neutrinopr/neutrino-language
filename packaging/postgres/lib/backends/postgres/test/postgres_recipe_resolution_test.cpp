//===- postgres_recipe_resolution_test.cpp - recipe resolver totality -----===//
//
// Focused witness for the PostgreSQL recipes' exact-key resolution: the
// generated recipe module resolves each production key to exactly the intended
// recipe, carries each key exactly once, and fails closed (ResolverZero) on a
// missing key — no fallback, no duplicate. It covers the  evidence
// procedure key and the two coordination-schema keys (temporal per-policy and
// single-quorum). (The byte-preserving end-to-end render is pinned by
// postgres-model-test.)
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"
#include "Neutrino/RecipeRuntime.h"

#include "llvm/Support/Error.h"

#include <cstdio>
#include <string>

#include "postgres_package_recipes.inc" // postgresPackageRecipeModule()

using namespace neutrino::recipe;

// Exact-key resolution + exact identity + exact-one registration for one key.
static bool resolvesUniquelyTo(const RecipeModule &module,
                               const FinalizedIdiomKey &key,
                               const char *expectedRecipeId) {
  auto resolved = resolveRecipe(module, key);
  if (!resolved) {
    std::fprintf(stderr, "FAIL: key did not resolve: %s\n",
                 llvm::toString(resolved.takeError()).c_str());
    return false;
  }
  if (module.recipes[*resolved].recipeId != std::string(expectedRecipeId)) {
    std::fprintf(stderr, "FAIL: key resolved to '%s' (want '%s')\n",
                 module.recipes[*resolved].recipeId.str().c_str(),
                 expectedRecipeId);
    return false;
  }
  // Uniqueness: the reachable-key manifest carries the key exactly once (the
  // generator deduplicates; a duplicate would resolve ResolverMultiple).
  int count = 0;
  for (const KeyRow &row : module.reachableKeys)
    if (row.key == key)
      ++count;
  if (count != 1) {
    std::fprintf(stderr, "FAIL: recipe '%s' key appears %d times (want 1)\n",
                 expectedRecipeId, count);
    return false;
  }
  return true;
}

// Fail closed: the key resolves to nothing (ResolverZero) — no fallback path.
static bool failsClosed(const RecipeModule &module,
                        const FinalizedIdiomKey &key) {
  auto missing = resolveRecipe(module, key);
  if (missing) {
    std::fprintf(stderr, "FAIL: a missing key resolved instead of failing\n");
    return false;
  }
  llvm::consumeError(missing.takeError());
  return true;
}

int main() {
  const RecipeModule &module = generated::postgresPackageRecipeModule();

  // The  evidence procedure recipe.
  if (!resolvesUniquelyTo(
          module,
          {"postgres", "QuorumAcceptance.Single", "Evidence", "NotApplicable"},
          "postgres.evidence.procedure.v1"))
    return 1;

  // The per-rail complete-schema recipes ( B2: base + quorum/temporal).
  if (!resolvesUniquelyTo(
          module,
          {"postgres", "QuorumAcceptance.PerPolicy", "Temporal", "Schema"},
          "postgres.temporal.schema.v1"))
    return 1;
  if (!resolvesUniquelyTo(
          module, {"postgres", "QuorumAcceptance.Single", "Evidence", "Schema"},
          "postgres.evidence.schema.v1"))
    return 1;
  if (!resolvesUniquelyTo(
          module,
          {"postgres", "QuorumAcceptance.Single", "Effectful", "Schema"},
          "postgres.effectful.quorum.schema.v1"))
    return 1;
  if (!resolvesUniquelyTo(
          module, {"postgres", "QuorumAcceptance.None", "Effectful", "Schema"},
          "postgres.effectful.self.schema.v1"))
    return 1;

  // The two  effectful recipes (gated quorum admission / ungated
  // self-attestation).
  if (!resolvesUniquelyTo(
          module,
          {"postgres", "QuorumAcceptance.Single", "Effectful", "NotApplicable"},
          "postgres.effectful.with-attestation.v1"))
    return 1;
  if (!resolvesUniquelyTo(
          module,
          {"postgres", "QuorumAcceptance.None", "Effectful", "NotApplicable"},
          "postgres.effectful.without-attestation.v1"))
    return 1;

  // Fail closed on an unknown finalizedKind (no fallback).
  if (!failsClosed(module,
                   {"postgres", "NoSuchKind", "Evidence", "NotApplicable"}))
    return 1;

  // Fail closed on the effectful neighbor that the driver never emits (a
  // per-policy effectful key has no recipe — the PerPolicy effectful case is
  // unreachable).
  if (!failsClosed(module, {"postgres", "QuorumAcceptance.PerPolicy",
                            "Effectful", "NotApplicable"}))
    return 1;

  // Fail closed on a schema-neighbor: the temporal-schema coordinates with a
  // role that is not the exact "Schema" role must not resolve to the temporal
  // schema recipe (the role coordinate is matched exactly).
  if (!failsClosed(module, {"postgres", "QuorumAcceptance.PerPolicy",
                            "Temporal", "NoSuchRole"}))
    return 1;

  std::printf("postgres-recipe-resolution-test: OK\n");
  return 0;
}
