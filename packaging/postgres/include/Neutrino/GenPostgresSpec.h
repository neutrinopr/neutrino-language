#ifndef NEUTRINO_GENPOSTGRES_SPEC_H
#define NEUTRINO_GENPOSTGRES_SPEC_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/TestRealization.h"

#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

//  slice-2 DDL funnel — opaque forward decls (the leaf-internal PgSqlText.h
// is NOT included from this public header; only the below entry names them).
namespace pgddl {
class RawSql;
class DdlCap;
} // namespace pgddl

// Render procedure.sql (M5 WP5, ;  legalization split). It legalizes +
// prints the normalized CoordinationPlan () and reads NOTHING else — no
// spec JSON, no View.h (no ProcedureView), no raw expression text: every
// decision (workflow key, balanced obligation, effect legs, reconciled
// terminal) and the per-effect memo are carried on the
// CoordinationPlan, and compute/guard expressions are lowered from the
// CoordinationPlan's typed AST via toSql. Byte-identical to the ProcedureView
// path it replaces. See docs/backends/BACKEND_GENERATORS.md.
std::string
generatePostgresProcedureFromSpec(const CoordinationPlan &coordinationPlan);

// Oracle S2d (): the extra schema DDL the M-of-N quorum-acceptance guard
// needs (the authorized-observer + quorum-acceptance tables), emitted ONLY when
// the coordination carries an attestation policy — returns "" otherwise, so an
// unattested coordination's schema.sql stays byte-identical. Parity with the
// Solidity guard (); PostgreSQL admits already-recovered observer
// identities (no on-rail ecrecover), the documented backend difference.
// A fail-closed RawSql ( slice 2); the DdlCap proves an authorized caller.
pgddl::RawSql
generatePostgresQuorumSchemaFromSpec(const pgddl::DdlCap &cap,
                                     const CoordinationPlan &coordinationPlan);

// Render the docker+psql shell test harness (run_db_test.sh) from the canonical
// spec too (M5 WP5 final slice, ). The harness's STRUCTURAL shape — input
// names/types/order, the workflow (idempotency) key, the entry count, the
// procedure name — is single-sourced from the SAME spec that renders
// procedure.sql, so procedure and harness cannot drift; only the concrete
// values/ledger come from the folded TestRealization (WP2, ). Like the
// procedure renderer this is a View.h-free entry point (no ProcedureView), so
// the whole migrated PostgreSQL renderer owns no independent workflow/state
// semantics. Byte-identical to the ProcedureView-based harness it replaces.
std::string
generatePostgresDbTestFromSpec(const llvm::json::Object &spec,
                               const TestRealization &tr,
                               const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENPOSTGRES_SPEC_H
