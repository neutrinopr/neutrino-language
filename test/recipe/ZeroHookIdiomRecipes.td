//===- ZeroHookIdiomRecipes.td - test-only zero-leaf-hook package ----------===//
//
// A minimal SYNTHETIC, test-only backend package that declares NO leaf hooks —
// the regression fixture for the empty-recipe-table generator fix. A package
// with zero hooks emitted an ambiguous `ArrayRef` constructor (`{nullptr, 0}`)
// that failed to compile; the generator now emits `{}`. Target `"zerohook"` is
// test-only and drives no extraction. RecipeModuleTest.cpp includes the
// generated module and asserts it has zero hooks (its very compilation is the
// regression — before the fix this `.inc` did not compile).
//
//===----------------------------------------------------------------------===//

include "BackendIdiom.td"

def FinalizedZeroHookValue : FinalizedType<"FinalizedZeroHookValue", [
  FinalizedField<"label", "TargetIdentifierAtom">
]>;

def ZeroHookNode : TargetNode<"ZeroHookNode", "ZeroHookCat", [
  TargetField<"label", "value", "TargetIdentifierAtom">
]>;

// One recipe, one direct value binding, and — deliberately — NO RegisterLeafHook.
def ZeroHookRecipe : TargetIdiomRecipe<
  "zerohook.value.v1", "zerohook",
  "ZeroHookKind", "NotApplicable", "NotApplicable",
  [One<"value", "FinalizedZeroHookValue">],
  "ZeroHookCat", CardinalityOne,
  Sequence<[
    Emit<"ZeroHookNode", [Direct<"label", "value.label">]>
  ]>
>;
