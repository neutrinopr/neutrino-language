//===- SolidityRecipeProvider.cpp - generated-recipe Solidity adapter -----===//
//
// The single provider/bootstrap owned by .  It maps generated opaque node
// IDs to the existing typed Solidity model.  Recipe traversal, exact-key
// resolution, nesting, ordering, and cardinality remain in NeutrinoRecipe.
//
//===----------------------------------------------------------------------===//

#include "SolidityRecipeProvider.h"
#include "SolidityTargetValidation.h"

#include "Neutrino/BackendProjectionDriver.h"
#include "Neutrino/CodeText.h"
#include "Neutrino/Expr.h"
#include "Neutrino/RecipeModule.h"
#include "Neutrino/RecipeProviderRegistry.h"
#include "Neutrino/RecipeSessionStore.h"
#include "Neutrino/SolidityEmit.h"
#include "Neutrino/StrCase.h"
#include "Neutrino/ValueModel.h"

#include "llvm/ADT/SmallSet.h"
#include "llvm/Support/Error.h"

#include <algorithm>
#include <atomic>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "SolidityPrinterHandlers.inc"
#include "SolidityRecipePackage.inc"

using namespace llvm;
using namespace neutrino::recipe;
using namespace neutrino::recipe::generated;

//  R5b A.2: the generated finalized-view dispatch resolver that retires the
// handwritten project()/slotExtent()/slotItemOrder() cascades. Included AFTER
// solidity_recipes.inc (the symbolic constants + SlotRow/findSlot/
// solidityOptionalSlotExtent it consumes) and the recipe/adapter using-
// directives; the three provider overrides forward into it.
#include "SolidityProjection.inc"

namespace neutrino {
namespace solidity_model {
using namespace sol_detail;

namespace {

struct SolidityRecipeView final
    : TaggedRecipeOpaque<SolidityRecipeView, FinalizedInputView> {
  const projection::FinalizedProjectionSequence *sequence = nullptr;
  std::vector<projection::FinalizedTemporalPolicyProjection> temporalPolicies;
};

// One produced node in the emit-order session store — exactly one carrier is
// populated (mirrors PostgreSQL's PgRecipeNode). Internal storage only: the
// nodes, their order, and their render are unchanged from the prior parallel
// vectors.
struct SolRecipeNode {
  std::unique_ptr<SolStmt> stmt;
  std::optional<SolParam> param;
  std::optional<std::string> fragment;
  std::optional<SolidityContract> contract;
};

struct SolidityRecipeSession final : OpaqueBuildSession {
  const projection::FinalizedProjectionSequence *sequence = nullptr;
  std::vector<std::unique_ptr<SolRecipeNode>> nodes;
  std::vector<std::string> finalizedValues;
  // : an expression leaf travels WITH the category of the position it was
  // projected for (value vs predicate), so the hook lowers it through the right
  // emitter instead of guessing from the node shape.
  std::vector<CategorizedExpr> finalizedExpressions;
  std::vector<std::string> leafValues;
};

struct SolidityRecipeArtifact final
    : TaggedRecipeOpaque<SolidityRecipeArtifact, OpaqueTargetArtifact> {
  std::vector<SolStmt> roots;
  std::optional<SolidityContract> temporalContract;
};

// : the recursive node renderer is the shared `toNode`
// (SolidityTargetAdapter), which now also performs the generic trailing-comment
// alignment — so the provider render path and the contract projection render
// through ONE renderer, with no duplicate. (The former provider-local
// `renderNode` is retired.)

class SolidityRecipeProvider final : public TargetRecipeProvider {
public:
  using Node = SolStmt;
  using Callable = CallableKind;
  using Modifier = CallableModifier;
  using Param = SolParam;
  using Contract = SolidityContract;
  using SourceRequirement = SoliditySourceRequirement;
  using Sequence = projection::FinalizedProjectionSequence;

  StringRef target() const override { return "solidity"; }

  Expected<RecipeHandle> resolve(const FinalizedIdiomKey &key) const override {
    auto recipe = resolveRecipe(solidityRecipeModule(), key);
    if (!recipe)
      return recipe.takeError();
    return static_cast<RecipeHandle>(*recipe);
  }

