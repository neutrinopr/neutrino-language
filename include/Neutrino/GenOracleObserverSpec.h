#ifndef NEUTRINO_GENORACLEOBSERVER_SPEC_H
#define NEUTRINO_GENORACLEOBSERVER_SPEC_H

#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// The oracle-consensus OFF-CHAIN observer backend (M5 oracle S4, ).
// Renders, from the frozen capability-spec's attestation policy () plus an
// observation binding, the deterministic serverless observer code + the
// aggregation package the on-chain M-of-N acceptance guard consumes. Like the
// other backend renderers (postgres/security/capability, /) it consumes
// ONLY the capability-spec JSON + the binding JSON + the AttestationPolicy leaf
// contract — no ProcedureView — so it links only NeutrinoSpecContract. See
// docs/backends/BACKEND_GENERATORS.md.
//
// Thesis (): Neutrino can't verify "is X true?", but consensus turns that
// into a predicate it CAN render: "did an M-of-N quorum sign the canonical form
// of X?". The observer is the off-chain half — subscribe -> canonicalize ->
// sign — and the guard (S2) is the on-chain half; both single-source the SAME
// canonical claim from this policy, so they cannot disagree (the S7 parity gate
// enforces it).

// One rendered artifact: a repo-relative path (under the output dir) + its
// bytes.
struct OracleFile {
  std::string path;
  std::string content;
};

// Render the observer + aggregation files for every attestation policy the spec
// declares, using `binding` (an `neutrino.observation-binding` document,
// target- profile-shaped, /S5) to resolve each policy's observer-set
// REFERENCE to the concrete mock source + the N observer members (id + public
// key). Deterministic: the rendered code carries no timestamp/nonce; the
// runtime secp256k1 signer and keccak256 hasher are INJECTED (real at deploy,
// mocked in tests), so CI needs no crypto dependency and the byte-goldens are
// stable.
//
// Fail-closed (throws neutrino::ExprError with a `spec.*`/`binding.*` code):
//   - a policy whose observer-set ref has no binding entry;
//   - a binding member set of size N < M (the spec threshold) — the quorum
//   could
//     never be met, so the observer package is refused rather than emitted.
std::vector<OracleFile>
generateOracleObserverFromSpec(const llvm::json::Object &spec,
                               const llvm::json::Object &binding);

} // namespace neutrino

#endif // NEUTRINO_GENORACLEOBSERVER_SPEC_H
