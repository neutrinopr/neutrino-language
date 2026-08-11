// SPDX-License-Identifier: Apache-2.0
//===- RecipeInterpreterTest.cpp - generic runtime end-to-end + failures --===//
//
// Drives the  generic runtime against a SYNTHETIC, test-only
// TargetRecipeProvider over an in-memory finalized view. The provider is a pure
// data source keyed ENTIRELY by generated ids (no name/path string, no
// const void*): it demonstrates the §3.5 typed seam. All proofs live in the
// generic runtime, so the malformed cases mutate a single provider method and
// assert the RUNTIME (not the provider) produces the stable §3.7 diagnostic.
// The happy path goes through the atomic executeRecipe lifecycle and checks the
// buffered render is byte-exact and that a failing render commits nothing.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"
#include "Neutrino/RecipeProviderRegistry.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include "gtest/gtest.h"

#include <memory>
#include <string>
#include <vector>

// The build-generated module + typed-id constants: generated::synthetic*.
#include "synthetic_recipes.inc"

using namespace neutrino::recipe;
using namespace neutrino::recipe::generated;
using llvm::Error;
using llvm::Expected;
using llvm::StringRef;

namespace {

// The immutable finalized snapshot — a typed view base, never a void*.
struct SynthView : TaggedRecipeOpaque<SynthView, FinalizedInputView> {
  std::vector<std::string> groups;
};

struct SynthNode {
  BackendNodeTypeId type = 0;
  std::string text;               // arm: escaped label
  std::vector<uint64_t> children; // block: child node ordinals
};

struct SynthSession : OpaqueBuildSession {
  BuildSessionId id = 0;
  std::vector<std::string> groups;
  std::vector<std::string> leaves;
  std::vector<SynthNode> nodes;
};

struct SynthArtifact : TaggedRecipeOpaque<SynthArtifact, OpaqueTargetArtifact> {
  std::vector<SynthNode> nodes;
  std::vector<uint64_t> roots;
};

struct StringSink : OutputSink {
  std::string data;
  void write(StringRef bytes) override { data += bytes.str(); }
};

// The synthetic provider: trusts nothing about recipes, decides nothing, reads
// its snapshot only by generated id.
class SynthProvider : public TargetRecipeProvider {
public:
  StringRef target() const override { return "synthetic"; }

  Expected<RecipeHandle> resolve(const FinalizedIdiomKey &key) const override {
    auto idx = resolveRecipe(syntheticRecipeModule(), key);
    if (!idx)
      return idx.takeError();
    return (RecipeHandle)*idx;
  }

  Expected<std::unique_ptr<OpaqueBuildSession>>
  begin(const FinalizedInvocation &inv) const override {
    const auto *view = checkedRecipeOpaque<SynthView>(inv.finalizedView);
    if (view == nullptr)
      return recipeError(RecipeDiagnostic::InputUnbound,
                         "synthetic finalized recipe view");
    auto s = std::make_unique<SynthSession>();
    s->id = ++counter;
    s->sessionId = s->id; // authoritative id on the runtime-owned handle
    s->groups = view->groups;
    return s;
  }

  Expected<OpaqueLeafValueRef> applyHook(OpaqueBuildSession &session,
                                         RegisteredHookId hook,
                                         TypedHookInput input) const override {
    auto &s = static_cast<SynthSession &>(session);
    uint64_t ord = s.leaves.size();
    s.leaves.push_back("[" + s.groups[input.value] + "]"); // synthetic escape
    return leafRef(s, hook, ord);
  }

  Expected<TargetNodeRef>
  emit(OpaqueBuildSession &session, BackendNodeTypeId node,
       llvm::ArrayRef<GeneratedFieldBinding> bindings,
       llvm::ArrayRef<TargetFieldDescriptor> fields) const override {
    auto &s = static_cast<SynthSession &>(session);
    // §3.6 adapter recheck: the binding set must match the field schema before
    // any concrete node is constructed.
    if (Error e = recheck(s, bindings, fields))
      return std::move(e);
    SynthNode n;
    n.type = node;
    if (node == synthetic_Node_SynthArm) {
      n.text = s.leaves[bindings[0].leaf.ordinal];
    } else { // SynthBlock
      for (const TargetNodeRef &ch : bindings[0].nodes)
        n.children.push_back(ch.ordinal);
    }
    uint64_t ord = s.nodes.size();
    s.nodes.push_back(std::move(n));
    return nodeRef(s, node, ord);
  }