  Expected<std::unique_ptr<OpaqueBuildSession>>
  begin(const FinalizedInvocation &invocation) const override {
    const auto *view =
        checkedRecipeOpaque<SolidityRecipeView>(invocation.finalizedView);
    if (view == nullptr)
      return recipeError(RecipeDiagnostic::InputUnbound,
                         "Solidity finalized recipe view");
    auto session = std::make_unique<SolidityRecipeSession>();
    session->sessionId = ++nextSession;
    session->sequence = view->sequence;
    return std::unique_ptr<OpaqueBuildSession>(std::move(session));
  }

  Expected<OpaqueLeafValueRef> applyHook(OpaqueBuildSession &opaque,
                                         RegisteredHookId hook,
                                         TypedHookInput input) const override {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    if (input.value >= session.finalizedValues.size())
      return recipeError(RecipeDiagnostic::HookExecution,
                         "Solidity hook input");
    const StringRef value = session.finalizedValues[input.value];
    std::string formatted;
    BackendLeafTypeId output = 0;
    if (hook == solidity_Hook_solidity_identifier_escape) {
      formatted = value.str();
      output = solidity_Leaf_EscapedIdentifier;
    } else if (hook == solidity_Hook_solidity_string_escape) {
      formatted = solString(value);
      output = solidity_Leaf_EscapedStringLiteral;
    } else if (hook == solidity_Hook_solidity_type_spell) {
      formatted = solType(value);
      if (formatted == "string")
        formatted += " calldata";
      output = solidity_Leaf_TargetTypeToken;
    } else if (hook == solidity_Hook_solidity_operand_format) {
      const auto category = value.split('\t');
      if (category.first == "claim") {
        const auto claim = category.second.split('\t');
        const std::string reference = uref(claim.second);
        formatted = solType(claim.first) == "uint256"
                        ? "CoordinationEnvelope.u2s(" + reference + ")"
                        : reference;
      } else {
        const auto operand = category.second.split(':');
        const bool literal = operand.first == "literal";
        if (category.first == "uint") {
          if (literal && !isInt(operand.second))
            return recipeError(RecipeDiagnostic::HookExecution,
                               "Solidity numeric operand");
          formatted = literal ? operand.second.str() : uref(operand.second);
        } else if (category.first == "string") {
          formatted =
              literal ? solString(operand.second) : uref(operand.second);
        } else {
          return recipeError(RecipeDiagnostic::HookExecution,
                             "Solidity operand category");
        }
      }
      output = solidity_Leaf_TargetOperand;
    } else if (hook == solidity_Hook_solidity_expression_leaf) {
      if (input.value >= session.finalizedExpressions.size() ||
          session.finalizedExpressions[input.value].node == nullptr)
        return recipeError(RecipeDiagnostic::HookExecution,
                           "Solidity expression input");
      // : the PROJECTED category selects the emitter — a value expression
      // lowers through toSolidity, a guard condition through guardToSolidity.
      // Both emitters keep their own typed refusal: a comparison in a Value
      // position still fails `expr.type` ("a comparison predicate is not a
      // value expression"), and a non-comparison in a Predicate position still
      // fails in guardToSolidity. Nothing here inspects the node's shape.
      const CategorizedExpr &projected =
          session.finalizedExpressions[input.value];
      const Resolver resolve = [](StringRef name) { return "u_" + name.str(); };
      switch (projected.category) {
      case ExprCategory::Value:
        formatted = toSolidity(*projected.node, resolve);
        break;
      case ExprCategory::Predicate:
        formatted = guardToSolidity(*projected.node, resolve);
        break;
      }
      output = solidity_Leaf_TargetExpression;
    } else {
      return recipeError(RecipeDiagnostic::HookMissing,
                         "Solidity generated hook id");
    }
    const LeafOrdinal ordinal = session.leafValues.size();
    session.leafValues.push_back(std::move(formatted));
    return OpaqueLeafValueRef{session.sessionId, output, ordinal};
  }

  Expected<TargetNodeRef>
  emit(OpaqueBuildSession &opaque, BackendNodeTypeId node,
       ArrayRef<GeneratedFieldBinding> bindings,
       ArrayRef<TargetFieldDescriptor> fields) const override {
    return solidityBuildNode(*this, opaque, node, bindings, fields);
  }

