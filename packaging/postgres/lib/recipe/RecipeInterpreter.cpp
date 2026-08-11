//===- RecipeInterpreter.cpp - generic target-blind recipe traversal ------===//
//
// The generic runtime traversal (boundary contract §3.6): walk a resolved
// recipe's body and dispatch its ordered operations through the
// `TargetRecipeProvider` ABI. The runtime OWNS all proofs — it never trusts the
// provider:
//
//   * slot extents are validated against each slot's declared cardinality;
//   * `many` items are validated to arrive in strictly increasing projection
//     order (§3.2 semantic order ordinals);
//   * every projected value is checked against its accessor's typed id, and
//     every hook input/output against the registered hook signature (§3.6);
//   * every returned leaf/node ref is checked for session confinement and the
//     exact expected type;
//   * every produced leaf/node is consumed exactly once (single-consumption);
//   * nested/callee bodies and the top-level result are checked against the
//     generated result-type/cardinality proofs.
//
// It addresses slots and fields ONLY by generated id (§3.5 — no runtime name or
// path string), makes no semantic decision, and interprets no backend value.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"

#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/StringMap.h"

#include <set>
#include <tuple>
#include <vector>

using namespace llvm;

namespace neutrino {
namespace recipe {

namespace {

using NodeKey =
    std::tuple<uint64_t, uint32_t, uint64_t>; // session,type,ordinal
using LeafKey = std::tuple<uint64_t, uint32_t, uint64_t>;

NodeKey keyOf(const TargetNodeRef &r) { return {r.session, r.type, r.ordinal}; }
LeafKey keyOf(const OpaqueLeafValueRef &r) {
  return {r.session, r.type, r.ordinal};
}

struct Interpreter {
  const RecipeModule &m;
  const TargetRecipeProvider &provider;
  OpaqueBuildSession &session;

  StringMap<int> recipeByName;
  DenseMap<unsigned, int> slotById;  // SlotId -> module.slots index
  DenseMap<unsigned, int> fieldById; // FinalizedFieldId -> module.fields index
  DenseMap<unsigned, int> hookById;  // RegisteredHookId -> module.hooks index
  DenseMap<unsigned, unsigned> categoryOf; // node type id -> category id
  DenseMap<unsigned, std::vector<TargetFieldDescriptor>>
      nodeFieldsOf; // node id

  // Single-consumption bookkeeping.
  std::set<NodeKey> producedNodes, consumedNodes;
  std::set<LeafKey> producedLeaves, consumedLeaves;

  // Session confinement: every ref the provider returns must belong to the one
  // session `begin` created, identified by the authoritative id on the
  // runtime-owned session handle (NOT inferred from a returned ref) — so a
  // provider stamping every ref with the same foreign id is still caught.
  uint64_t expectedSession = 0;
  Error bindSession(uint64_t s, RecipeDiagnostic d, const Twine &where) const {
    if (s != expectedSession)
      return recipeError(d, where);
    return Error::success();
  }

  Interpreter(const RecipeModule &module, const TargetRecipeProvider &p,
              OpaqueBuildSession &s)
      : m(module), provider(p), session(s), expectedSession(s.sessionId) {
    for (int i = 0; i < (int)m.recipes.size(); ++i)
      recipeByName[m.recipes[i].recipeId] = i;
    for (int i = 0; i < (int)m.slots.size(); ++i)
      slotById[m.slots[i].id] = i;
    for (int i = 0; i < (int)m.fields.size(); ++i)
      fieldById[m.fields[i].id] = i;
    for (int i = 0; i < (int)m.hooks.size(); ++i)
      hookById[m.hooks[i].id] = i;
    for (const NodeCategoryRow &c : m.nodeCategories)
      categoryOf[c.node] = c.category;
    for (const NodeFieldRow &f : m.nodeFields)
      nodeFieldsOf[f.node].push_back({f.id, f.kind, f.typeId, f.card});
  }

  using Alias = DenseMap<unsigned, SlotIndex>; // callee SlotId -> resolved ref

