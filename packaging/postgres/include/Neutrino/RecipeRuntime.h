//===- RecipeRuntime.h - generic target-blind backend-idiom recipe runtime ===//
//
// The domain-blind, target-blind runtime contract for the  declarative
// backend-idiom recipe boundary (). This header is the ONLY surface the
// generic recipe library exposes to backend packages; it names no backend enum,
// leaf class, target-node class, or renderer header. Backend packages implement
// `TargetRecipeProvider` and hand the runtime type-erased opaque IDs.
//
// Nothing here reads source/domain/spec/MLIR or makes a semantic decision: the
// runtime resolves the exact finalized key, validates recipe structure, walks
// the generated recipe, and dispatches ordered operations through the provider
// ABI. All semantics are already finalized upstream in the projection.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_RECIPERUNTIME_H
#define NEUTRINO_RECIPERUNTIME_H

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstdint>
#include <memory>
#include <string>

namespace neutrino {
namespace recipe {

// ---- §3.1 the exact resolution key -----------------------------------------
//
// Resolution is by the exact tuple (target, finalizedKind, mode, role). Every
// component is a closed value; `mode`/`role` may be the closed literal
// "NotApplicable". There is no wildcard, priority, partial match, default, or
// catch-all. A backend package fixes `target` and indexes the remaining triple.
struct FinalizedIdiomKey {
  std::string target;
  std::string finalizedKind;
  std::string mode; // closed mode or "NotApplicable"
  std::string role; // closed role or "NotApplicable"