  // Thin forwarders to the shared session store: recheck the bindings, then
  // record one produced node (variant carrier) at the next emit ordinal. The
  // method NAMES are the contract the frozen generated builders call.
  Expected<TargetNodeRef>
  storeGenerated(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                 ArrayRef<GeneratedFieldBinding> bindings,
                 ArrayRef<TargetFieldDescriptor> fields,
                 SolStmt statement) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    if (Error error = recheckBindings(session, solidityRecipeModule(), bindings,
                                      fields, "Solidity"))
      return std::move(error);
    return storeNode(
        session, node,
        SolRecipeNode{std::make_unique<SolStmt>(std::move(statement)),
                      std::nullopt, std::nullopt, std::nullopt});
  }

  Expected<TargetNodeRef>
  storeGeneratedParam(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                      ArrayRef<GeneratedFieldBinding> bindings,
                      ArrayRef<TargetFieldDescriptor> fields,
                      SolParam param) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    if (Error error = recheckBindings(session, solidityRecipeModule(), bindings,
                                      fields, "Solidity"))
      return std::move(error);
    return storeNode(
        session, node,
        SolRecipeNode{nullptr, std::move(param), std::nullopt, std::nullopt});
  }

  Expected<TargetNodeRef>
  storeGeneratedFragment(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                         ArrayRef<GeneratedFieldBinding> bindings,
                         ArrayRef<TargetFieldDescriptor> fields,
                         std::string fragment) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    if (Error error = recheckBindings(session, solidityRecipeModule(), bindings,
                                      fields, "Solidity"))
      return std::move(error);
    return storeNode(session, node,
                     SolRecipeNode{nullptr, std::nullopt, std::move(fragment),
                                   std::nullopt});
  }

