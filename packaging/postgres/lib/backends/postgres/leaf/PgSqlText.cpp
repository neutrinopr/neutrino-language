//===- PgSqlText.cpp - the PostgreSQL below-waist DDL-carrier host () -===//
//
// Hosts the generated `pgddl` DDL-carrier builders ( slice 2 / ) via
// the #included PgDdlBuilders.inc. BELOW-WAIST / syntax-only: no
// CoordinationPlan, capability-spec, profile, target-registry, or
// model-decision surface enters this TU.
//
// : the legacy raw PL/pgSQL TEXT authors (`pgtext::authorLine`,
// `pgtext::procedureLine`, the `Seam`-gated `sql::Stmt::line` escape) are
// RETIRED — the PostgreSQL render path is fully on the generated
// `PgStmt -> generated_printer::render -> codetext::Document` pipeline ( +
// /), so no handwritten raw-text author survives in this leaf. (The
//  ledgerUpsert / postingInsert composers were already retired to the
// generated LedgerUpsert / PostingInsert[WithMemo] nodes.)
//
//===----------------------------------------------------------------------===//

#include "PgSqlText.h"

//  (Group C): the  slice-2 DDL-carrier construction — the capability
// mint (`DdlCap::forge`), the sole raw-DDL minter (`rawSql`), and the sole
// combiner (`operator+`) — is GENERATED from the closed PostgresDdlCarrier.td
// descriptor into the authenticated PgDdlBuilders.inc, so no handwritten
// construction survives in this leaf. The out-of-line owned symbols, their
// signatures, and the  friend seals (owned by Neutrino/PgDdl.h) are
// unchanged; the reviewed  REVOKE bodies call the generated minter/combiner
// verbatim. The `.inc` carries its own `namespace neutrino::pgddl { … }`.
#include "PgDdlBuilders.inc"
