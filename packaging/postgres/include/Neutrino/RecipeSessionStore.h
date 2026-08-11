//===- RecipeSessionStore.h - shared emit-side recipe session store ------===//
//
// Header-only, target-blind helpers for the emit-side of a backend recipe
// provider's build session: the binding recheck, ordered node insertion, the
// single-consumption take, the direct/leaf value read, and the finish-time root
// consumption + unconsumed scan. Every helper addresses the session by the same
// member conventions a provider's `OpaqueBuildSession` subclass exposes
// (`sessionId`, `finalizedValues`, `leafValues`, `nodes`) and validates through
// the generated `RecipeModule`; none reads a backend value or makes a semantic
// decision. The per-node carrier is the provider's own variant type, threaded
// as a template parameter so one store owns nodes of every kind in emit order.
//
// The `backend` label only prefixes the stable fail-closed detail string; the
// `RecipeDiagnostic` code — the identity a caller keys on — is fixed here. Two
// providers (Solidity, PostgreSQL) share this so the confinement/cardinality/
// single-consumption rules live once, not per backend.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_RECIPESESSIONSTORE_H
#define NEUTRINO_RECIPESESSIONSTORE_H

#include "Neutrino/RecipeModule.h"
#include "Neutrino/RecipeRuntime.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/SmallSet.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstddef>
#include <memory>
#include <type_traits>
#include <utility>
#include <vector>

