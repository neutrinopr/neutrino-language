// Focused  Batch B provider/recipe witness.

#include "SolidityRecipeProvider.h"

#include "Neutrino/RecipeProviderRegistry.h"
#include "Neutrino/RecipeSessionStore.h"

#include "llvm/Support/Error.h"

#include <exception>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

using namespace neutrino;
using namespace neutrino::solidity_model;

namespace {

using AppendRecipe = void (*)(std::vector<SolStmt> &);

// ----  R3: backend-neutral takeField result-type vs consumption witness --
//
// `takeField` (the shared emit-side session store) must SPLIT the two §3.7
// failure cases so the distinction is a target-blind API contract, not
// accidental Solidity behavior: a LIVE slot whose carrier holds the wrong
// concrete kind (extract -> null) fails RESULT TYPE; a missing/already-consumed
// slot fails RESULT CONSUMPTION. This drives the helper directly with a minimal
// mock session + carrier (no Solidity type), covering BOTH cases.

// A minimal per-node carrier: `holds` names which concrete kind it stores; the
// Extract lambda yields the payload only when the kind matches (else nullptr,
// exactly as a real provider's variant does for the wrong member).
struct MockCarrier {
  int holds = 0;
  std::string payload;
};

// A minimal build session exposing only the member conventions the shared store
// addresses: `sessionId`, `finalizedValues`, `leafValues`, `nodes`.
struct MockSession {
  recipe::BuildSessionId sessionId = 0;
  std::vector<std::string> finalizedValues;
  std::vector<std::string> leafValues;
  std::vector<std::unique_ptr<MockCarrier>> nodes;
};

// True iff `error` carries exactly the stable code for diagnostic `d`.
bool errorHasCode(llvm::Error error, recipe::RecipeDiagnostic d) {
  std::string msg = llvm::toString(std::move(error));
  size_t sep = msg.find(':');
  std::string code = sep == std::string::npos ? msg : msg.substr(0, sep);
  return code == recipe::diagnosticCode(d).str();
}

// Build a session + module + one Nodes binding/field that PASSES
// recheckBindings (so control reaches the slot/extract branch): one child node
// of a category that matches the field's declared typeId. `liveSlot` picks the
// case — a live wrong-kind carrier (a) vs a missing/consumed slot (b).
bool takeFieldCase(bool liveSlot, recipe::RecipeDiagnostic expected) {
  constexpr recipe::BackendNodeTypeId kNodeType = 7;
  constexpr recipe::BackendNodeCategoryId kCategory = 3;
  constexpr recipe::TargetFieldId kFieldId = 5;
  constexpr int kWantKind = 1;
  constexpr int kWrongKind = 2;

  MockSession session;
  session.sessionId = 1;
  if (liveSlot) {
    auto carrier = std::make_unique<MockCarrier>();
    carrier->holds = kWrongKind; // NOT what the extract lambda wants
    carrier->payload = "x";
    session.nodes.push_back(std::move(carrier));
  } else {
    // Missing/already-consumed slot: the ordinal is still carried (so recheck's
    // in-range check passes) but the carrier is gone.
    session.nodes.push_back(nullptr);
  }

  std::vector<recipe::NodeCategoryRow> categories = {{kNodeType, kCategory}};
  recipe::RecipeModule module;
  module.nodeCategories = categories;

  std::vector<recipe::TargetNodeRef> children = {
      recipe::TargetNodeRef{session.sessionId, kNodeType, /*ordinal=*/0}};
  recipe::GeneratedFieldBinding binding;
  binding.kind = recipe::GeneratedFieldBinding::Kind::Nodes;
  binding.targetField = kFieldId;
  binding.nodes = children;
  std::vector<recipe::GeneratedFieldBinding> bindings = {binding};

  recipe::TargetFieldDescriptor field;
  field.id = kFieldId;
  field.kind = recipe::TargetFieldKind::Nodes;
  field.typeId = kCategory;
  field.card = {recipe::Cardinality::Many, /*min=*/1,
                recipe::ResultCardinality::kUnbounded};
  std::vector<recipe::TargetFieldDescriptor> fields = {field};

  auto extract = [](MockCarrier &c) -> std::string * {
    return c.holds == kWantKind ? &c.payload : nullptr;
  };

  auto result = recipe::takeField<std::string>(session, module, bindings,
                                               fields, /*fieldIndex=*/0, "mock",
                                               "widget", extract);
  if (result) // must fail closed
    return false;
  return errorHasCode(result.takeError(), expected);
}

// Both §3.7 cases, distinct: (a) live wrong-kind carrier -> RESULT TYPE;
// (b) missing/consumed slot -> RESULT CONSUMPTION.
bool takeFieldSplitsResultTypeVsConsumption() {
  return takeFieldCase(/*liveSlot=*/true,
                       recipe::RecipeDiagnostic::ResultType) &&
         takeFieldCase(/*liveSlot=*/false,
                       recipe::RecipeDiagnostic::ResultConsumption);
}

bool check(AppendRecipe append, const std::string &keyNoun) {
  std::vector<SolStmt> statements;
  append(statements);
  if (statements.size() != 5)
    return false;
  for (size_t i = 0; i != 4; ++i)
    if (statements[i].kind != SolStmt::Kind::DocComment)
      return false;
  if (statements[3].operand(0) !=
      keyNoun + " key, so it can never proceed on unattested evidence.")
    return false;
  const SolStmt &shell = statements[4];
  return shell.kind == SolStmt::Kind::InterfaceShell &&
         shell.operand(0) == "IThresholdQuorumAcceptance" &&
         shell.body.size() == 2 &&
         shell.body[0].kind == SolStmt::Kind::InterfaceSignature &&
         shell.body[0].operand(0) == "isAccepted" &&
         shell.body[1].kind == SolStmt::Kind::InterfaceSignature &&
         shell.body[1].operand(0) == "acceptedExecutionClaim";
}

} // namespace

int main() {
  const bool ok = check(appendEvidenceGuardConsumerRecipe, "instance") &&
                  check(appendTemporalGuardConsumerRecipe, "workflow") &&
                  takeFieldSplitsResultTypeVsConsumption() &&
                  recipe::RecipeProviderRegistry::get().has("solidity");
  if (!ok)
    std::cerr << "Solidity generated recipe provider witness failed\n";
  return ok ? 0 : 1;
}