  Expected<TargetNodeRef> storeGeneratedTemporalContract(
      OpaqueBuildSession &opaque, BackendNodeTypeId node,
      ArrayRef<GeneratedFieldBinding> bindings,
      ArrayRef<TargetFieldDescriptor> fields, SolidityContract contract) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    if (Error error = recheckBindings(session, solidityRecipeModule(), bindings,
                                      fields, "Solidity"))
      return std::move(error);
    return storeNode(session, node,
                     SolRecipeNode{nullptr, std::nullopt, std::nullopt,
                                   std::move(contract)});
  }

  [[noreturn]] static void fail(const std::string &message) {
    specFail(message);
  }

  static std::string targetPascalIdentifier(StringRef value) {
    return pascalCase(value);
  }
  static std::string targetReference(StringRef value) { return uref(value); }

  static std::string
  closedSpelling(StringRef ordinal,
                 std::initializer_list<StringRef> spellings) {
    unsigned index = 0;
    if (ordinal.getAsInteger(10, index) || index >= spellings.size())
      fail("invalid closed Solidity spelling ordinal");
    return (spellings.begin() + index)->str();
  }

  static std::string joinParts(std::initializer_list<std::string> parts,
                               StringRef separator) {
    std::string result;
    for (const std::string &part : parts) {
      if (part.empty())
        continue;
      if (!result.empty())
        result += separator.str();
      result += part;
    }
    return result;
  }

  static std::string joinFragments(ArrayRef<std::string> fragments,
                                   StringRef separator) {
    std::string result;
    for (size_t i = 0; i < fragments.size(); ++i) {
      if (i)
        result += separator.str();
      result += fragments[i];
    }
    return result;
  }

  // Thin forwarders: the rendered-operand read and the three single-consumption
  // takes delegate to the shared store, threading the concrete carrier
  // accessor.
  Expected<std::vector<std::string>>
  readValueOperands(OpaqueBuildSession &opaque,
                    ArrayRef<GeneratedFieldBinding> bindings,
                    ArrayRef<TargetFieldDescriptor> fields) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    return readValues(session, solidityRecipeModule(), bindings, fields,
                      "Solidity");
  }

  Expected<std::vector<SolParam>> takeGeneratedParams(
      OpaqueBuildSession &opaque, ArrayRef<GeneratedFieldBinding> bindings,
      ArrayRef<TargetFieldDescriptor> fields, size_t fieldIndex) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    return takeField<SolParam>(session, solidityRecipeModule(), bindings,
                               fields, fieldIndex, "Solidity", "parameter",
                               [](SolRecipeNode &node) -> SolParam * {
                                 return node.param ? &*node.param : nullptr;
                               });
  }

  Expected<std::vector<SolStmt>> takeGeneratedStatements(
      OpaqueBuildSession &opaque, ArrayRef<GeneratedFieldBinding> bindings,
      ArrayRef<TargetFieldDescriptor> fields, size_t fieldIndex) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    return takeField<SolStmt>(
        session, solidityRecipeModule(), bindings, fields, fieldIndex,
        "Solidity", "statement",
        [](SolRecipeNode &node) -> SolStmt * { return node.stmt.get(); });
  }

  Expected<std::vector<std::string>> takeGeneratedFragments(
      OpaqueBuildSession &opaque, ArrayRef<GeneratedFieldBinding> bindings,
      ArrayRef<TargetFieldDescriptor> fields, size_t fieldIndex) const {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    return takeField<std::string>(
        session, solidityRecipeModule(), bindings, fields, fieldIndex,
        "Solidity", "fragment", [](SolRecipeNode &node) -> std::string * {
          return node.fragment ? &*node.fragment : nullptr;
        });
  }

  Expected<std::vector<SolStmt>>
  takeGeneratedNodes(OpaqueBuildSession &opaque,
                     ArrayRef<GeneratedFieldBinding> bindings,
                     ArrayRef<TargetFieldDescriptor> fields) const {
    return takeGeneratedStatements(opaque, bindings, fields, 0);
  }

  Expected<std::unique_ptr<OpaqueTargetArtifact>>
  finish(std::unique_ptr<OpaqueBuildSession> opaque,
         ArrayRef<TargetNodeRef> roots) const override {
    auto session = std::unique_ptr<SolidityRecipeSession>(
        static_cast<SolidityRecipeSession *>(opaque.release()));
    auto artifact = std::make_unique<SolidityRecipeArtifact>();
    artifact->roots.reserve(roots.size());
    // Finish-time root consumption + unconsumed scan live in the shared store;
    // the leaf `consume` here selects the typed carrier (a statement root vs
    // the single temporal-contract root) — the only Solidity-specific step.
    if (Error error = consumeRoots(
            *session, roots, "Solidity", [&](SolRecipeNode &node) -> Error {
              if (node.stmt) {
                artifact->roots.push_back(std::move(*node.stmt));
                return Error::success();
              }
              if (node.contract) {
                if (artifact->temporalContract)
                  return recipeError(RecipeDiagnostic::ResultCardinality,
                                     "multiple temporal contract roots");
                artifact->temporalContract.emplace(std::move(*node.contract));
                return Error::success();
              }
              return recipeError(RecipeDiagnostic::ResultConsumption,
                                 "Solidity root node has no generated value");
            }))
      return std::move(error);
    return std::unique_ptr<OpaqueTargetArtifact>(std::move(artifact));
  }

  Error render(const OpaqueTargetArtifact &opaque,
               OutputSink &sink) const override {
    const auto &artifact = static_cast<const SolidityRecipeArtifact &>(opaque);
    if (artifact.temporalContract)
      return recipeError(RecipeDiagnostic::OperationForbidden,
                         "temporal contract requires typed consumption");
    codetext::Document document;
    for (const SolStmt &root : artifact.roots)
      document.add(toNode(root));
    sink.write(document.print("    "));
    return Error::success();
  }

  //  R5b A.2: the finalized-view trio is retired to the generated dispatch
  // resolver (generated/SolidityProjection.inc). Each override is a thin typed
  // forwarder — it recovers the session's finalized sequence and delegates to
  // the generated accessor vocabulary. No handwritten cascade, slot/field
  // branch, or semantic read lives here; the resolver's only leaf-hook is
  // solidityStatusAtom (the  (mode,role) -> atom accessor).
  Expected<unsigned> slotExtent(OpaqueBuildSession &opaque, SlotId slot,
                                ArrayRef<SlotIndex> ctx) const override {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    if (session.sequence == nullptr)
      return recipeError(RecipeDiagnostic::InputUnbound,
                         "temporal finalized sequence");
    return generated_projection::soliditySlotExtentResolve(*session.sequence,
                                                           slot, ctx);
  }

  Expected<uint64_t> slotItemOrder(OpaqueBuildSession &opaque, SlotId slot,
                                   ArrayRef<SlotIndex> ctx,
                                   unsigned index) const override {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    return generated_projection::soliditySlotItemOrderResolve(*session.sequence,
                                                              slot, ctx, index);
  }

  Expected<TypedHookInput> project(OpaqueBuildSession &opaque,
                                   FinalizedFieldId field,
                                   ArrayRef<SlotIndex> ctx,
                                   SlotIndex owner) const override {
    auto &session = static_cast<SolidityRecipeSession &>(opaque);
    return generated_projection::solidityProjectField(
        session.finalizedValues, session.finalizedExpressions,
        *session.sequence, field, ctx, owner);
  }

