#ifndef NEUTRINO_GENSOLIDITY_SPEC_H
#define NEUTRINO_GENSOLIDITY_SPEC_H

#include "Neutrino/Attestation.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/SolidityPackageArtifacts.h"
#include "Neutrino/TestRealization.h"

#include "llvm/Support/JSON.h"

#include <string>
#include <vector>

namespace neutrino {

// Render the Solidity coordination contract (M5 WP6, ;  legalization
// split). It legalizes + prints the normalized CoordinationPlan () and
// reads NOTHING else — no spec JSON, no View.h (no ProcedureView), no raw
// expression text: every decision (workflow key, balanced obligation, effect
// legs, terminal projection) and every presentation label (invoked-event name,
// per-effect memo) is carried on the coordination plan, and compute/guard
// expressions are lowered from the coordination plan's typed AST via
// toSolidity. Besides EVM realization details (Solidity syntax, u_ prefixes,
// keccak keying), it hand-authors the on-chain coordination state machine as a
// FIXED 2-state projection (Status{None,Reconciled}) deliberately NOT derived
// from the full lifecycle (see docs/backends/BACKEND_GENERATORS.md); it stays
// pinned to the coordination plan (the Reconciled terminal projects the success
// terminal, the balance guard tracks the balanced invariant). Byte-identical to
// the ProcedureView path it replaces. The coordination plan is built once by
// the caller (from the verified MLIR internally, or reconstructed from an
// external spec). See docs/backends/BACKEND_GENERATORS.md.
std::string
generateSolidityContractFromSpec(const CoordinationPlan &coordinationPlan);

/// Render the complete source bundle required by a canonical capability spec:
/// the coordination contract plus any policy-required quorum guard and
/// coordination-envelope library. This is shared by source/scenario generation
/// and external --from-spec ingestion so neither entry point can silently drop
/// a required source dependency.
std::vector<SoliditySourceFile>
generateSoliditySourcesFromSpec(const CoordinationPlan &coordinationPlan);

// Render the Foundry test harness (<Name>.t.sol) from the canonical spec too
// (M5 WP8 follow-up,  — the symmetric analog of the migrated PostgreSQL
// harness, ). The harness's STRUCTURAL shape — input names/types/order, the
// workflow (idempotency) key, the trigger, compute/effect names, the entry set
// — is single-sourced from the SAME spec that renders the contract, so contract
// and test cannot drift; only the concrete values/ledger come from the folded
// TestRealization (WP2, ). Like the contract renderer this is a View.h-free
// entry point (no ProcedureView), so the whole migrated Solidity renderer owns
// no independent structural semantics. Byte-identical to the
// ProcedureView-based harness it replaces.
std::string
generateSolidityTestFromSpec(const llvm::json::Object &spec,
                             const TestRealization &tr,
                             const CoordinationPlan &coordinationPlan);

// Render the on-chain M-of-N threshold-quorum acceptance guard from one
// attestation policy (oracle S2c, ) — the S2 lowering of the spec-declared
// attestation policy () to the SECURITY-REVIEWED reference contract shape
// (). The rendered bytes are byte-identical to the vetted reference golden
// (the reference-first methodology : reproduce the reviewed pattern, do not
// invent one; a byte-golden diff proves it). The guard is deployment-
// independent — M/N/observer-addresses/capabilityHash are constructor arguments
// resolved at deploy/binding — so `exact` canonicalization renders the reviewed
// guard verbatim; an unsupported canonicalization (e.g. numeric `median`) fails
// CLOSED rather than emit an unreviewed guard.
std::string generateThresholdQuorumGuard(const AttestationPolicy &policy);
// The  coordination-envelope library
// (examples/oracle-reference/coordination-envelope), reproduced byte-identically.
// A temporal per-policy coordination () emits + imports it to recompute the
// execution claim on chain and bind each guard group to acceptedExecutionClaim.
// A byte-golden diff pins it to the reference.
} // namespace neutrino

#endif // NEUTRINO_GENSOLIDITY_SPEC_H