  // Resolve a slot reference to a concrete (root slot, ordinal): follow a Call
  // alias, else find the active ForEach ordinal, else a top-level slot at 0.
  SlotIndex resolveSlotRef(SlotId s, ArrayRef<SlotIndex> ctx,
                           const Alias &alias) const {
    auto a = alias.find(s);
    if (a != alias.end())
      return a->second;
    for (const SlotIndex &c : ctx)
      if (c.slot == s)
        return c;
    return SlotIndex{s, 0};
  }

  // Validate a produced node count against a declared cardinality and that
  // every node belongs to the declared result CATEGORY (§3.3) — several
  // concrete node kinds may share a category.
  Error checkResult(ArrayRef<TargetNodeRef> nodes, const ResultCardinality &rc,
                    BackendNodeCategoryId category, const Twine &where) const {
    unsigned n = nodes.size();
    bool ok = rc.kind == Cardinality::One ? n == 1
              : rc.kind == Cardinality::Optional
                  ? n <= 1
                  : n >= rc.min && (rc.max == ResultCardinality::kUnbounded ||
                                    n <= rc.max);
    if (!ok)
      return recipeError(RecipeDiagnostic::ResultCardinality, where);
    for (const TargetNodeRef &r : nodes) {
      auto c = categoryOf.find(r.type);
      if (category && (c == categoryOf.end() || c->second != category))
        return recipeError(RecipeDiagnostic::ResultType, where);
    }
    return Error::success();
  }

  Error markNodeProduced(const TargetNodeRef &r) {
    if (!producedNodes.insert(keyOf(r)).second)
      return recipeError(RecipeDiagnostic::ResultConsumption,
                         "duplicate produced node");
    return Error::success();
  }
  Error markNodeConsumed(const TargetNodeRef &r) {
    if (!consumedNodes.insert(keyOf(r)).second)
      return recipeError(RecipeDiagnostic::ResultConsumption,
                         "node consumed more than once");
    return Error::success();
  }

  Expected<std::vector<TargetNodeRef>>
  evalBody(int bodyIdx, ArrayRef<SlotIndex> ctx, const Alias &alias) {
    std::vector<TargetNodeRef> result;
    const BodyRow &body = m.bodies[bodyIdx];
    for (int oi = body.opsBegin; oi < body.opsEnd; ++oi) {
      const OpRow &op = m.ops[oi];
      switch (op.kind) {
      case OpKind::Emit: {
        std::vector<GeneratedFieldBinding> binds;
        std::vector<std::vector<TargetNodeRef>> nested; // outlives emit
        if (Error e = buildBindings(op, ctx, alias, binds, nested))
          return std::move(e);
        // Hand the node's generated field descriptors to the adapter so it can
        // perform the mandated recheck before construction.
        ArrayRef<TargetFieldDescriptor> fds;
        auto nf = nodeFieldsOf.find(op.nodeTypeId);
        if (nf != nodeFieldsOf.end())
          fds = nf->second;
        auto ref = provider.emit(session, op.nodeTypeId, binds, fds);
        if (!ref)
          return ref.takeError();
        if (Error e = bindSession(ref->session, RecipeDiagnostic::Session,
                                  "emit foreign session"))
          return std::move(e);
        if (op.nodeTypeId && ref->type != op.nodeTypeId)
          return recipeError(RecipeDiagnostic::ResultType, "emit node type");
        if (Error e = markNodeProduced(*ref))
          return std::move(e);
        result.push_back(*ref);
        break;
      }
      case OpKind::ForEach: {
        // Read the extent EXACTLY ONCE, validate that value, and traverse it —
        // a provider cannot report one count to the check and another to the
        // walk.
        auto n = provider.slotExtent(session, op.slotId, ctx);
        if (!n)
          return n.takeError();
        if (Error e = validateExtent(op.slotId, *n, /*optional=*/false))
          return std::move(e);
        uint64_t prevOrder = 0;
        for (unsigned i = 0; i < *n; ++i) {
          auto ord = provider.slotItemOrder(session, op.slotId, ctx, i);
          if (!ord)
            return ord.takeError();
          if (i && *ord <= prevOrder)
            return recipeError(RecipeDiagnostic::Order, "slot order ordinals");
          prevOrder = *ord;
          std::vector<SlotIndex> c2(ctx.begin(), ctx.end());
          c2.push_back({op.slotId, i});
          auto sub = evalBody(op.body, c2, alias);
          if (!sub)
            return sub.takeError();
          result.insert(result.end(), sub->begin(), sub->end());
        }
        break;
      }
      case OpKind::OptionalOp: {
        auto n = provider.slotExtent(session, op.slotId, ctx);
        if (!n)
          return n.takeError();
        if (Error e = validateExtent(op.slotId, *n, /*optional=*/true))
          return std::move(e);
        if (*n == 1) {
          auto sub = evalBody(op.body, ctx, alias);
          if (!sub)
            return sub.takeError();
          result.insert(result.end(), sub->begin(), sub->end());
        }
        break;
      }
      case OpKind::Call: {
        auto it = recipeByName.find(op.recipeId);
        if (it == recipeByName.end())
          return recipeError(RecipeDiagnostic::ResolverZero,
                             "call to unknown recipe " + op.recipeId);
        const RecipeRow &callee = m.recipes[it->second];
        int nargs = op.bindingsEnd - op.bindingsBegin;
        int nslots = callee.slotsEnd - callee.slotsBegin;
        if (nargs != nslots)
          return recipeError(RecipeDiagnostic::CardinalityError,
                             "call argument count for " + op.recipeId);
        Alias callAlias;
        for (int k = 0; k < nargs; ++k) {
          const BindingRow &b = m.bindings[op.bindingsBegin + k];
          if (b.kind != BindKind::Direct)
            return recipeError(RecipeDiagnostic::OperationForbidden,
                               "call argument must be a direct slot binding");
          SlotId calleeSlot = m.slots[callee.slotsBegin + k].id;
          callAlias[calleeSlot] = resolveSlotRef(b.slotRef, ctx, alias);
        }
        auto sub = evalBody(callee.body, ctx, callAlias);
        if (!sub)
          return sub.takeError();
        if (Error e = checkResult(*sub, callee.result, callee.resultCategory,
                                  "callee result " + op.recipeId))
          return std::move(e);
        result.insert(result.end(), sub->begin(), sub->end());
        break;
      }
      }
    }
    return result;
  }