  bool operator==(const FinalizedIdiomKey &o) const {
    return target == o.target && finalizedKind == o.finalizedKind &&
           mode == o.mode && role == o.role;
  }
};

// ---- §3.3 closed result cardinality ----------------------------------------
enum class Cardinality { One, Optional, Many };
struct ResultCardinality {
  Cardinality kind = Cardinality::One;
  unsigned min = 1;
  // `max == kUnbounded` encodes the closed value "unbounded".
  unsigned max = 1;
  static constexpr unsigned kUnbounded = 0xffffffffu;
};

// ---- §3.6 generated opaque IDs ---------------------------------------------
//
// These are generated, stable, opaque identifiers. They carry NO backend type
// information across the generic boundary; the provider maps them internally.
// `SlotId` and `FinalizedFieldId` are the generator-assigned handles that
// replace every runtime name/field-path string (§3.5 forbids stringly named
// runtime field lookup): the runtime addresses slots and typed input-view
// accessors only by these IDs.
using RecipeHandle = uint32_t;
using RegisteredHookId = uint32_t;
using FinalizedValueTypeId = uint32_t;
using BackendLeafTypeId = uint32_t;
using BackendNodeTypeId = uint32_t;     // one concrete target-node kind
using BackendNodeCategoryId = uint32_t; // a §3.3 result category (many kinds)
using SlotId = uint32_t;                // generated; 0 = none
using FinalizedFieldId = uint32_t; // generated typed input-view accessor id
using TargetFieldId = uint32_t;    // generated target-node field id
using BuildSessionId = uint64_t;
using FinalizedValueOrdinal = uint64_t;
using LeafOrdinal = uint64_t;
using NodeOrdinal = uint64_t;

// ---- §3.6 type-erased value/ref carriers -----------------------------------
//
// A hook input: exactly one generated typed value, indexed into the session's
// immutable input snapshot.
struct TypedHookInput {
  FinalizedValueTypeId type = 0;
  FinalizedValueOrdinal value = 0;
};

// A backend-owned leaf value produced by exactly one hook. Immutable,
// non-owning, valid only in the session that created it, consumed exactly once.
struct OpaqueLeafValueRef {
  BuildSessionId session = 0;
  BackendLeafTypeId type = 0;
  LeafOrdinal ordinal = 0;
};

// A backend-owned target node produced by exactly one `emit`. Non-owning, valid
// only while its session is alive; never crosses providers or sessions.
struct TargetNodeRef {
  BuildSessionId session = 0;
  BackendNodeTypeId type = 0;
  NodeOrdinal ordinal = 0;
};

// A validated field binding the runtime hands to `emit`: exactly one of a
// direct finalized value, a produced leaf reference, or an ordered node-ref
// sequence.
// The generated descriptor for one target-node field, handed to the builder
// adapter alongside each `emit` so it can perform the mandated §3.6 recheck
// (kind/type/cardinality) before constructing the concrete node. `typeId` is a
// value type (`Value`), leaf type (`Leaf`), or child result CATEGORY (`Nodes`).
enum class TargetFieldKind { Value, Leaf, Nodes };
struct TargetFieldDescriptor {
  TargetFieldId id = 0;
  TargetFieldKind kind = TargetFieldKind::Value;
  uint32_t typeId = 0;
  ResultCardinality card; // Nodes: child-count bounds
};

struct GeneratedFieldBinding {
  enum class Kind { Direct, Leaf, Nodes } kind = Kind::Direct;
  // The generated target-node field this binding fills; the builder adapter
  // rechecks kind/type/cardinality against its field schema (§3.6).
  TargetFieldId targetField = 0;
  // Direct: an index into the session's immutable finalized-value snapshot.
  FinalizedValueTypeId directType = 0;
  FinalizedValueOrdinal directValue = 0;
  // Leaf: the already-produced hook output.
  OpaqueLeafValueRef leaf;
  // Nodes: the ordered result of a nested body (consumed whole, once).
  llvm::ArrayRef<TargetNodeRef> nodes;
};

// Opaque, backend-owned session, finished artifact, and finalized input view:
// polymorphic bases the generic runtime holds only by `unique_ptr`/pointer. The
// provider derives its concrete type and downcasts internally; no concrete type
// or field ever crosses the generic boundary, and the generic runtime NEVER
// reinterprets one as raw memory. `FinalizedInputView` replaces the former
// `const void *`: the caller hands the provider a typed view base, and the
// provider snapshots the generated typed input accessors in `begin`.
struct OpaqueBuildSession {
  virtual ~OpaqueBuildSession() = default;
  // The authoritative session identity, set by `begin`. It is part of the
  // runtime-owned handle: the runtime compares EVERY returned leaf/node ref
  // against this exact id for session confinement (§3.6 rules 2-3), so a
  // provider cannot legitimize a foreign ref by stamping it uniformly.
  BuildSessionId sessionId = 0;
};
struct OpaqueTargetArtifact {
  virtual ~OpaqueTargetArtifact() = default;
  virtual const void *recipeTypeTag() const = 0;
};
struct FinalizedInputView {
  virtual ~FinalizedInputView() = default;
  virtual const void *recipeTypeTag() const = 0;
};

// Target-neutral checked discriminator for provider-owned opaque values. The
// tag is one process-stable address per concrete C++ type; it avoids RTTI and
// makes a checked static cast possible without exposing backend identities to
// the generic runtime.
template <typename Derived, typename Base> struct TaggedRecipeOpaque : Base {
  static const void *classRecipeTypeTag() {
    static const char Tag = 0;
    return &Tag;
  }
  const void *recipeTypeTag() const final { return classRecipeTypeTag(); }
};

template <typename Derived, typename Base>
const Derived *checkedRecipeOpaque(const Base *value) {
  if (value == nullptr ||
      value->recipeTypeTag() != Derived::classRecipeTypeTag())
    return nullptr;
  return static_cast<const Derived *>(value);
}

template <typename Derived, typename Base>
Derived *checkedRecipeOpaque(Base *value) {
  if (value == nullptr ||
      value->recipeTypeTag() != Derived::classRecipeTypeTag())
    return nullptr;
  return static_cast<Derived *>(value);
}

// The finalized invocation the runtime hands to `begin`: the resolved key plus
// a typed opaque handle to the finalized projection view the provider
// snapshots.
struct FinalizedInvocation {
  FinalizedIdiomKey key;
  RecipeHandle recipe = 0;
  const FinalizedInputView *finalizedView = nullptr; // typed; provider-owned
};

// A sink the finished artifact renders bytes into (the first byte-exposing op).
class OutputSink {
public:
  virtual ~OutputSink() = default;
  virtual void write(llvm::StringRef bytes) = 0;
};

// ---- finalized-view query seam ---------------------------------------------
//
// The generic runtime owns `ForEach`/`Optional` expansion and `Direct`/`Hook`
// field projection (§3.6), so it asks the provider's immutable finalized
// snapshot structural questions — WITHOUT ever seeing a backend value and
// WITHOUT any name/path string. A `SlotIndex` names one active item by its
// generated `SlotId` and ordinal; the ordered stack is the projection context.
struct SlotIndex {
  SlotId slot = 0;
  unsigned index = 0;
};

// ---- §3.6 the provider ABI -------------------------------------------------
//
// Each backend package exports one provider. The generic runtime performs ALL
// recipe traversal and invokes the provider's generated exact-key resolver; the
// provider only resolves keys, owns the build session, executes registered pure
// hooks (`applyHook`), constructs concrete nodes (`emit`), and renders. The
// provider MUST NOT interpret recipes, branch on finalized values, or invoke
// other recipes. See RecipeRuntime.cpp / the boundary doc §3.6 for the
// normative ownership + failure rules.
class TargetRecipeProvider {
public:
  virtual ~TargetRecipeProvider() = default;

  // The governed target this provider owns (matches every recipe's `target`).
  virtual llvm::StringRef target() const = 0;

  // Resolve the exact key to exactly one recipe, or fail closed
  // (zero/multiple).
  virtual llvm::Expected<RecipeHandle>
  resolve(const FinalizedIdiomKey &key) const = 0;

  // Open one backend-owned build session, snapshotting the invocation's typed
  // input views; returns unique ownership to the runtime.
  virtual llvm::Expected<std::unique_ptr<OpaqueBuildSession>>
  begin(const FinalizedInvocation &invocation) const = 0;