private:
  static std::atomic<BuildSessionId> nextSession;
};

std::atomic<BuildSessionId> SolidityRecipeProvider::nextSession{0};

Error ensureProviderRegistered() {
  static const std::string registrationError = [] {
    Error error = RecipeProviderRegistry::get().registerProvider(
        "solidity", [] { return std::make_unique<SolidityRecipeProvider>(); });
    return error ? toString(std::move(error)) : std::string();
  }();
  if (!registrationError.empty())
    return recipeError(RecipeDiagnostic::OperationForbidden, registrationError);
  return Error::success();
}

Expected<std::unique_ptr<SolidityRecipeArtifact>>
materializeArtifact(const FinalizedIdiomKey &key,
                    const SolidityRecipeView &view) {
  const RecipeModule &module = solidityRecipeModule();
  if (Error error = ensureProviderRegistered())
    return std::move(error);
  auto provider = RecipeProviderRegistry::get().create("solidity");
  if (!provider)
    return provider.takeError();
  FinalizedInvocation invocation;
  invocation.key = key;
  invocation.finalizedView = &view;
  auto artifact = materializeRecipe(module, **provider, invocation);
  if (!artifact)
    return artifact.takeError();
  auto *solidityArtifact =
      checkedRecipeOpaque<SolidityRecipeArtifact>(artifact->get());
  if (solidityArtifact == nullptr)
    return recipeError(RecipeDiagnostic::Finish,
                       "Solidity provider returned a foreign artifact");
  artifact->release();
  return std::unique_ptr<SolidityRecipeArtifact>(solidityArtifact);
}

struct ProjectedRecipeArtifact {
  std::unique_ptr<SolidityRecipeArtifact> artifact;
};

Expected<ProjectedRecipeArtifact> materializeProjectionRoot(
    const projection::BackendProjectionGraph &projection) {
  auto sequence = projection::consumeFinalizedProjectionSequence(projection);
  if (!sequence)
    return sequence.takeError();
  auto key =
      projection_driver::finalizedProjectionIdiomKey("solidity", *sequence);
  if (!key)
    return key.takeError();
  SolidityRecipeView view;
  view.sequence = &*sequence;
  view.temporalPolicies = sequence->temporalPolicies;
  auto artifact = materializeArtifact(*key, view);
  if (!artifact)
    return artifact.takeError();
  return ProjectedRecipeArtifact{std::move(*artifact)};
}

Expected<std::vector<SolStmt>> materialize(const FinalizedIdiomKey &key,
                                           const SolidityRecipeView &view) {
  auto artifact = materializeArtifact(key, view);
  if (!artifact)
    return artifact.takeError();
  if ((*artifact)->temporalContract)
    return recipeError(RecipeDiagnostic::ResultType,
                       "Solidity statement recipe returned a typed contract");
  return std::move((*artifact)->roots);
}

void appendSolidityRecipe(std::vector<SolStmt> &output,
                          const FinalizedIdiomKey &key) {
  SolidityRecipeView view;
  auto statements = materialize(key, view);
  if (!statements)
    specFail(toString(statements.takeError()));
  for (SolStmt &statement : *statements)
    output.push_back(std::move(statement));
}

} // namespace

