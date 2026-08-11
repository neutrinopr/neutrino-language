#ifndef NEUTRINO_EXECUTION_ENVELOPE_H
#define NEUTRINO_EXECUTION_ENVELOPE_H

#include "Neutrino/CoordinationPlan.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"

#include <string>

namespace neutrino {

// One declared, TYPED input in an invocation's canonical payload: the input's
// name, its value CATEGORY (categoryName — the type tag a rail must reproduce),
// and its canonicalized value (decimal minor units for a numeric category, the
// token for a symbolic one). Built from the coordination plan's DECLARED input
// inventory, not the caller's raw maps, so the claim covers exactly the
// coordination's surface.
struct ExecutionInput {
  std::string name;
  std::string category;
  std::string value;
};

// A collision-resistant COORDINATION IDENTITY: a domain-separated structural
// hash of the normalized coordination plan's semantic core (procedure, workflow
// key, declared typed inputs, effect signatures, attestation policies,
// terminal, balance). Identical across the .neu (normalizePlan) and from-spec
// (planFromSpec) paths — both produce the same coordination plan () — so it
// names ONE coordination. Folded into the execution claim so acceptance for one
// coordination can never authorize another on a shared quorum guard.
std::string coordinationIdentityHash(const CoordinationPlan &coordinationPlan);

// The canonical per-invocation EXECUTION CLAIM (): a domain-separated hash
// binding the COORDINATION IDENTITY + workflow key + the TYPED input payload,
// so the payload is immutable per (coordination, key) — a later invocation on
// the same key that presents a different payload does not match this claim and
// is refused, and acceptance never crosses coordinations. Distinct from the
// agreementHash (spec/code identity, ): this hashes the RUNTIME values.
// Target-neutral: the reference evaluator and every rail derive the SAME claim.
// `canonicalInputs` need not be pre-sorted. Attestation acceptance verdicts are
// NOT part of the payload — a policy accepting later must not change the claim.
std::string executionClaimHash(llvm::StringRef coordinationIdentity,
                               llvm::StringRef workflowKey,
                               llvm::ArrayRef<ExecutionInput> canonicalInputs);

} // namespace neutrino

#endif // NEUTRINO_EXECUTION_ENVELOPE_H
