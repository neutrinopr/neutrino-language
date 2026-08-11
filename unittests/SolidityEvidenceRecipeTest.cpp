//===- SolidityEvidenceRecipeTest.cpp -  real-package integration
//------===//
//
// Integration test for the  Solidity evidence recipe layer against the REAL
// rekeyed + package: lib/backends/solidity/recipes/SolidityIdiomRecipes.td (the
//  guard consumers) `include`s SolidityEvidenceIdiomRecipes.td (the
// full evidence-contract recipe), generated here through the production
// generator. Asserts the reachable evidence key is owned by the full contract
// recipe (not the guard), that the guard is a distinct-keyed internal recipe,
// and that the contract recipe CONSUMES the guard through its typed
// `guardHeader` nested field via a Call — the result algebra the review
// required (no heterogeneous sibling sequence, no stand-in fixture).
//
// The full runtime render of the combined recipe lands with the provider
// consumption + printer shape (the atomic  co-land); C's
// SolidityRecipeProvider owns that runtime surface.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include "gtest/gtest.h"

// : the generated package's optional-slot extent resolver
// (solidityOptionalSlotExtent) mechanically reads the finalized posting
// projection, so this direct consumer must see its full definition.
#include "Neutrino/BackendProjection.h"

// The build-generated REAL package module: generated::solidityPackage*.
#include "solidity_package_recipes.inc"

using namespace neutrino::recipe;
using namespace neutrino::recipe::generated;
using llvm::StringRef;

namespace {

const RecipeModule &pkg() { return solidityPackageRecipeModule(); }

const FinalizedIdiomKey kEvidenceKey{"solidity", "QuorumAcceptance.Single",
                                     "Evidence", "NotApplicable"};
const FinalizedIdiomKey kGuardKey{"solidity", "GuardConsumer", "Evidence",
                                  "NotApplicable"};

// The full evidence-contract recipe owns the reachable evidence key; the
// guard consumer is a DISTINCT-keyed internal recipe; exactly one recipe owns
// the evidence dispatch tuple (the generator fail-closes on a duplicate).
TEST(SolidityEvidenceRecipe, PackageReachableKeyOwnedByFullContract) {
  const RecipeModule &m = pkg();

  auto idx = resolveRecipe(m, kEvidenceKey);
  ASSERT_TRUE(static_cast<bool>(idx));
  EXPECT_EQ(m.recipes[*idx].recipeId, "solidity.evidence.contract.v1");

  auto gidx = resolveRecipe(m, kGuardKey);
  ASSERT_TRUE(static_cast<bool>(gidx));
  EXPECT_EQ(m.recipes[*gidx].recipeId, "solidity.guard-consumer.evidence.v1");
  EXPECT_NE(*idx, *gidx);

  int owners = 0;
  for (const RecipeRow &r : m.recipes)
    if (StringRef(r.key.finalizedKind) == "QuorumAcceptance.Single" &&
        StringRef(r.key.mode) == "Evidence" &&
        StringRef(r.key.role) == "NotApplicable")
      ++owners;
  EXPECT_EQ(owners, 1);
}

// The full contract recipe CONSUMES the guard through its typed `guardHeader`
// nested field — a Call to the internal guard-consumer, never a heterogeneous
// sibling sequence.
TEST(SolidityEvidenceRecipe, FullContractConsumesGuardViaNestedField) {
  const RecipeModule &m = pkg();

  auto idx = resolveRecipe(m, kEvidenceKey);
  ASSERT_TRUE(static_cast<bool>(idx));
  const RecipeRow &contract = m.recipes[*idx];

  const BodyRow &top = m.bodies[contract.body];
  ASSERT_EQ(top.opsEnd - top.opsBegin, 1);
  const OpRow &emit = m.ops[top.opsBegin];
  EXPECT_EQ(emit.kind, OpKind::Emit);
  EXPECT_EQ(emit.node, "SolEvidenceContract");

  bool guardConsumed = false;
  for (int b = emit.bindingsBegin; b < emit.bindingsEnd; ++b) {
    const BindingRow &bind = m.bindings[b];
    if (bind.field != "guardHeader")
      continue;
    EXPECT_EQ(bind.kind, BindKind::Nested);
    ASSERT_GE(bind.nestedBody, 0);
    const BodyRow &gb = m.bodies[bind.nestedBody];
    ASSERT_EQ(gb.opsEnd - gb.opsBegin, 1);
    const OpRow &call = m.ops[gb.opsBegin];
    EXPECT_EQ(call.kind, OpKind::Call);
    EXPECT_EQ(call.recipeId, "solidity.guard-consumer.evidence.v1");
    guardConsumed = true;
  }
  EXPECT_TRUE(guardConsumed);
}

} // namespace