SolidityProjectionArtifact materializeSolidityProjectionArtifact(
    const projection::BackendProjectionGraph &projection) {
  auto projected = materializeProjectionRoot(projection);
  if (!projected)
    specFail(toString(projected.takeError()));
  if (!projected->artifact->temporalContract ||
      !projected->artifact->roots.empty())
    specFail("Solidity root recipe returned an invalid contract artifact");

  SolidityProjectionArtifact result{
      std::move(*projected->artifact->temporalContract), {}, {}};
  result.contractSource = renderSolidityProjection(result.contractModel);
  result.namedSources.push_back(
      {result.contractModel.targetSourceName, result.contractSource});
  for (const SoliditySourceDependency &dependency :
       result.contractModel.sourceDependencies) {
    if (dependency.kind ==
        SoliditySourceRequirement::ThresholdQuorumAcceptance) {
      if (dependency.canonicalizations.empty())
        specFail("Solidity quorum dependency has no canonicalization payload");
      std::optional<std::string> guard;
      for (const std::string &canonicalization : dependency.canonicalizations) {
        std::string rendered =
            generateThresholdQuorumGuardForCanonicalization(canonicalization);
        if (guard && *guard != rendered)
          specFail("Solidity quorum dependency payloads render different "
                   "source artifacts");
        guard = std::move(rendered);
      }
      result.namedSources.push_back(
          {"src/ThresholdQuorumAcceptance.sol", std::move(*guard)});
      continue;
    }
    if (dependency.kind == SoliditySourceRequirement::CoordinationEnvelope) {
      if (!dependency.canonicalizations.empty())
        specFail("Solidity coordination-envelope dependency carried an "
                 "unexpected canonicalization payload");
      result.namedSources.push_back(
          {"src/CoordinationEnvelope.sol", generateCoordinationEnvelope()});
      continue;
    }
    specFail("Solidity root recipe returned an unknown source requirement");
  }
  return result;
}

std::vector<SoliditySourceFile> materializeSoliditySources(
    const projection::BackendProjectionGraph &projection) {
  return materializeSolidityProjectionArtifact(projection).namedSources;
}

void appendEvidenceGuardConsumerRecipe(std::vector<SolStmt> &output) {
  appendSolidityRecipe(
      output, {"solidity", "GuardConsumer", "Evidence", "NotApplicable"});
}

void appendTemporalGuardConsumerRecipe(std::vector<SolStmt> &output) {
  appendSolidityRecipe(
      output, {"solidity", "GuardConsumer", "Temporal", "NotApplicable"});
}

SolidityContract materializeTemporalContractRecipe(
    const projection::FinalizedProjectionSequence &sequence) {
  SolidityRecipeView view;
  view.sequence = &sequence;
  view.temporalPolicies = sequence.temporalPolicies;
  auto artifact = materializeArtifact(
      {"solidity", "QuorumAcceptance.PerPolicy", "Temporal", "NotApplicable"},
      view);
  if (!artifact)
    specFail(toString(artifact.takeError()));
  if (!(*artifact)->temporalContract || !(*artifact)->roots.empty())
    specFail("temporal recipe returned an invalid contract result");
  return std::move(*(*artifact)->temporalContract);
}

SolidityContract materializeEffectfulWithAttestationContractRecipe(
    const projection::FinalizedProjectionSequence &sequence) {
  SolidityRecipeView view;
  view.sequence = &sequence;
  auto artifact = materializeArtifact(
      {"solidity", "QuorumAcceptance.Single", "Effectful", "NotApplicable"},
      view);
  if (!artifact)
    specFail(toString(artifact.takeError()));
  if (!(*artifact)->temporalContract || !(*artifact)->roots.empty())
    specFail("effectful attested recipe returned an invalid contract result");
  return std::move(*(*artifact)->temporalContract);
}

SolidityContract materializeEffectfulWithoutAttestationContractRecipe(
    const projection::FinalizedProjectionSequence &sequence) {
  SolidityRecipeView view;
  view.sequence = &sequence;
  auto artifact = materializeArtifact(
      {"solidity", "QuorumAcceptance.None", "Effectful", "NotApplicable"},
      view);
  if (!artifact)
    specFail(toString(artifact.takeError()));
  if (!(*artifact)->temporalContract || !(*artifact)->roots.empty())
    specFail("effectful unattested recipe returned an invalid contract result");
  return std::move(*(*artifact)->temporalContract);
}

SolidityContract materializeEvidenceContractRecipe(
    const projection::FinalizedProjectionSequence &sequence) {
  SolidityRecipeView view;
  view.sequence = &sequence;
  auto artifact = materializeArtifact(
      {"solidity", "QuorumAcceptance.Single", "Evidence", "NotApplicable"},
      view);
  if (!artifact)
    specFail(toString(artifact.takeError()));
  if (!(*artifact)->temporalContract || !(*artifact)->roots.empty())
    specFail("evidence recipe returned an invalid contract result");
  return std::move(*(*artifact)->temporalContract);
}

} // namespace solidity_model
} // namespace neutrino
