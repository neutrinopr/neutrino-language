//===- PostgresRecipeProvider.h - generated-recipe PostgreSQL adapter -----===//
//
// The first REAL PostgreSQL resolver-reachable recipe provider (),
// mirroring the merged Solidity evidence extraction (). It owns the
// PostgreSQL recipe provider registration/discovery the  shape/builder
// bootstrap deferred. Recipe traversal, exact-key resolution, nesting,
// ordering, and cardinality remain in NeutrinoRecipe; this provider maps
// generated opaque node IDs to the existing typed PostgreSQL model carriers and
// snapshots the finalized evidence values (already lowered at the
// finalized-value boundary by `computeEvidenceInputs`).
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_POSTGRES_POSTGRESEVIDENCEINPUTS_H
#define NEUTRINO_BACKENDS_POSTGRES_POSTGRESEVIDENCEINPUTS_H

#include "PostgresModel.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/RecipeRuntime.h" // recipe::FinalizedIdiomKey (caller-passed key)

#include "llvm/Support/Error.h"

#include <cstdint>
#include <string>
#include <vector>

namespace neutrino {
namespace postgres_model {

// The evidence procedure's decided target VALUES, synthesized once at the
// finalized-value boundary from the verified FinalizedProjectionSequence (the
//  `computeEvidenceContractInputs` analog). The recipe binds these by
// `Direct`; the provider only snapshots and mechanically binds them.
struct EvidenceProcedureInputs {
  std::string name;            // raw procedureNamespace (gate/revoke)
  std::string executeName;     // execute_<name>
  std::string procLiteral;     // sqlQuote(name)
  std::string key;             // p_<replayKey>
  std::string keyType;         // sqlType(key type)
  std::string observerSet;     // raw observer-set id (gate quotes it)
  std::string quorumM;         // decimal quorum threshold
  std::string quorumPredicate; // NOT EXISTS (... quorum_acceptance ...)
  std::string replayPredicate; // NOT FOUND
  std::string statusAtom;      // reconciled
  struct Param {
    std::string name; // already p_-prefixed
    std::string type; // lowered SQL type
    uint64_t ordinal; // projection-owned order
  };
  std::vector<Param> params;
};

// Synthesize the evidence procedure inputs from the verified projection.
// Defined in PostgresModel.cpp (it consumes the file-local finalized-value
// helpers); constructs NO target node — only already-lowered strings.
EvidenceProcedureInputs
computeEvidenceInputs(const projection::FinalizedProjectionSequence &sequence);

// Package-local  security resolvers (defined in PostgresModel.cpp beside
// the reviewed primitives, whose bodies stay unmoved). The recipe provider
// invokes these during typed node construction as a registered
// PG-QUORUM-SINGLE(+REVOKE) consumer; it never composes the reviewed generation
// itself.
PgFunction resolveQuorumGate(const std::string &name, const std::string &pkey,
                             const std::string &keyType,
                             const std::string &observerSet, int quorumM);
pgddl::RawSql resolveQuorumRevoke(const pgddl::DdlCap &cap,
                                  const std::string &name,
                                  const std::string &keyType);

//  B3: the one procedure entry for every rail. The caller passes the exact
// finalized idiom `key` (the rail is the key's `mode` component) and the
// verified `sequence`; the provider resolves that key's recipe and synthesizes
// the rail's finalized inputs from the sequence behind the recipe seam (via the
// package-local compute*Inputs). No per-rail entry, view, or backend branch
// survives. Fails closed (postgres_model::fail) if the manifest does not
// resolve `key` — no fallback path.
PgProcedure materializeProjectionProcedure(
    const recipe::FinalizedIdiomKey &key,
    const projection::FinalizedProjectionSequence &sequence,
    const pgddl::DdlCap &ddlCap);

//===----------------------------------------------------------------------===//
//  temporal ( per-policy quorum) recipe inputs + seam.
//===----------------------------------------------------------------------===//

// The temporal acceptance procedure's decided target VALUES, synthesized once
// at the finalized-value boundary from the verified FinalizedProjectionSequence
// by `computeTemporalInputs` (the temporal analog of `computeEvidenceInputs`).
// Every SQL fragment (predicates, the claim expression, each posting's lowered
// operands) is already lowered; the recipe binds them by `Direct` and owns the
// order + repeated-group composition. `attestation` is the finalized policy
// view the reviewed  gate consumes (via the package-local temporal
// resolver); the provider/recipe path never touches CoordinationPlan.
struct TemporalProcedureInputs {
  std::string name;            // raw procedureNamespace (gate/revoke)
  std::string executeName;     // execute_<name>
  std::string proc;            // sqlQuote(name)
  std::string key;             // p_<replayKey> (pkey)
  std::string rawKey;          // <replayKey> (postingInsert raw key)
  std::string keyType;         // sqlType(key type)
  std::string statusSuccess;   // projected success status atom
  std::string replayPredicate; // EXISTS coordination_status AND status
  std::string claimVar;        // v_claim (fixed PL/pgSQL variable)
  std::string claimExpr;       // neu_execution_claim(...)
  std::string
      claimMismatchPredicate; // EXISTS key_claim ... execution_claim <> v_claim
  std::string keyClaimPredicate; // v_progress AND NOT EXISTS key_claim
  std::string donePredicate;     // AND of the committed_group EXISTS terms
  std::string
      balancePredicate; // SUM(signed_amount) ... <> 0 (same per assertion)
  struct Param {
    std::string name; // already p_-prefixed
    std::string type; // lowered SQL type
    uint64_t ordinal; // projection-owned order
  };
  struct Compute {
    std::string var;  // v_<name>
    std::string expr; // already-lowered SQL expression
    uint64_t ordinal;
  };
  struct Posting {
    std::string negativePredicate; // (amount) < 0
    std::string negativeMessage;   // negative money for <name>
    std::string ledger, party, currency, signedAmount;
    std::string entry, amount, memo; // postingInsert per-posting operands
    uint64_t ordinal;
  };
  struct Group {
    std::string
        holdsPredicate; // (EXISTS quorum_acceptance ...) AND NOT committed(gi)
    std::string committedOrdinal; // committed_group group_ordinal operand
    uint64_t ordinal;
    std::vector<Posting> postings;
  };
  struct Balance {
    uint64_t ordinal; // loop counter only; predicate is procedure-level
  };
  std::vector<Param> params;
  std::vector<Compute> computes;
  std::vector<Group> groups;
  std::vector<Balance> balances;
  // Finalized policy view (a snapshot) the reviewed per-policy gate consumes;
  // held by value so it outlives node construction (the provider builds the
  // gate carrier from it inside the temporal security resolver).
  projection::AttestationProjection attestation;
};

// Synthesize the temporal procedure inputs from the verified projection.
// Defined in PostgresModel.cpp (it reuses the file-local finalized-value
// helpers so the lowered SQL is byte-identical to the retired handwritten
// materializer); constructs NO target node.
TemporalProcedureInputs
computeTemporalInputs(const projection::FinalizedProjectionSequence &sequence);

// Package-local  security resolvers for the temporal rail (defined in
// PostgresModel.cpp beside the reviewed primitives buildTemporalAcceptGate /
// temporalAcceptRevoke, whose bodies stay unmoved). The recipe provider invokes
// these during typed node construction as a registered
// PG-QUORUM-TEMPORAL(+REVOKE) consumer; the per-policy gate carrier is built
// inside the resolver from the finalized AttestationProjection.
PgFunction resolveTemporalGate(const std::string &name, const std::string &pkey,
                               const std::string &keyType,
                               const projection::AttestationProjection &att);
pgddl::RawSql resolveTemporalRevoke(const pgddl::DdlCap &cap,
                                    const std::string &name,
                                    const std::string &keyType);

//===----------------------------------------------------------------------===//
//  B3 coordination-schema recipe seam.
//===----------------------------------------------------------------------===//

// The reviewed  coordination-envelope exact-body leaf (PG-EXECUTION-ENVELOPE),
// emitted from this allowed-consumer TU; the schema recipe composes it.
pgddl::RawSql resolveSchemaEnvelope(const pgddl::DdlCap &cap);

// Materialize the COMPLETE coordination-schema DDL (base coordination tables +
// the rail's quorum/temporal tables) through the generated schema recipe the
// caller keys. The verified `sequence` supplies the postings memo fact. Fails
// closed on any resolver/key error — no fallback, no handwritten section
// splice.
pgddl::RawSql materializeCoordinationSchema(
    const projection::FinalizedProjectionSequence &sequence,
    const recipe::FinalizedIdiomKey &key, const pgddl::DdlCap &ddlCap);

//===----------------------------------------------------------------------===//
//  effectful recipe inputs + seam.
//===----------------------------------------------------------------------===//

// The effectful procedure's decided target VALUES, synthesized once at the
// finalized-value boundary by `computeEffectfulInputs`. Every SQL fragment (the
// replay/requirement/balance predicates, each posting's lowered operands) is
// already lowered; the recipe binds them by `Direct` and owns the order. This
// is the (currently precomposed) target-value contract shared with the other
// PostgreSQL rails. It carries NO structural authority: the variant key is the
// finalized idiom key the caller passes, and the attestation/guard
// optional-slot presence is read from the finalized sequence facts in the
// provider — not from any backend Boolean here.
struct EffectfulProcedureInputs {
  std::string name;            // raw procedureNamespace (gate/revoke)
  std::string executeName;     // execute_<name>
  std::string attestName;      // attest_<name> (ungated self-attestation gate)
  std::string proc;            // sqlQuote(name)
  std::string key;             // p_<replayKey> (pkey)
  std::string rawKey;          // <replayKey> (postingInsert raw key)
  std::string keyType;         // sqlType(key type)
  std::string statusSuccess;   // projected success status atom
  std::string statusAttest;    // projected accepted/attested status atom
  std::string replayPredicate; // EXISTS coordination_status ... AND success
  // Both requirement predicates are precomposed unconditionally; the recipe's
  // WithAttestation / WithoutAttestation arm each binds its own, so no backend
  // Boolean selects between them.
  std::string quorumRequirementPredicate; // NOT EXISTS quorum_acceptance
  std::string selfRequirementPredicate;   // NOT EXISTS coordination_status ...
                                          // AND attested
  std::string notFoundPredicate; // "NOT FOUND" idempotency-return guard
  std::string idempotencyEntry;  // sqlEsc(name) for postingIdempotency
  std::string balancePredicate;  // SUM(signed_amount) ... <> 0
  // The quorum gate observer set / threshold are read from the finalized
  // attestation policy in the provider (consumed only under WithAttestation),
  // so they are not precomposed here.
  struct Param {
    std::string name; // already p_-prefixed
    std::string type; // lowered SQL type
    uint64_t ordinal; // projection-owned order
  };
  struct Compute {
    std::string var;  // v_<name>
    std::string expr; // already-lowered SQL expression
    uint64_t ordinal;
  };
  struct Posting {
    std::string negativePredicate; // (amount) < 0
    std::string negativeMessage;   // negative money for <name>
    std::string ledger, party, currency, signedAmount;
    std::string entry, amount, memo; // postingInsert + comment operands
    std::string direction;           // effectLedgerComment kind
    std::string commentSuffix;       // "" or " when <guard>"
    std::string guard;               // guardSql (value-guarded) — else empty
    uint64_t ordinal;
  };
  struct Balance {
    uint64_t ordinal; // loop counter only; predicate is procedure-level
  };
  std::vector<Param> params;
  std::vector<Compute> computes;
  std::vector<Posting> postings;
  std::vector<Balance> balances;
  // Attestation optional-slot extents, decided ONCE here from the finalized
  // sequence.attestationKind. slotExtent returns these precomputed values
  // directly — no backend Boolean, no conditional at the render boundary. The
  // two are mutually exclusive (exactly one is 1).
  unsigned withAttestationExtent = 0;
  unsigned withoutAttestationExtent = 0;
};

// Synthesize the effectful procedure inputs from the verified projection.
// Defined in PostgresModel.cpp (it reuses the file-local finalized-value
// helpers so the lowered SQL is byte-identical to the retired handwritten
// materializer); constructs NO target node. The reachable variant is read from
// the finalized `sequence.attestationKind` (not a backend flag) only to shape
// the precomposed requirement predicate / quorum operands.
EffectfulProcedureInputs
computeEffectfulInputs(const projection::FinalizedProjectionSequence &sequence);

} // namespace postgres_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_POSTGRES_POSTGRESEVIDENCEINPUTS_H
