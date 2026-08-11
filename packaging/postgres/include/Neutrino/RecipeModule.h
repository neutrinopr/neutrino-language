//===- RecipeModule.h - generated recipe-table representation ()
//-------===//
//
// The static data a backend package's generated recipe `.inc` populates and the
// generic runtime interprets. The generator (scripts/generators/
// gen_backend_idiom_recipes.py) emits one `RecipeModule` per backend package
// from its `<Target>IdiomRecipes.td`, having already validated structure,
// duplicate/exact-key resolution, call-DAG acyclicity, and the §3.3
// result/cardinality algebra at generation time.
//
// This representation is target-blind: it names recipe/slot/hook/node identity
// as strings + the opaque IDs from RecipeRuntime.h. The generic runtime walks
// it and dispatches through `TargetRecipeProvider`; it never sees a backend
// type.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_RECIPEMODULE_H
#define NEUTRINO_RECIPEMODULE_H

#include "Neutrino/RecipeRuntime.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"

#include <vector>

namespace neutrino {
namespace recipe {

// §3.4 op kinds and binding kinds (the closed body grammar).
enum class OpKind { Emit, ForEach, OptionalOp, Call };
enum class BindKind { Direct, Hook, Nested };

// A field binding within an Emit/Call. Exactly one interpretation per `kind`.
// The runtime dispatches on the generated IDs; the `field`/`hookId` STRINGS are
// debug/provenance only and are NEVER used for a runtime lookup (§3.5).
//  - Direct: `fieldId` is the typed accessor to project; `slotRef` is the
//            owning slot (a Call argument aliases the callee slot to it);
//  - Hook:   `hook` is the registered §5 hook applied to `fieldId`;
//  - Nested: `nestedBody` indexes a body whose whole result fills the field,
//            proven to be `nestedResult` of `nestedResultType`.
struct BindingRow {
  BindKind kind = BindKind::Direct;
  llvm::StringRef field;         // debug: the target field / callee slot name
  llvm::StringRef hookId;        // debug: the source hook id
  int nestedBody = -1;           // Nested only: index into RecipeModule.bodies
  FinalizedFieldId fieldId = 0;  // Direct/Hook: typed accessor id
  RegisteredHookId hook = 0;     // Hook: registered hook id
  SlotId slotRef = 0;            // Direct: owning/caller slot id
  TargetFieldId targetField = 0; // Emit: the target-node field filled
  BackendNodeCategoryId nestedCategory = 0; // Nested: proven result category
  ResultCardinality nestedResult;           // Nested: proven result cardinality
};

// One ordered recipe operation. Bindings live in RecipeModule.bindings over
// [bindingsBegin, bindingsEnd); `body` indexes a nested body
// (ForEach/OptionalOp). `node`/`slot` strings are debug only; the runtime uses
// `nodeTypeId`/`slotId`.
struct OpRow {
  OpKind kind = OpKind::Emit;
  llvm::StringRef node;     // debug: target-node category name (Emit)
  llvm::StringRef slot;     // debug: slot name (ForEach/OptionalOp)
  llvm::StringRef recipeId; // Call: the exact same-package recipe id
  int bindingsBegin = 0;    // Emit/Call
  int bindingsEnd = 0;
  int body = -1;                    // ForEach/OptionalOp: index into bodies
  BackendNodeTypeId nodeTypeId = 0; // Emit: generated target-node type id
  SlotId slotId = 0;                // ForEach/OptionalOp: generated slot id
};

// A Sequence body: an ordered op range over RecipeModule.ops. An empty range is
// rejected at generation time (§3.4 forbids an empty sequence).
struct BodyRow {
  int opsBegin = 0;
  int opsEnd = 0;
};

// A typed input slot (§3.2). `id` is the generated `SlotId` the runtime uses;
// `name`/`finalizedType`/`orderKey` strings are debug/provenance only.
struct SlotRow {
  llvm::StringRef name;
  llvm::StringRef finalizedType;
  SlotId id = 0;
  FinalizedValueTypeId finalizedTypeId = 0;
  Cardinality cardinality = Cardinality::One;
  unsigned min = 1;
  unsigned max = 1;         // ResultCardinality::kUnbounded for "unbounded"
  llvm::StringRef orderKey; // "many" only
  // Related-optional slots only. `parentSlot` is the generated SlotId of the
  // owning parent slot (0 when none). `presence` is the closed presence-kind
  // ordinal (0 when the provider supplies presence itself) naming WHICH typed
  // predicate on the finalized parent decides a 0/1 optional slot's extent; the
  // generated recipe module resolves it, the provider only dispatches.
  unsigned parentSlot = 0;
  unsigned presence = 0;
};

// A generated typed input-view accessor (§3.5): a `FinalizedFieldId` projecting
// `type` from the finalized value in slot `slot` (a `SlotId`). `debugPath` is
// the source "slot.field" spelling, for diagnostics only.
struct FieldRow {
  FinalizedFieldId id = 0;
  FinalizedValueTypeId type = 0;
  SlotId slot = 0;
  llvm::StringRef debugPath;
};

// One field of a target node's generated schema (§3.6). `typeId` is a value
// type (`Value`), leaf type (`Leaf`), or child result CATEGORY (`Nodes`) per
// `kind`; `card` bounds a `Nodes` field's child count. The builder adapter
// rechecks a binding against this descriptor before constructing the node.
struct NodeFieldRow {
  BackendNodeTypeId node = 0;
  TargetFieldId id = 0;
  llvm::StringRef name; // debug
  TargetFieldKind kind = TargetFieldKind::Value;
  uint32_t typeId = 0;
  ResultCardinality card;
};

// Maps one concrete target-node kind to its §3.3 result category. Several kinds
// may share a category; a recipe/field result is checked by category while
// `emit` still receives the concrete node id.
struct NodeCategoryRow {
  BackendNodeTypeId node = 0;
  BackendNodeCategoryId category = 0;
};

// One recipe row. Slots live in RecipeModule.slots over [slotsBegin, slotsEnd);
// `body` indexes its top-level Sequence in RecipeModule.bodies. `result` is the
// declared result, already proven equal to the §3.3-derived body result.
struct RecipeRow {
  llvm::StringRef recipeId;
  FinalizedIdiomKey key;
  int schemaVersion = 1;
  int slotsBegin = 0;
  int slotsEnd = 0;
  llvm::StringRef resultType; // debug: result category name
  ResultCardinality result;
  int body = 0;
  BackendNodeCategoryId resultCategory = 0; // generated result category id
};

// A registered leaf hook (§5): its stable id, generated numeric id, closed
// kind, and package-local pure implementation symbol.
struct HookRow {
  llvm::StringRef hookId;
  RegisteredHookId id = 0;
  llvm::StringRef kind; // e.g. "identifier.escape"
  llvm::StringRef impl;
  FinalizedValueTypeId inputType = 0; // §3.6 exact hook signature
  BackendLeafTypeId outputType = 0;
};

// One reachable-key manifest entry (= exact-key resolver row). The generator
// guarantees each key resolves to exactly one recipe (no duplicate, no
// wildcard).
struct KeyRow {
  FinalizedIdiomKey key;
  int recipe = 0; // index into RecipeModule.recipes
};

// The one schema version this runtime supports exactly (§3.6 fail-closed).
constexpr int kSupportedSchemaVersion = 1;

// The complete generated recipe module for one backend package.
struct RecipeModule {
  llvm::StringRef target;
  int schemaVersion = 1;
  llvm::ArrayRef<RecipeRow> recipes;
  llvm::ArrayRef<SlotRow> slots;
  llvm::ArrayRef<FieldRow> fields;
  llvm::ArrayRef<NodeFieldRow> nodeFields;
  llvm::ArrayRef<NodeCategoryRow> nodeCategories;
  llvm::ArrayRef<BodyRow> bodies;
  llvm::ArrayRef<OpRow> ops;
  llvm::ArrayRef<BindingRow> bindings;
  llvm::ArrayRef<HookRow> hooks;
  llvm::ArrayRef<KeyRow> reachableKeys; // sorted, deduplicated at gen time
  llvm::StringRef generationHash;       // freshness digest of the module
};

// ---- generic resolution over a generated module ----------------------------
//
// Exact-key resolution (§3.1): returns the single recipe index, or fails closed
// with `resolver_zero` / `resolver_multiple`. (The generator also rejects
// duplicate reachable keys, so `resolver_multiple` is a defense-in-depth
// guard.)
llvm::Expected<int> resolveRecipe(const RecipeModule &module,
                                  const FinalizedIdiomKey &key);

// ---- generic runtime traversal ---------------------------------------------
//
// Interpret a resolved recipe over an ACTIVE build session and return its
// ordered root result nodes, or a fail-closed §3.7 diagnostic. The generic
// runtime owns all traversal — `Emit`/`ForEach`/`Optional`/`Call`/`Nested`,
// cardinality expansion, `Call` argument aliasing, and single-consumption of
// produced leaf/node references — dispatching only through the provider ABI. It
// makes no semantic decision and interprets no backend value.
llvm::Expected<std::vector<TargetNodeRef>>
interpretRecipe(const RecipeModule &module, int recipeIndex,
                const TargetRecipeProvider &provider,
                OpaqueBuildSession &session);

// The target-blind lifecycle seam used when a backend embeds the finished
// recipe artifact into a larger target model. It owns the same validation,
// resolution, begin, traversal, and finish sequence as executeRecipe; callers
// never receive a live session or partial roots.
llvm::Expected<std::unique_ptr<OpaqueTargetArtifact>>
materializeRecipe(const RecipeModule &module,
                  const TargetRecipeProvider &provider,
                  const FinalizedInvocation &invocation);

// ---- atomic top-level execution (§3.6) -------------------------------------
//
// The single generic entrypoint owning the COMPLETE lifecycle: validate target
// + schema version, exact-key resolve, `begin`, `interpretRecipe`, `finish`,
// and render into an INTERNAL buffer committed to `sink` ONLY on full success.
// Any error before commit destroys the session/outputs and leaves `sink`
// untouched — partial target output is never observable (§3.6 rule 9). The
// caller never manages the session or sees a partial render.
llvm::Error executeRecipe(const RecipeModule &module,
                          const TargetRecipeProvider &provider,
                          const FinalizedInvocation &invocation,
                          OutputSink &sink);

} // namespace recipe
} // namespace neutrino

#endif // NEUTRINO_RECIPEMODULE_H
