// SPDX-License-Identifier: Apache-2.0
//===- RecipeRuntimeTest.cpp - generic recipe runtime diagnostics ---------===//
//
// Focused unit coverage for the target-blind recipe runtime foundation ():
// the stable §3.7 diagnostic codes and the fail-closed `recipeError` carrier.
// Traversal/resolution tests land with the generator + synthetic fixture.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeRuntime.h"

#include "llvm/Support/Error.h"

#include "gtest/gtest.h"

#include <set>
#include <string>
#include <utility>

using namespace neutrino::recipe;

namespace {

// Every §3.7 diagnostic maps to its exact stable string; codes are distinct.
TEST(RecipeRuntime, DiagnosticCodesAreStableAndDistinct) {
  const std::pair<RecipeDiagnostic, const char *> table[] = {
      {RecipeDiagnostic::Version, "idiom.recipe.version"},
      {RecipeDiagnostic::ResolverZero, "idiom.recipe.resolver_zero"},
      {RecipeDiagnostic::ResolverMultiple, "idiom.recipe.resolver_multiple"},
      {RecipeDiagnostic::TargetMismatch, "idiom.recipe.target_mismatch"},
      {RecipeDiagnostic::InputUnbound, "idiom.recipe.input_unbound"},
      {RecipeDiagnostic::InputType, "idiom.recipe.input_type"},
      {RecipeDiagnostic::CardinalityError, "idiom.recipe.cardinality"},
      {RecipeDiagnostic::ResultType, "idiom.recipe.result_type"},
      {RecipeDiagnostic::ResultCardinality, "idiom.recipe.result_cardinality"},
      {RecipeDiagnostic::ResultConsumption, "idiom.recipe.result_consumption"},
      {RecipeDiagnostic::Order, "idiom.recipe.order"},
      {RecipeDiagnostic::Cycle, "idiom.recipe.cycle"},
      {RecipeDiagnostic::Session, "idiom.recipe.session"},
      {RecipeDiagnostic::Finish, "idiom.recipe.finish"},
      {RecipeDiagnostic::HookMissing, "idiom.recipe.hook_missing"},
      {RecipeDiagnostic::HookType, "idiom.recipe.hook_type"},
      {RecipeDiagnostic::HookExecution, "idiom.recipe.hook_execution"},
      {RecipeDiagnostic::HookLifetime, "idiom.recipe.hook_lifetime"},
      {RecipeDiagnostic::OperationForbidden,
       "idiom.recipe.operation_forbidden"},
      {RecipeDiagnostic::Reachback, "idiom.recipe.reachback"},
  };
  std::set<std::string> seen;
  for (const auto &[diag, code] : table) {
    EXPECT_EQ(diagnosticCode(diag), code);
    EXPECT_TRUE(seen.insert(code).second) << "duplicate code " << code;
  }
  // The whole closed §3.7 vocabulary is covered.
  EXPECT_EQ(seen.size(), 20u);
}

// `recipeError` produces a fail-closed Error carrying the exact stable code,
// with the detail appended after a separator.
TEST(RecipeRuntime, RecipeErrorCarriesStableCode) {
  llvm::Error e =
      recipeError(RecipeDiagnostic::ResolverZero, "no recipe for k");
  std::string msg = llvm::toString(std::move(e));
  EXPECT_EQ(msg, "idiom.recipe.resolver_zero: no recipe for k");

  llvm::Error bare = recipeError(RecipeDiagnostic::Cycle);
  EXPECT_EQ(llvm::toString(std::move(bare)), "idiom.recipe.cycle");
}

// The exact resolution key compares by all four closed components.
TEST(RecipeRuntime, FinalizedIdiomKeyEqualityIsExact) {
  FinalizedIdiomKey a{"postgres", "QuorumAcceptance.Single", "Evidence",
                      "Success"};
  FinalizedIdiomKey b = a;
  EXPECT_TRUE(a == b);
  b.role = "Initial";
  EXPECT_FALSE(a == b);
}

} // namespace