  // The mandated adapter recheck: field id, kind, type, and a Nodes field's
  // child category + cardinality, all from the generated descriptors.
  Error recheck(SynthSession &s, llvm::ArrayRef<GeneratedFieldBinding> bindings,
                llvm::ArrayRef<TargetFieldDescriptor> fields) const {
    if (bindings.size() != fields.size())
      return recipeError(RecipeDiagnostic::ResultCardinality, "field count");
    for (size_t i = 0; i < fields.size(); ++i) {
      const GeneratedFieldBinding &b = bindings[i];
      const TargetFieldDescriptor &f = fields[i];
      if (b.targetField != f.id)
        return recipeError(RecipeDiagnostic::ResultType, "field id");
      if (f.kind == TargetFieldKind::Value) {
        if (b.kind != GeneratedFieldBinding::Kind::Direct ||
            b.directType != f.typeId)
          return recipeError(RecipeDiagnostic::InputType, "value field");
      } else if (f.kind == TargetFieldKind::Leaf) {
        if (b.kind != GeneratedFieldBinding::Kind::Leaf ||
            b.leaf.type != f.typeId)
          return recipeError(RecipeDiagnostic::HookType, "leaf field");
      } else { // Nodes: child category + cardinality
        if (b.kind != GeneratedFieldBinding::Kind::Nodes)
          return recipeError(RecipeDiagnostic::ResultType, "nodes field");
        unsigned nch = b.nodes.size();
        bool okc =
            nch >= f.card.min &&
            (f.card.max == ResultCardinality::kUnbounded || nch <= f.card.max);
        if (!okc)
          return recipeError(RecipeDiagnostic::CardinalityError, "child count");
        for (const TargetNodeRef &ch : b.nodes)
          if (categoryOfNode(ch.type) != f.typeId)
            return recipeError(RecipeDiagnostic::ResultType, "child category");
      }
    }
    return Error::success();
  }

  static BackendNodeCategoryId categoryOfNode(BackendNodeTypeId t) {
    if (t == synthetic_Node_SynthArm)
      return synthetic_Cat_ArmCat;
    if (t == synthetic_Node_SynthBlock)
      return synthetic_Cat_StmtCat;
    return 0;
  }

  Expected<std::unique_ptr<OpaqueTargetArtifact>>
  finish(std::unique_ptr<OpaqueBuildSession> session,
         llvm::ArrayRef<TargetNodeRef> roots) const override {
    auto &s = static_cast<SynthSession &>(*session);
    auto a = std::make_unique<SynthArtifact>();
    a->nodes = std::move(s.nodes);
    for (const TargetNodeRef &r : roots)
      a->roots.push_back(r.ordinal);
    return a;
  }

  Error render(const OpaqueTargetArtifact &artifact,
               OutputSink &sink) const override {
    const auto &a = static_cast<const SynthArtifact &>(artifact);
    std::string out;
    for (uint64_t r : a.roots)
      out += renderNode(a, r);
    sink.write(out);
    return Error::success();
  }

  Expected<unsigned> slotExtent(OpaqueBuildSession &session, SlotId slot,
                                llvm::ArrayRef<SlotIndex>) const override {
    auto &s = static_cast<SynthSession &>(session);
    if (slot == synthetic_Slot_groups)
      return (unsigned)s.groups.size();
    return recipeError(RecipeDiagnostic::InputUnbound, "slot");
  }

  Expected<uint64_t> slotItemOrder(OpaqueBuildSession &, SlotId,
                                   llvm::ArrayRef<SlotIndex>,
                                   unsigned index) const override {
    return (uint64_t)index; // projection-owned order == declared index here
  }

