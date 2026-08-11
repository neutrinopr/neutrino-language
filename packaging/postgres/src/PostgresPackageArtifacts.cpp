// The reviewed backend-package sink (/). This TU defines the ONE
// symbol befriended by pgddl::DdlCap and pgddl::RawSql for the package:
// `neutrino::materializePostgresPackageArtifacts`. The protocol entry
// (PostgresBackendMain.cpp) is deliberately NOT a friend -- it calls this and
// receives already-extracted bytes, so the extraction authority stays pinned to
// a single named function rather than spreading across the package.
#include "PostgresPackageArtifacts.h"
#include "PostgresRecipeProvider.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/PgDdl.h"

#include <algorithm>

namespace neutrino {
namespace {

// Byte-identical to the text the in-core registry entry emits. These bytes are
// pinned by test/ir/oracle/golden/postgres/reconciliation.sql, so the SQL-byte
// witness fails if this copy and that oracle ever diverge -- which is what makes
// carrying it here safe until the in-core emitter retires.
const char *kReconciliation =
    "-- Reconciliation: a balanced procedure nets to zero per workflow key.\n"
    "-- Returns one row per key WITH DRIFT (empty result == reconciled).\n"
    "SELECT idempotency_key, SUM(signed_amount) AS drift\n"
    "  FROM postings\n"
    " GROUP BY idempotency_key\n"
    "HAVING SUM(signed_amount) <> 0;\n";

const char *kReconciliationEvidence =
    "-- Evidence-only coordination: no ledger value moves, so there is "
    "nothing\n"
    "-- to reconcile to zero. This lists the accepted evidence instances.\n"
    "SELECT idempotency_key AS instance_key\n"
    "  FROM coordination_status\n"
    " WHERE reconciled\n"
    " ORDER BY idempotency_key;\n";

} // namespace

std::vector<std::pair<std::string, std::string>>
materializePostgresPackageArtifacts(
    const projection::BackendProjectionGraph &graph) {
  const pgddl::DdlCap cap = pgddl::DdlCap::forge();
  // `evidenceOnly` comes from the PROJECTED execution mode, not from a
  // CoordinationPlan the package cannot see: the projector already folded that
  // fact in ( G1-S1), which is exactly why the package needs no plan.
  //
  // The mode rides on each ProjectedLifecycleRole rather than the graph root.
  // It is coordination-uniform by construction, so requiring EVERY role to
  // agree is equivalent for well-formed graphs and fails safe otherwise: a
  // mixed or empty set falls through to the effectful reconciliation, which is
  // exactly what the in-core emitter's `evidenceOnly ? ... : kReconciliation`
  // default does.
  const bool evidenceOnly =
      !graph.projectedLifecycleRoles.empty() &&
      std::all_of(graph.projectedLifecycleRoles.begin(),
                  graph.projectedLifecycleRoles.end(),
                  [](const projection::ProjectedLifecycleRole &role) {
                    return role.mode == projection::ExecutionMode::Evidence;
                  });

  const pgddl::RawSql schema =
      postgres_model::materializePostgresQuorumSchemaArtifact(cap, graph);

  std::vector<std::pair<std::string, std::string>> artifacts;
  artifacts.emplace_back("schema.sql", schema.bytes());
  artifacts.emplace_back(
      "procedure.sql",
      postgres_model::materializePostgresProcedureArtifact(graph));
  artifacts.emplace_back(
      "reconciliation.sql",
      std::string(evidenceOnly ? kReconciliationEvidence : kReconciliation));
  return artifacts;
}

} // namespace neutrino
