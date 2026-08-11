//===- PgSqlSyntax.cpp - below-waist PostgreSQL syntax primitives () --===//
//
// The pure SQL-syntax leaf: the column-type map + the single-quote escaper /
// quoter. Below-waist — includes ONLY the syntax header and the
// (StringRef-only) value-type classifier; no CoordinationPlan, spec, profile,
// target-registry, or model-decision surface. Its object is what the
// below-waist raw-text authority (PgSqlText.cpp) links against, so that
// authority never reaches into the spec/model object (the  boundary gate
// enforces it). The above-waist renderers reuse these same definitions through
// PostgresSpecInternal.h.
//
//===----------------------------------------------------------------------===//

#include "PgSqlSyntax.h"

#include "Neutrino/ValueModel.h"

#include <string>

using namespace llvm;

namespace neutrino::postgres_detail {

std::string sqlType(StringRef ty) {
  switch (classifyValueType(ty)) {
  case ValueCategory::Money:
  case ValueCategory::Decimal:
    return "bigint";
  default:
    return "text";
  }
}

std::string sqlEsc(StringRef s) {
  std::string out;
  for (char c : s)
    out += (c == '\'') ? "''" : std::string(1, c);
  return out;
}

std::string sqlQuote(StringRef s) { return "'" + sqlEsc(s) + "'"; }

} // namespace neutrino::postgres_detail