  // Build one Emit's validated field bindings into `binds`. `nested` is
  // caller-owned backing storage that outlives the `emit` call so the ArrayRefs
  // a Nested binding hands to `emit` stay valid; it is reserved up front so no
  // reallocation invalidates them.
  Error buildBindings(const OpRow &op, ArrayRef<SlotIndex> ctx,
                      const Alias &alias,
                      std::vector<GeneratedFieldBinding> &binds,
                      std::vector<std::vector<TargetNodeRef>> &nested) {
    nested.reserve(op.bindingsEnd - op.bindingsBegin);
    for (int bi = op.bindingsBegin; bi < op.bindingsEnd; ++bi) {
      const BindingRow &b = m.bindings[bi];
      if (b.kind == BindKind::Direct) {
        auto tv = projectField(b.fieldId, ctx, alias);
        if (!tv)
          return tv.takeError();
        GeneratedFieldBinding g;
        g.kind = GeneratedFieldBinding::Kind::Direct;
        g.targetField = b.targetField;
        g.directType = tv->type;
        g.directValue = tv->value;
        binds.push_back(g);
      } else if (b.kind == BindKind::Hook) {
        auto hit = hookById.find(b.hook);
        if (hit == hookById.end())
          return recipeError(RecipeDiagnostic::HookMissing, b.hookId);
        const HookRow &hook = m.hooks[hit->second];
        auto tv = projectField(b.fieldId, ctx, alias);
        if (!tv)
          return tv.takeError();
        if (tv->type != hook.inputType)
          return recipeError(RecipeDiagnostic::HookType,
                             "hook input " + b.hookId);
        auto leaf = provider.applyHook(session, hook.id, *tv);
        if (!leaf)
          return leaf.takeError();
        if (Error e = bindSession(leaf->session, RecipeDiagnostic::HookLifetime,
                                  b.hookId))
          return std::move(e);
        if (leaf->type != hook.outputType)
          return recipeError(RecipeDiagnostic::HookType,
                             "hook output " + b.hookId);
        if (!producedLeaves.insert(keyOf(*leaf)).second ||
            !consumedLeaves.insert(keyOf(*leaf)).second)
          return recipeError(RecipeDiagnostic::ResultConsumption,
                             "leaf reused " + b.hookId);
        GeneratedFieldBinding g;
        g.kind = GeneratedFieldBinding::Kind::Leaf;
        g.targetField = b.targetField;
        g.leaf = *leaf;
        binds.push_back(g);
      } else { // Nested
        auto sub = evalBody(b.nestedBody, ctx, alias);
        if (!sub)
          return sub.takeError();
        if (Error e = checkResult(*sub, b.nestedResult, b.nestedCategory,
                                  "nested binding " + b.field))
          return std::move(e);
        for (const TargetNodeRef &r : *sub)
          if (Error e = markNodeConsumed(r))
            return std::move(e);
        nested.push_back(std::move(*sub));
        GeneratedFieldBinding g;
        g.kind = GeneratedFieldBinding::Kind::Nodes;
        g.targetField = b.targetField;
        g.nodes = nested.back();
        binds.push_back(g);
      }
    }
    return Error::success();
  }