  Expected<TypedHookInput> project(OpaqueBuildSession &session,
                                   FinalizedFieldId field,
                                   llvm::ArrayRef<SlotIndex>, SlotIndex owner) const override {
    auto &s = static_cast<SynthSession &>(session);
    if (owner.index >= s.groups.size())
      return recipeError(RecipeDiagnostic::InputUnbound, "owner index");
    if (field == synthetic_Field_group_label)
      return TypedHookInput{synthetic_Value_TargetIdentifierAtom, owner.index};
    if (field == synthetic_Field_groups_item)
      return TypedHookInput{synthetic_Value_FinalizedSyntheticGroup,
                            owner.index};
    return recipeError(RecipeDiagnostic::InputUnbound, "field");
  }

protected:
  // Overridable ref factories so a mutation subclass can inject a fault.
  virtual OpaqueLeafValueRef leafRef(SynthSession &s, RegisteredHookId,
                                     uint64_t ord) const {
    return {s.id, synthetic_Leaf_EscapedIdentifier, ord};
  }
  virtual TargetNodeRef nodeRef(SynthSession &s, BackendNodeTypeId node,
                                uint64_t ord) const {
    return {s.id, node, ord};
  }

private:
  mutable uint64_t counter = 0;

  std::string renderNode(const SynthArtifact &a, uint64_t ord) const {
    const SynthNode &n = a.nodes[ord];
    if (n.type == synthetic_Node_SynthArm)
      return "arm" + n.text;
    std::string out = "block{";
    for (size_t i = 0; i < n.children.size(); ++i) {
      if (i)
        out += ",";
      out += renderNode(a, n.children[i]);
    }
    return out + "}";
  }
};

const RecipeModule &synth() { return syntheticRecipeModule(); }
const FinalizedIdiomKey kBlockKey{"synthetic", "SyntheticBlock",
                                  "NotApplicable", "NotApplicable"};

FinalizedInvocation invoke(const SynthView &v) {
  FinalizedInvocation inv;
  inv.key = kBlockKey;
  inv.finalizedView = &v;
  return inv;
}

// Open a live session directly (for provider-boundary unit checks).
std::unique_ptr<OpaqueBuildSession> open(const SynthProvider &p,
                                         const SynthView &v) {
  auto s = p.begin(invoke(v));
  EXPECT_TRUE(static_cast<bool>(s));
  return std::move(*s);
}

std::string codeOf(Error e) { return llvm::toString(std::move(e)); }

// ---- end-to-end via the atomic lifecycle -----------------------------------
TEST(RecipeInterpreter, EndToEndRendersByteExact) {
  SynthProvider p;
  SynthView v;
  v.groups = {"alpha", "beta", "gamma"};
  StringSink sink;
  ASSERT_FALSE(static_cast<bool>(executeRecipe(synth(), p, invoke(v), sink)));
  EXPECT_EQ(sink.data, "block{arm[alpha],arm[beta],arm[gamma]}");
}

TEST(RecipeInterpreter, SingleGroupRenders) {
  SynthProvider p;
  SynthView v;
  v.groups = {"only"};
  StringSink sink;
  ASSERT_FALSE(static_cast<bool>(executeRecipe(synth(), p, invoke(v), sink)));
  EXPECT_EQ(sink.data, "block{arm[only]}");
}

// ---- P1.3: a failing render commits no bytes -------------------------------
TEST(RecipeInterpreter, RenderFailureDiscardsBufferedOutput) {
  struct FailingRender : SynthProvider {
    Error render(const OpaqueTargetArtifact &,
                 OutputSink &sink) const override {
      sink.write("PARTIAL");
      return recipeError(RecipeDiagnostic::Finish, "render blew up");
    }
  } p;
  SynthView v;
  v.groups = {"x"};
  StringSink sink;
  auto e = executeRecipe(synth(), p, invoke(v), sink);
  ASSERT_TRUE(static_cast<bool>(e));
  llvm::consumeError(std::move(e));
  EXPECT_EQ(sink.data, ""); // nothing observable
}

// ---- P1(b): the resolved recipe handle reaches begin -----------------------
TEST(RecipeInterpreter, BeginReceivesResolvedHandle) {
  struct P : SynthProvider {
    mutable RecipeHandle seen = 0xffffffff;
    Expected<std::unique_ptr<OpaqueBuildSession>>
    begin(const FinalizedInvocation &inv) const override {
      seen = inv.recipe;
      return SynthProvider::begin(inv);
    }
  } p;
  SynthView v;
  v.groups = {"x"};
  StringSink sink;
  ASSERT_FALSE(static_cast<bool>(executeRecipe(synth(), p, invoke(v), sink)));
  // The block key resolves to recipe index 1; begin must have seen it.
  auto blk = resolveRecipe(synth(), kBlockKey);
  ASSERT_TRUE(static_cast<bool>(blk));
  EXPECT_EQ(p.seen, (RecipeHandle)*blk);
}

// ---- P1.3: target/version gate ---------------------------------------------
TEST(RecipeInterpreter, TargetMismatchFailsClosed) {
  struct WrongTarget : SynthProvider {
    StringRef target() const override { return "other"; }
  } p;
  SynthView v;
  v.groups = {"x"};
  StringSink sink;
  auto e = executeRecipe(synth(), p, invoke(v), sink);
  ASSERT_TRUE(static_cast<bool>(e));
  EXPECT_EQ(codeOf(std::move(e)).rfind("idiom.recipe.target_mismatch", 0), 0u);
}

// ---- P1.2: runtime-enforced proofs (each mutates ONE provider method) -------
template <class Prov> std::string runFail(std::vector<std::string> groups) {
  Prov p;
  SynthView v;
  v.groups = std::move(groups);
  StringSink sink;
  auto e = executeRecipe(synth(), p, invoke(v), sink);
  EXPECT_TRUE(static_cast<bool>(e));
  EXPECT_EQ(sink.data, "");
  return e ? llvm::toString(std::move(e)) : std::string();
}

TEST(RecipeInterpreter, SlotExtentBelowMinFailsCardinality) {
  struct P : SynthProvider {
    Expected<unsigned> slotExtent(OpaqueBuildSession &, SlotId,
                                  llvm::ArrayRef<SlotIndex>) const override {
      return 0u; // violates groups' declared many(1,unbounded)
    }
  };
  EXPECT_EQ(runFail<P>({"a"}).rfind("idiom.recipe.cardinality", 0), 0u);
}

TEST(RecipeInterpreter, NonMonotonicOrderFails) {
  struct P : SynthProvider {
    Expected<uint64_t> slotItemOrder(OpaqueBuildSession &, SlotId,
                                     llvm::ArrayRef<SlotIndex>,
                                     unsigned) const override {
      return 0u; // never increases
    }
  };
  EXPECT_EQ(runFail<P>({"a", "b", "c"}).rfind("idiom.recipe.order", 0), 0u);
}

TEST(RecipeInterpreter, WrongProjectedTypeFailsInputType) {
  struct P : SynthProvider {
    Expected<TypedHookInput> project(OpaqueBuildSession &, FinalizedFieldId,
                                     llvm::ArrayRef<SlotIndex>, SlotIndex owner) const override {
      return TypedHookInput{/*type=*/999, owner.index};
    }
  };
  EXPECT_EQ(runFail<P>({"a"}).rfind("idiom.recipe.input_type", 0), 0u);
}

TEST(RecipeInterpreter, WrongHookOutputFailsHookType) {
  struct P : SynthProvider {
    OpaqueLeafValueRef leafRef(SynthSession &s, RegisteredHookId,
                               uint64_t ord) const override {
      return {s.id, /*type=*/999, ord}; // not EscapedIdentifier
    }
  };
  EXPECT_EQ(runFail<P>({"a"}).rfind("idiom.recipe.hook_type", 0), 0u);
}

TEST(RecipeInterpreter, ForeignSessionRefFailsSession) {
  struct P : SynthProvider {
    TargetNodeRef nodeRef(SynthSession &, BackendNodeTypeId node,
                          uint64_t ord) const override {
      return {/*session=*/99999, node, ord}; // not the hook's session
    }
  };
  EXPECT_EQ(runFail<P>({"a"}).rfind("idiom.recipe.session", 0), 0u);
}

TEST(RecipeInterpreter, DuplicateNodeRefFailsConsumption) {
  struct P : SynthProvider {
    TargetNodeRef nodeRef(SynthSession &s, BackendNodeTypeId node,
                          uint64_t) const override {
      return {s.id, node, /*ordinal=*/0}; // every node aliases ordinal 0
    }
  };
  EXPECT_EQ(runFail<P>({"a", "b"}).rfind("idiom.recipe.result_consumption", 0),
            0u);
}

// ---- P1(2): the adapter rechecks the field contract before construction -----
// A corrupted binding (right count, wrong leaf type) must be rejected by emit's
// recheck, never reaching node construction.
TEST(RecipeInterpreter, AdapterRechecksFieldContract) {
  SynthProvider p;
  SynthView v;
  v.groups = {"x"};
  auto session = open(p, v);

  // The SynthArm schema: one leaf field "label" (target-field id 1) of
  // EscapedIdentifier (from the generated node_fields table).
  TargetFieldDescriptor label{/*id=*/1,
                              TargetFieldKind::Leaf,
                              synthetic_Leaf_EscapedIdentifier,
                              {Cardinality::One, 1, 1}};
  GeneratedFieldBinding bad;
  bad.kind = GeneratedFieldBinding::Kind::Leaf;
  bad.targetField = 1;
  bad.leaf = {session->sessionId, /*type=*/999,
              /*ordinal=*/0}; // wrong leaf type
  auto r = p.emit(*session, synthetic_Node_SynthArm, {bad}, {label});
  ASSERT_FALSE(static_cast<bool>(r));
  EXPECT_EQ(codeOf(r.takeError()).rfind("idiom.recipe.hook_type", 0), 0u);

  // A wrong target-field id is also rejected.
  GeneratedFieldBinding wrongId;
  wrongId.kind = GeneratedFieldBinding::Kind::Leaf;
  wrongId.targetField = 7; // no such field
  wrongId.leaf = {session->sessionId, synthetic_Leaf_EscapedIdentifier, 0};
  auto r2 = p.emit(*session, synthetic_Node_SynthArm, {wrongId}, {label});
  ASSERT_FALSE(static_cast<bool>(r2));
  EXPECT_EQ(codeOf(r2.takeError()).rfind("idiom.recipe.result_type", 0), 0u);
}

// ---- §8 package discovery ---------------------------------------------------
TEST(RecipeInterpreter, PackageDiscoveryRegistersAndResolvesByTarget) {
  auto &reg = RecipeProviderRegistry::get();
  reg.unregisterForTesting("synthetic");

  auto e0 = reg.create("synthetic").takeError();
  EXPECT_EQ(codeOf(std::move(e0)).rfind("idiom.recipe.resolver_zero", 0), 0u);

  ASSERT_FALSE(static_cast<bool>(reg.registerProvider(
      "synthetic", [] { return std::make_unique<SynthProvider>(); })));
  EXPECT_TRUE(reg.has("synthetic"));

  auto prov = reg.create("synthetic");
  ASSERT_TRUE(static_cast<bool>(prov));
  EXPECT_EQ((*prov)->target(), "synthetic");

  auto dup = reg.registerProvider(
      "synthetic", [] { return std::make_unique<SynthProvider>(); });
  ASSERT_TRUE(static_cast<bool>(dup));
  EXPECT_EQ(codeOf(std::move(dup)).rfind("idiom.recipe.operation_forbidden", 0),
            0u);

  reg.unregisterForTesting("synthetic");
}

} // namespace
