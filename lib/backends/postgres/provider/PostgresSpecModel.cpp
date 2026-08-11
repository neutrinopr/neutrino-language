//===- PostgresSpecModel.cpp - capability-spec decode primitives (PG) -----===//
//
// The decode/model-preparation primitives the PostgreSQL leaf's renderers share
// (): value-type mapping, SQL escaping/quoting, operand lowering, and
// required-field access. Consumes only the frozen spec object + the value model
// — no ProcedureView.
//
//===----------------------------------------------------------------------===//

#include "PostgresSpecInternal.h"

#include "Neutrino/Expr.h"
#include "Neutrino/ValueModel.h"

#include "llvm/Support/JSON.h"

#include <set>
#include <string>

using namespace llvm;

namespace neutrino::postgres_detail {

// sqlType/sqlEsc/sqlQuote live below-waist in PgSqlSyntax.cpp (declared via
// PostgresSpecInternal.h -> PgSqlSyntax.h) so the raw-text authority can reuse
// the escaper without linking this above-waist model object.

// A debit/credit operand from the spec: {kind: ref|literal, value}. A literal
// lowers to a quoted SQL string; a ref lowers to p_<input> or v_<compute>.
std::string operandSql(const json::Object &op,
                       const std::set<std::string> &inputs) {
  StringRef kind = op.getString("kind").value_or("");
  std::string value = op.getString("value").value_or("").str();
  if (kind == "literal")
    return sqlQuote(value);
  return (inputs.count(value) ? "p_" : "v_") + value;
}

// Spec-ingestion failures surface as the registered `spec.ast` code (not
// `internal`): a renderer consuming an external spec reports a real,
// taxonomy-aligned diagnostic ( F3).
const json::Object &obj(const json::Value *v, const char *what) {
  const json::Object *o = v ? v->getAsObject() : nullptr;
  if (!o)
    throw ExprError("spec.ast",
                    std::string("capability-spec: missing/invalid ") + what);
  return *o;
}

} // namespace neutrino::postgres_detail
