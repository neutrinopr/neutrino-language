//===- PgSqlSyntax.h - below-waist PostgreSQL syntax primitives () ----===//
//
// The pure SQL-syntax leaf: the column-type map and the single-quote escaper +
// quoter. StringRef in, std::string out — no CoordinationPlan, spec, profile,
// target-registry, or model-decision surface, so the below-waist SQL-text
// authority (PgSqlText.cpp) can escape/frame literals without crossing the
//  boundary. Defined below-waist in PgSqlSyntax.cpp; re-exported through
// PostgresSpecInternal.h for the above-waist units that already used them.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_POSTGRES_PGSQLSYNTAX_H
#define NEUTRINO_BACKENDS_POSTGRES_PGSQLSYNTAX_H

#include "llvm/ADT/StringRef.h"

#include <string>

namespace neutrino::postgres_detail {

// The SQL column type for a spec value type; the SQL single-quote escaper; and
// the escaper wrapped in single quotes.
std::string sqlType(llvm::StringRef ty);
std::string sqlEsc(llvm::StringRef s);
std::string sqlQuote(llvm::StringRef s);

} // namespace neutrino::postgres_detail

#endif // NEUTRINO_BACKENDS_POSTGRES_PGSQLSYNTAX_H
