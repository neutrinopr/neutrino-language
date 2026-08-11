#ifndef NEUTRINO_ATTESTATION_H
#define NEUTRINO_ATTESTATION_H

// The attestation-policy CONTRACT leaf (M5 oracle S1, ): the spec-declared
// oracle-consensus policy carried by an `evidence` input, plus its spec-JSON
// (de)serialization and fail-closed validation. View.h-free and MLIR-free, so
// it belongs in NeutrinoSpecContract — everything downstream in  (the
// on-chain acceptance guard, the serverless observers, the security spec)
// renders FROM this one frozen contract.
//
// The policy converts a non-deterministic real-world observation into a
// predicate Neutrino can render and verify: not "is X true?" but "did an M-of-N
// quorum sign the canonical form of X?". Only the threshold M and the observer
// set REFERENCE are portable spec; the concrete N and the observer members are
// resolved at binding ( slice 5), so the spec stays deployment-independent.
#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// The attestation policy on one `evidence` input. Additive: an evidence input
// without a declared policy carries none (the spec omits the section entirely,
// keeping existing specs byte-identical).
struct AttestationPolicy {
  std::string input; // the evidence input this policy governs
  int quorum =
      0; // M — the acceptance threshold (spec); concrete N is binding-level
  std::string observerSet;  // observer-set identity/role REFERENCE (members are
                            // binding-level)
  std::string observerRole; // optional role the observer set must hold ("" =
                            // unconstrained)
  // Trust-surfacing metadata on the observer set (oracle S6, ) — DECLARED,
  // not derived; surfaced/flagged by the security spec, not enforced here. Both
  // optional ("" = undeclared, surfaced as an advisory).
  std::string assurance; // claimed assurance tier of the observer set:
                         // "A1".."A4" (attestationAssuranceTiers is the source)
  std::string independence; // observer-set independence posture:
                            // "independent" | "correlated"
  std::string
      canonicalization;  // what counts as "the same claim": "exact" | "median"
  std::string tolerance; // optional agreement band for numeric feeds ("" = none
                         // / exact)
  std::string timeout;   // optional deadline for reaching quorum ("" = none)
  std::string fallback;  // behavior when quorum is not reached: "abort" |
                         // "escalate"
};

// The supported canonicalization modes, in canonical order — the single source
// of the accepted set (validation + any metadata render FROM here). `exact` for
// discrete events (byte-equal claim); `median` for numeric feeds (agreement
// within `tolerance`).
llvm::ArrayRef<llvm::StringRef> attestationCanonicalizationModes();

// The supported quorum-timeout fallbacks, in canonical order. Fail-closed by
// design (): the coordination stalls rather than firing on partial
// attestation. `abort` ends the coordination; `escalate` hands off to a
// declared escalation path. (`degrade` is deferred until it names its reduced
// target — /S1 review.)
llvm::ArrayRef<llvm::StringRef> attestationFallbacks();

// The supported observer-set assurance tiers, in ascending order (oracle S6,
// ). Mirrors the Trust lane's A1-A4 vocabulary: A1 compiler attestation,
// A2 realization, A3 runtime evidence, A4 proof. The single source for the
// accepted set (validation + the security surfacing read FROM here).
llvm::ArrayRef<llvm::StringRef> attestationAssuranceTiers();

// The supported observer-set independence postures, in canonical order (oracle
// S6, ). `independent` = diverse sources/operators; `correlated` = shared
// upstream (an M-of-N over correlated observers is a single point of failure
// wearing N hats — surfaced as an advisory, ).
llvm::ArrayRef<llvm::StringRef> attestationIndependenceModes();

// Fail-closed validation of a single policy. Returns "" when valid, else a
// human-readable reason. The rejected shapes the contract guarantees (/
// acceptance): non-positive quorum, missing observer-set reference,
// missing/unsupported canonicalization mode, unsupported fallback, and — when
// declared — an unsupported assurance tier or independence posture.
std::string validateAttestationPolicy(const AttestationPolicy &p);

// Serialize one policy to its frozen capability-spec JSON shape.
llvm::json::Value attestationPolicyJson(const AttestationPolicy &p);

// Reconstruct the policies from a frozen capability spec's `attestations` array
// (mirrors lifecycleModelFromSpec, Lifecycle.h) — so a spec-JSON renderer
// (the oracle backend, the acceptance guard, the security spec) projects the
// policy without a ProcedureView. Returns an empty vector when the spec
// declares none.
std::vector<AttestationPolicy>
attestationPoliciesFromSpec(const llvm::json::Object &spec);

// Fail closed (throws `attest.multi_policy.unsupported`) when a single-guard
// rail is asked to lower MORE THAN ONE attestation policy (): the quorum
// lowering gates ONE guard per procedure, keyed by the workflow key, so
// rendering only the first policy would leave the others UNGATED (fail-open).
// Shared by the Solidity and PostgreSQL renderers so BOTH rails refuse
// identically (and the fail-closed throw lives in ONE place). No-op for 0/1
// policies. `railLowering` names the caller for the diagnostic (e.g. "the
// Solidity quorum lowering ()").
void requireSingleAttestationPolicy(
    const std::vector<AttestationPolicy> &policies,
    llvm::StringRef railLowering);

} // namespace neutrino

#endif // NEUTRINO_ATTESTATION_H