  // Project a typed accessor against its (alias-resolved) owner, checking the
  // returned value type against the accessor's generated type id.
  Expected<TypedHookInput> projectField(FinalizedFieldId fid,
                                        ArrayRef<SlotIndex> ctx,
                                        const Alias &alias) {
    auto it = fieldById.find(fid);
    if (it == fieldById.end())
      return recipeError(RecipeDiagnostic::InputUnbound, "unknown field id");
    const FieldRow &fr = m.fields[it->second];
    SlotIndex owner = resolveSlotRef(fr.slot, ctx, alias);
    auto tv = provider.project(session, fid, ctx, owner);
    if (!tv)
      return tv.takeError();
    if (fr.type && tv->type != fr.type)
      return recipeError(RecipeDiagnostic::InputType, fr.debugPath);
    return *tv;
  }

  // Validate an already-read slot extent against its declared cardinality (no
  // second provider call — the caller reads the extent exactly once).
  Error validateExtent(SlotId sid, unsigned n, bool optional) const {
    auto si = slotById.find(sid);
    if (si == slotById.end())
      return recipeError(RecipeDiagnostic::InputUnbound, "unknown slot id");
    const SlotRow &s = m.slots[si->second];
    bool ok = optional
                  ? n <= 1
                  : n >= s.min &&
                        (s.max == ResultCardinality::kUnbounded || n <= s.max);
    if (!ok)
      return recipeError(RecipeDiagnostic::CardinalityError, s.name);
    return Error::success();
  }
};

} // namespace

Expected<std::vector<TargetNodeRef>>
interpretRecipe(const RecipeModule &module, int recipeIndex,
                const TargetRecipeProvider &provider,
                OpaqueBuildSession &session) {
  if (recipeIndex < 0 || recipeIndex >= (int)module.recipes.size())
    return recipeError(RecipeDiagnostic::ResolverZero, "recipe index");
  const RecipeRow &recipe = module.recipes[recipeIndex];
  if (recipe.schemaVersion != kSupportedSchemaVersion)
    return recipeError(RecipeDiagnostic::Version, recipe.recipeId);

  Interpreter interp(module, provider, session);
  auto roots = interp.evalBody(recipe.body, {}, Interpreter::Alias{});
  if (!roots)
    return roots.takeError();

  if (Error e = interp.checkResult(*roots, recipe.result, recipe.resultCategory,
                                   "top-level result " + recipe.recipeId))
    return std::move(e);

  // Roots are consumed by `finish`; every other produced node must have been
  // consumed exactly once by a nested binding (§3.6 single-consumption).
  for (const TargetNodeRef &r : *roots)
    if (Error e = interp.markNodeConsumed(r))
      return std::move(e);
  if (interp.consumedNodes.size() != interp.producedNodes.size())
    return recipeError(RecipeDiagnostic::ResultConsumption,
                       "unconsumed target node");
  return roots;
}

} // namespace recipe
} // namespace neutrino
