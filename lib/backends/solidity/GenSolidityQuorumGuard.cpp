//===- GenSolidityQuorumGuard.cpp - the M-of-N acceptance guard (S2c) -----===//
//
// Oracle S2c (): the on-chain M-of-N threshold-quorum acceptance guard,
// reproduced byte-identically from the security-reviewed reference () via
// the reference-first methodology (). The guard is deployment-independent —
// M, N, the observer addresses, and the capabilityHash are all constructor
// arguments resolved at deploy/binding — so `exact` canonicalization renders
// the reviewed bytes verbatim; an unsupported canonicalization fails closed
// rather than emit an unreviewed guard. See docs/backends/BACKEND_GENERATORS.md
// (Oracle S2c).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SolidityPackageArtifacts.h"
#ifndef NEUTRINO_SOLIDITY_PACKAGE_ONLY
#include "Neutrino/Attestation.h"
#endif
#include "Neutrino/Expr.h"

#include <string>

using namespace llvm;

namespace neutrino {

namespace {

// The single fail-closed funnel for the acceptance-guard render.
[[noreturn]] void failGuard(const char *code, const std::string &msg) {
  throw ExprError(code, msg);
}

// The reviewed guard source, embedded verbatim (see the .inc header). The
// golden diff pins these bytes to the reference; do not edit them here.
const char *const kThresholdQuorumGuardSol =
#include "ThresholdQuorumAcceptance.sol.inc"
    ;

// The reviewed  coordination-envelope library, embedded verbatim from the
// reference (examples/oracle-reference/coordination-envelope). A temporal
// per-policy coordination emits + imports it to recompute the execution claim
// on chain and bind it to the guard's acceptedExecutionClaim. The golden diff
// pins these bytes.
const char *const kCoordinationEnvelopeSol =
#include "CoordinationEnvelope.sol.inc"
    ;

} // namespace

std::string generateCoordinationEnvelope() { return kCoordinationEnvelopeSol; }

#ifndef NEUTRINO_SOLIDITY_PACKAGE_ONLY
std::string generateThresholdQuorumGuard(const AttestationPolicy &policy) {
  return generateThresholdQuorumGuardForCanonicalization(
      policy.canonicalization);
}
#endif

std::string generateThresholdQuorumGuardForCanonicalization(
    llvm::StringRef canonicalization) {
  if (canonicalization != "exact")
    failGuard("attest.canonicalization.unsupported",
              "attestation canonicalization '" + canonicalization.str() +
                  "' has no reviewed on-chain acceptance guard yet (only "
                  "'exact' is lowered; numeric 'median'/tolerance aggregation "
                  "is a deferred profile) — refusing to render an unreviewed "
                  "guard");
  return kThresholdQuorumGuardSol;
}

} // namespace neutrino
