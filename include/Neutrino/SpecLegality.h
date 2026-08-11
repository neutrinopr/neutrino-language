#ifndef NEUTRINO_SPEC_LEGALITY_H
#define NEUTRINO_SPEC_LEGALITY_H

#include "Neutrino/Diagnostics.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <vector>

namespace neutrino {

// In-process spec-vs-target-profile legality gate (M5 WP4/, wired into the
// renderer path by WP6/). This is the C++ twin of
// scripts/gates/check_spec_legality.py: it matches the spec's
// `targetRequirements.requirements[].feature` against the target profile's
// `supportedFeatures` and FAILS CLOSED on any unsupported *required* feature —
// so neutrino-gen refuses to emit a deployable artifact for a capability the
// target profile cannot legally realize, BEFORE dispatch. Matching is over
// semantic FEATURES (value_category:* / effect:* / invariant:* / binding:* /
// topology:*), never domain labels.
//
// Both implementations must agree; a parity self-test drives the same
// spec+profile through the Python gate and neutrino-gen and asserts the same
// accept/reject (the legality.* codes are registered as DiagEmitter::Both for
// exactly this reason). Fails closed (legality.bad_input) on malformed pieces
// rather than crashing — shape validation is the validators' job.
//
// `expectedTarget` (if non-empty) adds the target sanity check: a solidity
// profile must not gate a postgres render (legality.target_mismatch). Returns
// diagnostics ordered root-cause first (earliest source line, then feature);
// any `error`-severity diagnostic means "illegal".
std::vector<Diagnostic> checkSpecLegality(const llvm::json::Object &spec,
                                          const llvm::json::Object &profile,
                                          llvm::StringRef expectedTarget = "");

// True when `diags` contains no error-severity diagnostic (advisories are
// allowed).
bool specIsLegal(const std::vector<Diagnostic> &diags);

} // namespace neutrino

#endif // NEUTRINO_SPEC_LEGALITY_H
