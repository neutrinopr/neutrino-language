//===- RecipeRuntime.cpp - stable diagnostics + fail-closed errors --------===//
//
// The generic, target-blind recipe runtime's diagnostic surface (boundary
// contract §3.7). Traversal/resolution over the generated recipe table is added
// on top of this foundation; every failure it can raise routes through
// `recipeError` so it carries one exact stable code and no partial output.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeRuntime.h"

#include "llvm/Support/ErrorHandling.h"

using namespace llvm;

namespace neutrino {
namespace recipe {

StringRef diagnosticCode(RecipeDiagnostic d) {
  switch (d) {
  case RecipeDiagnostic::Version:
    return "idiom.recipe.version";
  case RecipeDiagnostic::ResolverZero:
    return "idiom.recipe.resolver_zero";
  case RecipeDiagnostic::ResolverMultiple:
    return "idiom.recipe.resolver_multiple";
  case RecipeDiagnostic::TargetMismatch:
    return "idiom.recipe.target_mismatch";
  case RecipeDiagnostic::InputUnbound:
    return "idiom.recipe.input_unbound";
  case RecipeDiagnostic::InputType:
    return "idiom.recipe.input_type";
  case RecipeDiagnostic::CardinalityError:
    return "idiom.recipe.cardinality";
  case RecipeDiagnostic::ResultType:
    return "idiom.recipe.result_type";
  case RecipeDiagnostic::ResultCardinality:
    return "idiom.recipe.result_cardinality";
  case RecipeDiagnostic::ResultConsumption:
    return "idiom.recipe.result_consumption";
  case RecipeDiagnostic::Order:
    return "idiom.recipe.order";
  case RecipeDiagnostic::Cycle:
    return "idiom.recipe.cycle";
  case RecipeDiagnostic::Session:
    return "idiom.recipe.session";
  case RecipeDiagnostic::Finish:
    return "idiom.recipe.finish";
  case RecipeDiagnostic::HookMissing:
    return "idiom.recipe.hook_missing";
  case RecipeDiagnostic::HookType:
    return "idiom.recipe.hook_type";
  case RecipeDiagnostic::HookExecution:
    return "idiom.recipe.hook_execution";
  case RecipeDiagnostic::HookLifetime:
    return "idiom.recipe.hook_lifetime";
  case RecipeDiagnostic::OperationForbidden:
    return "idiom.recipe.operation_forbidden";
  case RecipeDiagnostic::Reachback:
    return "idiom.recipe.reachback";
  }
  llvm_unreachable("unhandled RecipeDiagnostic");
}

Error recipeError(RecipeDiagnostic d, const Twine &detail) {
  std::string msg = diagnosticCode(d).str();
  std::string tail = detail.str();
  if (!tail.empty())
    msg += ": " + tail;
  return make_error<StringError>(msg, inconvertibleErrorCode());
}

} // namespace recipe
} // namespace neutrino
