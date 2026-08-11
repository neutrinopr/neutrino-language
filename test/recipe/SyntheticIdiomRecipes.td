//===- SyntheticIdiomRecipes.td - test-only recipe fixture () ----------===//
//
// A SYNTHETIC, non-production backend package fixture that exercises the whole
//  recipe meta-model end-to-end: repeated projection groups consumed by a
// nested target-node field (§4.3). Target `"synthetic"` is a test-only governed
// target — it is NOT solidity/postgres and drives NO extraction (-).
// Named `*IdiomRecipes.td` under test/ so the generator can consume it while the
// production backend-discovery globs never do.
//
//===----------------------------------------------------------------------===//

include "BackendIdiom.td"

// The finalized value type this package projects from: a synthetic group with a
// typed identifier label and a projection-owned ordinal (§3.5 field schema).
def FinalizedSyntheticGroup : FinalizedType<"FinalizedSyntheticGroup", [
  FinalizedField<"label", "TargetIdentifierAtom">,
  FinalizedField<"ordinal", "SyntheticOrdinal">
]>;

// The target-node field schema (§3.6): SynthArm (category ArmCat) has one leaf
// label; SynthBlock (category StmtCat) has one repeated `arms` field accepting
// one-or-more children of the ArmCat category.
def SynthArmNode : TargetNode<"SynthArm", "ArmCat", [
  TargetField<"label", "leaf", "EscapedIdentifier">
]>;
def SynthBlockNode : TargetNode<"SynthBlock", "StmtCat", [
  TargetField<"arms", "nodes", "ArmCat", "many", 1, "unbounded">
]>;

// An arm recipe over exactly one finalized group: emits one SynthArm whose
// `label` field is the group's typed `label` run through the pure identifier
// escape hook (exercises the §5 leaf-hook path end-to-end).
def SynthArmRecipe : TargetIdiomRecipe<
  "synthetic.arm.v1", "synthetic",
  "SyntheticGroup", "NotApplicable", "NotApplicable",
  [One<"group", "FinalizedSyntheticGroup">],
  "ArmCat", CardinalityOne,
  Sequence<[
    Emit<"SynthArm",
         [Hook<"label", "synthetic.identifier.escape", "group.label">]>
  ]>
>;

// A block recipe over a repeated, projection-ordered group slot. `ForEach`
// preserves the `group.ordinal` order and `Call`s the arm per item; the whole
// `RecipeResult<SynthArm, many(1,unbounded)>` is consumed once by the nested
// `SynthBlock.arms` repeated field; the outer `Emit` returns one SynthBlock.
def SynthBlockRecipe : TargetIdiomRecipe<
  "synthetic.block.v1", "synthetic",
  "SyntheticBlock", "NotApplicable", "NotApplicable",
  [Many<"groups", "FinalizedSyntheticGroup", 1, "unbounded", "group.ordinal">],
  "StmtCat", CardinalityOne,
  Sequence<[
    Emit<"SynthBlock", [
      Nested<"arms", Sequence<[
        ForEach<"groups", Sequence<[
          Call<"synthetic.arm.v1", [Direct<"group", "groups.item">]>
        ]>>
      ]>>
    ]>
  ]>
>;

// The package's closed leaf-hook registry: one pure identifier-escape hook.
def SynthIdentifierEscape : RegisterLeafHook<
  "synthetic.identifier.escape", HookIdentifierEscape, "synthEscapeIdentifier">;
