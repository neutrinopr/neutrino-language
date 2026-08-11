//===- PgSqlText.h - the PostgreSQL below-waist DDL-carrier host () --===//
//
// The below-waist leaf TU that hosts the generated `pgddl` DDL-carrier builders
// ( slice 2 / ): the capability mint, the sole raw-DDL minter, and the
// sole combiner are GENERATED into PgDdlBuilders.inc from the closed
// PostgresDdlCarrier.td descriptor and #included by PgSqlText.cpp. This header
// only pulls in the shared `pgddl` funnel + fwd-decls those builders need.
//
// The legacy raw PL/pgSQL TEXT path ( slice 1 — `pgtext::authorLine`,
// `pgtext::procedureLine`, the `Seam` capability, and the whole `sql::` typed
// emitter) is RETIRED (): the PostgreSQL render path is fully on the
// generated `PgStmt -> generated_printer::render -> codetext::Document` pipeline
// ( + /), so no handwritten raw-text author survives in this leaf.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_POSTGRES_PGSQLTEXT_H
#define NEUTRINO_BACKENDS_POSTGRES_PGSQLTEXT_H

#include "Neutrino/PgDdl.h" // pgddl::RawSql funnel + the shared fwd-decls

#endif // NEUTRINO_BACKENDS_POSTGRES_PGSQLTEXT_H
