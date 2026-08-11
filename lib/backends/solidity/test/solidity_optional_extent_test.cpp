//  item 3 witness: the GENERATED optional-slot extent resolver
// (solidityOptionalSlotExtent, emitted into solidity_recipes.inc) maps each
// closed presence ordinal to the correct 0/1 extent from an already-finalized
// posting — present/absent typed fields produce the correct extent. The
// provider dispatches to exactly this function; no handwritten presence read
// exists (its handwritten equivalent is rejected by check_semantic_authority's
// optional-slot-handwritten-presence probe).

#include "SolidityRecipeProvider.h"
#include "SolidityTargetValidation.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProjectionDriver.h"
#include "Neutrino/CodeText.h"
#include "Neutrino/Expr.h"
#include "Neutrino/GenSoliditySpec.h"
#include "Neutrino/RecipeModule.h"
#include "Neutrino/RecipeProviderRegistry.h"
#include "Neutrino/SolidityEmit.h"
#include "Neutrino/StrCase.h"
#include "Neutrino/ValueModel.h"

#include <iostream>
#include "SolidityPrinterHandlers.inc"
#include "SolidityRecipePackage.inc"

using neutrino::projection::FinalizedPostingGuardKind;
using neutrino::projection::FinalizedPostingProjection;
using neutrino::recipe::generated::solidityOptionalSlotExtent;

namespace {

// The finalized projection observes its parent group's immutable guard AST; a
// stack-owned node models that lifetime without introducing shared ownership
// merely to test presence.
FinalizedPostingProjection
comparisonPosting(const neutrino::ExprNode &comparisonGuard) {
  FinalizedPostingProjection p;
  p.guardKind = FinalizedPostingGuardKind::Comparison;
  p.comparisonGuard = &comparisonGuard;
  return p;
}

bool expect(const char *what, unsigned got, unsigned want) {
  if (got != want)
    std::cerr << "solidity-optional-extent: " << what << " got " << got
              << " want " << want << "\n";
  return got == want;
}

} // namespace

int main() {
  FinalizedPostingProjection withMemo;
  withMemo.memo = "m";
  FinalizedPostingProjection direct; // no memo, no comparison guard
  const neutrino::ExprNode comparisonGuard{};
  const FinalizedPostingProjection comparison =
      comparisonPosting(comparisonGuard);

  // PresenceMemo (1): present iff the posting carries a memo.
  bool ok = expect("memo-present", solidityOptionalSlotExtent(1, withMemo), 1);
  ok &= expect("memo-absent", solidityOptionalSlotExtent(1, direct), 0);
  // PresenceGuard (2): present iff the posting has a comparison guard.
  ok &= expect("guard-present", solidityOptionalSlotExtent(2, comparison), 1);
  ok &= expect("guard-absent", solidityOptionalSlotExtent(2, direct), 0);
  // PresenceDirect (3): present iff the posting has NO comparison guard.
  ok &= expect("direct-present", solidityOptionalSlotExtent(3, direct), 1);
  ok &= expect("direct-absent", solidityOptionalSlotExtent(3, comparison), 0);

  if (!ok)
    std::cerr << "Solidity optional-slot extent resolver witness failed\n";
  return ok ? 0 : 1;
}