namespace neutrino {
namespace recipe {

// The generated slot descriptor for `slot` (nullptr if unknown), carrying the
// `.parentSlot`/`.presence` columns the `.td` declares.
inline const SlotRow *findSlot(const RecipeModule &module, SlotId slot) {
  for (const SlotRow &row : module.slots)
    if (row.id == slot)
      return &row;
  return nullptr;
}

// The §3.3 result category of a concrete target-node kind (0 when unknown),
// matching the generic runtime's category map default.
inline BackendNodeCategoryId nodeCategory(const RecipeModule &module,
                                          BackendNodeTypeId node) {
  for (const NodeCategoryRow &row : module.nodeCategories)
    if (row.node == node)
      return row.category;
  return 0;
}

// The active projection-context item bound to `slot` (nullptr when none): the
// generated parent-slot edge a nested slot's extent/order/projection follows.
inline const SlotIndex *findParent(llvm::ArrayRef<SlotIndex> ctx, SlotId slot) {
  const auto *found = llvm::find_if(
      ctx, [&](const SlotIndex &item) { return item.slot == slot; });
  return found == ctx.end() ? nullptr : found;
}

// §3.6 mandated recheck: every binding matches its field descriptor by
// identity, kind, type, session confinement, and (for Nodes) child
// count/category — before any node is constructed. Fail-closed on any mismatch;
// the code is stable and the `backend` label only prefixes the detail.
template <typename Session>
llvm::Error recheckBindings(const Session &session, const RecipeModule &module,
                            llvm::ArrayRef<GeneratedFieldBinding> bindings,
                            llvm::ArrayRef<TargetFieldDescriptor> fields,
                            llvm::StringRef backend) {
  if (bindings.size() != fields.size())
    return recipeError(RecipeDiagnostic::ResultCardinality,
                       backend + " target field count");
  for (size_t i = 0; i < fields.size(); ++i) {
    const GeneratedFieldBinding &binding = bindings[i];
    const TargetFieldDescriptor &field = fields[i];
    if (binding.targetField != field.id)
      return recipeError(RecipeDiagnostic::ResultType,
                         backend + " target field identity");
    if (field.kind == TargetFieldKind::Value) {
      if (binding.kind != GeneratedFieldBinding::Kind::Direct ||
          binding.directType != field.typeId)
        return recipeError(RecipeDiagnostic::ResultType,
                           backend + " target value field");
      if (binding.directValue >= session.finalizedValues.size())
        return recipeError(RecipeDiagnostic::InputUnbound,
                           backend + " finalized value ordinal");
      continue;
    }
    if (field.kind == TargetFieldKind::Leaf) {
      if (binding.kind != GeneratedFieldBinding::Kind::Leaf ||
          binding.leaf.session != session.sessionId ||
          binding.leaf.type != field.typeId ||
          binding.leaf.ordinal >= session.leafValues.size())
        return recipeError(RecipeDiagnostic::HookType,
                           backend + " target leaf field");
      continue;
    }
    if (field.kind != TargetFieldKind::Nodes ||
        binding.kind != GeneratedFieldBinding::Kind::Nodes)
      return recipeError(RecipeDiagnostic::ResultType,
                         backend + " target field kind");
    const size_t count = binding.nodes.size();
    if (count < field.card.min ||
        (field.card.max != ResultCardinality::kUnbounded &&
         count > field.card.max))
      return recipeError(RecipeDiagnostic::CardinalityError,
                         backend + " nested node count");
    for (const TargetNodeRef &child : binding.nodes) {
      if (child.session != session.sessionId ||
          child.ordinal >= session.nodes.size())
        return recipeError(RecipeDiagnostic::Session,
                           backend + " nested node reference");
      if (nodeCategory(module, child.type) != field.typeId)
        return recipeError(RecipeDiagnostic::ResultType,
                           backend + " nested node category");
    }
  }
  return llvm::Error::success();
}

// Record one produced node at the next ordinal (emit order) and return its
// non-owning ref. The recheck is the caller's responsibility (done once per
// emit); this owns only the ordered insertion. `Carrier` is the provider's
// per-node variant, stored as `unique_ptr<Carrier>`.
template <typename Session, typename Carrier>
TargetNodeRef storeNode(Session &session, BackendNodeTypeId nodeType,
                        Carrier &&carrier) {
  const NodeOrdinal ordinal = session.nodes.size();
  session.nodes.push_back(
      std::make_unique<std::decay_t<Carrier>>(std::forward<Carrier>(carrier)));
  return TargetNodeRef{session.sessionId, nodeType, ordinal};
}

// Consume the `fieldIndex`-th Nodes field's children exactly once, extracting a
// value of type `T` from each carrier via `extract` (returns `T*`, or nullptr
// when the carrier holds a different kind — surfaced as a RESULT TYPE mismatch,
// distinct from the missing/consumed-slot consumption failure). Each consumed
// slot is cleared so the finish scan sees it gone.
template <typename T, typename Session, typename Extract>
llvm::Expected<std::vector<T>>
takeField(Session &session, const RecipeModule &module,
          llvm::ArrayRef<GeneratedFieldBinding> bindings,
          llvm::ArrayRef<TargetFieldDescriptor> fields, size_t fieldIndex,
          llvm::StringRef backend, llvm::StringRef noun, Extract extract) {
  if (llvm::Error error =
          recheckBindings(session, module, bindings, fields, backend))
    return std::move(error);
  if (fieldIndex >= bindings.size())
    return recipeError(RecipeDiagnostic::CardinalityError,
                       "generated " + backend + " " + noun + " field");
  std::vector<T> out;
  out.reserve(bindings[fieldIndex].nodes.size());
  for (const TargetNodeRef &child : bindings[fieldIndex].nodes) {
    auto &slot = session.nodes[child.ordinal];
    // §3.7 taxonomy: a missing/already-consumed slot is a RESULT CONSUMPTION
    // failure (dropped/reused/split/double-bound); a LIVE slot whose carrier
    // holds a different concrete kind (extract -> null) is a RESULT TYPE
    // mismatch, not a consumption failure. Keep the two distinct so every
    // backend adopting this seam preserves the distinction.
    if (!slot)
      return recipeError(RecipeDiagnostic::ResultConsumption,
                         "generated " + backend + " " + noun + " reused");
    T *carrier = extract(*slot);
    if (!carrier)
      return recipeError(RecipeDiagnostic::ResultType,
                         "generated " + backend + " " + noun + " result type");
    out.push_back(std::move(*carrier));
    slot.reset();
  }
  return out;
}

// Read each binding's rendered operand string: a produced leaf's stored value,
// a direct finalized value, or an empty placeholder for any other kind
// (mirroring the recipe's positional operand contract). Rechecks first.
template <typename Session>
llvm::Expected<std::vector<std::string>>
readValues(Session &session, const RecipeModule &module,
           llvm::ArrayRef<GeneratedFieldBinding> bindings,
           llvm::ArrayRef<TargetFieldDescriptor> fields,
           llvm::StringRef backend) {
  if (llvm::Error error =
          recheckBindings(session, module, bindings, fields, backend))
    return std::move(error);
  std::vector<std::string> values;
  values.reserve(bindings.size());
  for (const GeneratedFieldBinding &binding : bindings) {
    if (binding.kind == GeneratedFieldBinding::Kind::Leaf) {
      if (binding.leaf.session != session.sessionId ||
          binding.leaf.ordinal >= session.leafValues.size())
        return recipeError(RecipeDiagnostic::HookLifetime,
                           backend + " generated leaf binding");
      values.push_back(session.leafValues[binding.leaf.ordinal]);
      continue;
    }
    if (binding.kind != GeneratedFieldBinding::Kind::Direct) {
      values.emplace_back();
      continue;
    }
    if (binding.directValue >= session.finalizedValues.size())
      return recipeError(RecipeDiagnostic::InputUnbound,
                         backend + " finalized value binding");
    values.push_back(session.finalizedValues[binding.directValue]);
  }
  return values;
}

// Finish-time consumption: validate every root ref (session + ordinal), reject
// a reused or already-consumed root, hand each live carrier to `consume` (which
// moves it into the artifact and may fail closed), then prove no produced node
// was left unconsumed. `consume` returns an `llvm::Error`.
template <typename Session, typename Consume>
llvm::Error consumeRoots(Session &session, llvm::ArrayRef<TargetNodeRef> roots,
                         llvm::StringRef backend, Consume consume) {
  llvm::SmallSet<NodeOrdinal, 8> seen;
  for (const TargetNodeRef &root : roots) {
    if (root.session != session.sessionId ||
        root.ordinal >= session.nodes.size())
      return recipeError(RecipeDiagnostic::Session,
                         backend + " root node reference");
    if (!seen.insert(root.ordinal).second)
      return recipeError(RecipeDiagnostic::ResultConsumption,
                         backend + " root node reused");
    auto &slot = session.nodes[root.ordinal];
    if (!slot)
      return recipeError(RecipeDiagnostic::ResultConsumption,
                         backend + " root node has no generated value");
    if (llvm::Error error = consume(*slot))
      return error;
    slot.reset();
  }
  for (const auto &slot : session.nodes)
    if (slot)
      return recipeError(RecipeDiagnostic::Finish,
                         "unconsumed " + backend + " target node");
  return llvm::Error::success();
}

} // namespace recipe
} // namespace neutrino

#endif // NEUTRINO_RECIPESESSIONSTORE_H
