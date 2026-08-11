//===- BackendProjectionDriver.h - generic finalized projection traversal
//--===//
//
// This is the single target-neutral seam between the verified
// BackendProjectionGraph and target idiom materializers. It derives the exact
// finalized idiom KEY from the verified sequence (the rail is a finalized fact,
// not a backend choice) and exposes read-only posting-fact visitors. Backends
// dispatch through the derived key; they do not implement a rail callback table
// or conditional traversal themselves.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDPROJECTIONDRIVER_H
#define NEUTRINO_BACKENDPROJECTIONDRIVER_H

#include "Neutrino/BackendProjection.h"
#include "Neutrino/RecipeRuntime.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <string>
#include <utility>

namespace neutrino::projection_driver {

inline llvm::Expected<recipe::FinalizedIdiomKey> finalizedProjectionIdiomKey(
    llvm::StringRef target,
    const projection::FinalizedProjectionSequence &sequence) {
  recipe::FinalizedIdiomKey key;
  key.target = target.str();
  key.role = "NotApplicable";
  switch (sequence.executionMode) {
  case projection::ExecutionMode::Evidence:
    key.finalizedKind = "QuorumAcceptance.Single";
    key.mode = "Evidence";
    return key;
  case projection::ExecutionMode::Temporal:
    key.finalizedKind = "QuorumAcceptance.PerPolicy";
    key.mode = "Temporal";
    return key;
  case projection::ExecutionMode::Effectful:
    key.mode = "Effectful";
    switch (sequence.attestationKind) {
    case projection::FinalizedAttestationKind::None:
      key.finalizedKind = "QuorumAcceptance.None";
      return key;
    case projection::FinalizedAttestationKind::Single:
      key.finalizedKind = "QuorumAcceptance.Single";
      return key;
    case projection::FinalizedAttestationKind::PerPolicy:
      break;
    }
    break;
  }
  return llvm::createStringError(
      std::errc::invalid_argument,
      "diag:FinalizedProjectionSequence:execution-mode");
}

template <typename WithoutMemo, typename WithMemo>
decltype(auto)
visitFinalizedPostingMemo(const projection::PostingValueProjection &posting,
                          WithoutMemo &&withoutMemo, WithMemo &&withMemo) {
  if (posting.memo.empty())
    return std::forward<WithoutMemo>(withoutMemo)();
  return std::forward<WithMemo>(withMemo)(posting.memo);
}

template <typename Unguarded, typename Comparison, typename Attested,
          typename Failure>
decltype(auto) visitFinalizedPostingGuard(
    const projection::FinalizedProjectionSequence &sequence,
    const projection::FinalizedPostingProjection &posting,
    Unguarded &&unguarded, Comparison &&comparison, Attested &&attested,
    Failure &&failure) {
  const projection::GroupGuardProjection &guard =
      sequence.effectGroups[posting.groupIndex].guard;
  if (!guard.present)
    return std::forward<Unguarded>(unguarded)();
  if (guard.guardKind == "comparison" && guard.comparisonGuard)
    return std::forward<Comparison>(comparison)(*guard.comparisonGuard);
  if (guard.guardKind == "attested")
    return std::forward<Attested>(attested)(guard);
  return std::forward<Failure>(failure)();
}

} // namespace neutrino::projection_driver

#endif // NEUTRINO_BACKENDPROJECTIONDRIVER_H
