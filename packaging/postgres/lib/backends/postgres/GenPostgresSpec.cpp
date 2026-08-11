//===- GenPostgresSpec.cpp - PostgreSQL leaf public entry (orchestration) -===//
//
// Public ABI wrappers project once, then delegate to the graph-only PostgreSQL
// adapter. The backend model never receives the CoordinationPlan. The db-test
// harness remains an explicit non-production scenario boundary.
// NeutrinoBackendPostgres stays ONE leaf library, no View.h. See
// docs/backends/BACKEND_GENERATORS.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenPostgresSpec.h"

#include "PostgresModel.h"
#include "PostgresRecipeProvider.h"
#include "PostgresSpecInternal.h"

#include "Neutrino/BackendProjection.h"

#include "llvm/Support/Error.h"

namespace neutrino {

namespace {
projection::BackendProjectionGraph
projectForPostgres(const CoordinationPlan &coordinationPlan) {
  llvm::Expected<projection::BackendProjectionGraph> graph =
      projection::projectBackendGraph(coordinationPlan);
  if (!graph)
    postgres_model::fail("spec.ast", llvm::toString(graph.takeError()));
  return std::move(*graph);
}
} // namespace

std::string
generatePostgresProcedureFromSpec(const CoordinationPlan &coordinationPlan) {
  // Thin from-spec adapter: hydrate the plan into the backend graph, then
  // dispatch to the roled provider that owns the procedure composition. No
  // tracked construction lives here.
  return postgres_model::materializePostgresProcedureArtifact(
      projectForPostgres(coordinationPlan));
}

pgddl::RawSql
generatePostgresQuorumSchemaFromSpec(const pgddl::DdlCap &cap,
                                     const CoordinationPlan &coordinationPlan) {
  // Thin from-spec adapter: the roled provider owns the schema composition
  // behind the DdlCap authority.
  return postgres_model::materializePostgresQuorumSchemaArtifact(
      cap, projectForPostgres(coordinationPlan));
}

std::string
generatePostgresDbTestFromSpec(const llvm::json::Object &spec,
                               const TestRealization &tr,
                               const CoordinationPlan &coordinationPlan) {
  return postgres_detail::renderDbTest(spec, tr, coordinationPlan);
}

} // namespace neutrino