  // Execute exactly one registered pure leaf hook by exact ID on one typed
  // input; store + return one session-confined opaque leaf reference.
  virtual llvm::Expected<OpaqueLeafValueRef>
  applyHook(OpaqueBuildSession &session, RegisteredHookId hook,
            TypedHookInput input) const = 0;

  // Construct exactly one registered typed target node. The adapter MUST
  // recheck the binding set against `fields` (each binding's target-field id,
  // kind, type, and a Nodes field's child category/cardinality) BEFORE
  // construction (§3.6) and fail closed on any mismatch — a corrupted binding
  // never reaches a concrete node. On success it records the node and returns a
  // non-owning ref.
  virtual llvm::Expected<TargetNodeRef>
  emit(OpaqueBuildSession &session, BackendNodeTypeId node,
       llvm::ArrayRef<GeneratedFieldBinding> bindings,
       llvm::ArrayRef<TargetFieldDescriptor> fields) const = 0;

  // Consume the session exactly once, validate the complete root result, and
  // return a backend-owned opaque artifact.
  virtual llvm::Expected<std::unique_ptr<OpaqueTargetArtifact>>
  finish(std::unique_ptr<OpaqueBuildSession> session,
         llvm::ArrayRef<TargetNodeRef> roots) const = 0;

  // Render a finished artifact (the first operation allowed to expose bytes).
  virtual llvm::Error render(const OpaqueTargetArtifact &artifact,
                             OutputSink &sink) const = 0;

  // ---- finalized-view queries (runtime-owned traversal support) ----
  //
  // All three address the finalized snapshot by generated ID only — never a
  // name or field-path string (§3.5). The runtime validates every result
  // against the generated proofs; the provider only reads its typed snapshot.

  // The number of finalized items bound to `slot` in the given projection
  // context: `one` -> 1, `optional` -> 0 or 1, `many` -> n. Presence and count
  // are already finalized; the runtime never invents them and validates the
  // count against the slot's declared cardinality.
  virtual llvm::Expected<unsigned>
  slotExtent(OpaqueBuildSession &session, SlotId slot,
             llvm::ArrayRef<SlotIndex> ctx) const = 0;

  // The projection-owned semantic order ordinal of item `index` in a `many`
  // slot (§3.2). The runtime iterates in declared index order and validates the
  // returned ordinals are strictly increasing — it never invents or resorts.
  virtual llvm::Expected<uint64_t> slotItemOrder(OpaqueBuildSession &session,
                                                 SlotId slot,
                                                 llvm::ArrayRef<SlotIndex> ctx,
                                                 unsigned index) const = 0;

  // Project a generated typed input-view accessor (`FinalizedFieldId`) against
  // the exact finalized value named by `owner` (its slot + ordinal, already
  // alias-resolved by the runtime). Used for `Direct` and as the input to a
  // `Hook`. The runtime checks the returned `type` against the accessor's
  // generated `FinalizedValueTypeId`.
  virtual llvm::Expected<TypedHookInput> project(OpaqueBuildSession &session,
                                                 FinalizedFieldId field,
                                                 llvm::ArrayRef<SlotIndex> ctx,
                                                 SlotIndex owner) const = 0;
};

// ---- §3.7 stable diagnostics -----------------------------------------------
//
// Every recipe failure carries one of these stable codes and occurs BEFORE any
// partial target output is observable. `diagnosticCode` maps the enum to its
// exact stable string; the runtime never fabricates or reuses a code.
enum class RecipeDiagnostic {
  Version,            // idiom.recipe.version
  ResolverZero,       // idiom.recipe.resolver_zero
  ResolverMultiple,   // idiom.recipe.resolver_multiple
  TargetMismatch,     // idiom.recipe.target_mismatch
  InputUnbound,       // idiom.recipe.input_unbound
  InputType,          // idiom.recipe.input_type
  CardinalityError,   // idiom.recipe.cardinality
  ResultType,         // idiom.recipe.result_type
  ResultCardinality,  // idiom.recipe.result_cardinality
  ResultConsumption,  // idiom.recipe.result_consumption
  Order,              // idiom.recipe.order
  Cycle,              // idiom.recipe.cycle
  Session,            // idiom.recipe.session
  Finish,             // idiom.recipe.finish
  HookMissing,        // idiom.recipe.hook_missing
  HookType,           // idiom.recipe.hook_type
  HookExecution,      // idiom.recipe.hook_execution
  HookLifetime,       // idiom.recipe.hook_lifetime
  OperationForbidden, // idiom.recipe.operation_forbidden
  Reachback,          // idiom.recipe.reachback
};

// The exact stable string for a diagnostic (e.g. "idiom.recipe.resolver_zero").
llvm::StringRef diagnosticCode(RecipeDiagnostic d);

// Build a fail-closed `llvm::Error` carrying the stable code + a detail; used
// by the runtime and by providers so every failure surfaces the same identity.
llvm::Error recipeError(RecipeDiagnostic d, const llvm::Twine &detail = "");

} // namespace recipe
} // namespace neutrino

#endif // NEUTRINO_RECIPERUNTIME_H
