// SPDX-License-Identifier: Apache-2.0
//===- RecipeModuleTest.cpp - generated recipe module + exact-key resolver ==//
//
// Exercises the  generator end-to-end: the synthetic fixture
// (test/recipe/SyntheticIdiomRecipes.td) is run through
// gen_backend_idiom_recipes.py at build time into `synthetic_recipes.inc`, and
// these tests assert the generated RecipeModule structure, the reachable-key
// manifest, exact-key resolution (incl. fail-closed resolver_zero), and the
// flattened repeated+nested body (§4.3). Generator-level validation
// (duplicate/cycle/result/undeclared-field) is enforced fail-closed at
// generation time; an automated generator-mutation harness is a follow-up.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"

#include "llvm/Support/Error.h"

#include "gtest/gtest.h"

// The build-generated module accessor: generated::syntheticRecipeModule().
#include "synthetic_recipes.inc"
// A zero-leaf-hook package's generated module (regression for the empty-table
// fix): its very inclusion + compilation is the regression witness.
#include "zerohook_recipes.inc"

using namespace neutrino::recipe;

namespace {

const RecipeModule &synth() { return generated::syntheticRecipeModule(); }

// Regression: a backend package with NO leaf hooks must still generate a
// COMPILABLE module. An empty hooks table previously emitted `{nullptr, 0}`, an
// ambiguous ArrayRef constructor that failed to compile; the generator now
// emits
// `{}`. Including zerohook_recipes.inc above and this assertion is the witness.
TEST(RecipeModule, ZeroHookPackageGeneratesCompilableEmptyHooks) {
  const RecipeModule &m = generated::zeroHookRecipeModule();
  EXPECT_EQ(m.target, "zerohook");
  EXPECT_EQ(m.hooks.size(), 0u);
  auto idx = resolveRecipe(
      m, {"zerohook", "ZeroHookKind", "NotApplicable", "NotApplicable"});
  EXPECT_TRUE(static_cast<bool>(idx));
  EXPECT_FALSE(m.generationHash.empty());
}

TEST(RecipeModule, GeneratedStructure) {
  const RecipeModule &m = synth();
  EXPECT_EQ(m.target, "synthetic");
  EXPECT_EQ(m.schemaVersion, 1);
  ASSERT_EQ(m.recipes.size(), 2u);
  ASSERT_EQ(m.reachableKeys.size(), 2u);
  ASSERT_EQ(m.hooks.size(), 1u);
  EXPECT_EQ(m.hooks[0].hookId, "synthetic.identifier.escape");
  EXPECT_EQ(m.hooks[0].kind, "identifier.escape");
  EXPECT_EQ(m.hooks[0].impl, "synthEscapeIdentifier");
  EXPECT_FALSE(m.generationHash.empty()); // freshness digest present
}

TEST(RecipeModule, ExactKeyResolves) {
  const RecipeModule &m = synth();
  auto block = resolveRecipe(
      m, {"synthetic", "SyntheticBlock", "NotApplicable", "NotApplicable"});
  ASSERT_TRUE(static_cast<bool>(block));
  EXPECT_EQ(m.recipes[*block].recipeId, "synthetic.block.v1");

  auto arm = resolveRecipe(
      m, {"synthetic", "SyntheticGroup", "NotApplicable", "NotApplicable"});
  ASSERT_TRUE(static_cast<bool>(arm));
  EXPECT_EQ(m.recipes[*arm].recipeId, "synthetic.arm.v1");
}

TEST(RecipeModule, UnknownKeyFailsClosed) {
  const RecipeModule &m = synth();
  auto r =
      resolveRecipe(m, {"synthetic", "Nope", "NotApplicable", "NotApplicable"});
  ASSERT_FALSE(static_cast<bool>(r));
  std::string msg = llvm::toString(r.takeError());
  EXPECT_EQ(msg.rfind("idiom.recipe.resolver_zero", 0), 0u);
}

// The block recipe flattens to Emit<SynthBlock>[ Nested<arms> ->
// ForEach<groups>
// -> Call<synthetic.arm.v1> ] — the §4.3 repeated+nested shape.
TEST(RecipeModule, RepeatedNestedBodyFlattened) {
  const RecipeModule &m = synth();
  auto blockIdx = resolveRecipe(
      m, {"synthetic", "SyntheticBlock", "NotApplicable", "NotApplicable"});
  ASSERT_TRUE(static_cast<bool>(blockIdx));
  const RecipeRow &block = m.recipes[*blockIdx];

  const BodyRow &top = m.bodies[block.body];
  ASSERT_EQ(top.opsEnd - top.opsBegin, 1);
  const OpRow &emit = m.ops[top.opsBegin];
  EXPECT_EQ(emit.kind, OpKind::Emit);
  EXPECT_EQ(emit.node, "SynthBlock");
  ASSERT_EQ(emit.bindingsEnd - emit.bindingsBegin, 1);

  const BindingRow &nested = m.bindings[emit.bindingsBegin];
  EXPECT_EQ(nested.kind, BindKind::Nested);
  EXPECT_EQ(nested.field, "arms");
  ASSERT_GE(nested.nestedBody, 0);

  const BodyRow &arms = m.bodies[nested.nestedBody];
  ASSERT_EQ(arms.opsEnd - arms.opsBegin, 1);
  const OpRow &forEach = m.ops[arms.opsBegin];
  EXPECT_EQ(forEach.kind, OpKind::ForEach);
  EXPECT_EQ(forEach.slot, "groups");
  ASSERT_GE(forEach.body, 0);

  const BodyRow &per = m.bodies[forEach.body];
  ASSERT_EQ(per.opsEnd - per.opsBegin, 1);
  const OpRow &call = m.ops[per.opsBegin];
  EXPECT_EQ(call.kind, OpKind::Call);
  EXPECT_EQ(call.recipeId, "synthetic.arm.v1");

  // The `groups` slot is the projection-ordered many slot.
  const SlotRow &groups = m.slots[block.slotsBegin];
  EXPECT_EQ(groups.name, "groups");
  EXPECT_EQ(groups.cardinality, Cardinality::Many);
  EXPECT_EQ(groups.min, 1u);
  EXPECT_EQ(groups.max, ResultCardinality::kUnbounded);
  EXPECT_EQ(groups.orderKey, "group.ordinal");
}

} // namespace
