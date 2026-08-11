//===- PostgresSpecInternal.h - internal seam of the PostgreSQL leaf ------===//
//
// Internal declarations shared across the PostgreSQL leaf's responsibility
// units ( S5 / ): decode/model-preparation primitives
// (PostgresSpecModel.cpp), procedure + quorum-schema rendering
// (PostgresProcedure.cpp), and the reconciliation/db-test harness
// (PostgresDbTest.cpp). Not a public header — the exported entry points stay in
// Neutrino/GenPostgresSpec.h. Backend-neutral inputs only (the frozen spec
// object + CoordinationPlan/TestRealization); NO ProcedureView / View.h.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_POSTGRES_SPECINTERNAL_H
#define NEUTRINO_BACKENDS_POSTGRES_SPECINTERNAL_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/TestRealization.h"

#include "PgSqlSyntax.h" // sqlType/sqlEsc/sqlQuote (below-waist syntax leaf)

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <set>
#include <string>

namespace neutrino::postgres_detail {

// --- decode / model-preparation primitives (PostgresSpecModel.cpp) ---
// sqlType/sqlEsc/sqlQuote come from PgSqlSyntax.h above. Here: a debit/credit
// operand lowered to a quoted literal or a p_<input>/v_<compute> reference; and
// the required-object accessor that reports a `spec.ast` diagnostic on a
// missing/invalid external-spec field.
std::string operandSql(const llvm::json::Object &op,
                       const std::set<std::string> &inputs);
const llvm::json::Object &obj(const llvm::json::Value *v, const char *what);

// --- procedure / schema rendering ---
// The procedure + quorum schema legalize + print through PostgresModel
// (the graph-only PostgreSQL materializer and render/schema sinks),
// which drives off the verified BackendProjectionGraph; see PostgresModel.h.

// --- reconciliation / test rendering (PostgresDbTest.cpp) ---
std::string renderDbTest(const llvm::json::Object &spec,
                         const TestRealization &tr,
                         const CoordinationPlan &coordinationPlan);

} // namespace neutrino::postgres_detail

#endif // NEUTRINO_BACKENDS_POSTGRES_SPECINTERNAL_H
