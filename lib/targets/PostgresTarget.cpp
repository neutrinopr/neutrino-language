//===- PostgresTarget.cpp - PostgreSQL target entry ---------------------===//
//
// Port of neutrino_translator/backends/postgres.py. SQL (schema/procedure/
// reconciliation) is byte-for-byte identical to the Python output; the DB test
// is a docker+psql shell harness (no Python) proving the same semantics.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/GenPostgres.h"
#include "Neutrino/GenPostgresSpec.h"
#include "Neutrino/GenSpec.h"

#include "Neutrino/PgDdl.h" // pgddl::RawSql / DdlCap — the  slice-2 DDL funnel

#include "../backends/postgres/model/PostgresModel.h"

#include "llvm/Support/Error.h"

#include "llvm/Support/JSON.h"

#include <algorithm>
#include <filesystem>
#include <fstream>

using namespace neutrino;

namespace {

const char *kReconciliation =
    "-- Reconciliation: a balanced procedure nets to zero per workflow key.\n"
    "-- Returns one row per key WITH DRIFT (empty result == reconciled).\n"
    "SELECT idempotency_key, SUM(signed_amount) AS drift\n"
    "  FROM postings\n"
    " GROUP BY idempotency_key\n"
    "HAVING SUM(signed_amount) <> 0;\n";

// Evidence-only reconciliation (): no ledger value moves, so there is
// nothing to net to zero. The audit view lists the accepted evidence instances.
const char *kReconciliationEvidence =
    "-- Evidence-only coordination: no ledger value moves, so there is "
    "nothing\n"
    "-- to reconcile to zero. This lists the accepted evidence instances.\n"
    "SELECT idempotency_key AS instance_key\n"
    "  FROM coordination_status\n"
    " WHERE reconciled\n"
    " ORDER BY idempotency_key;\n";

} // namespace

std::vector<std::string> neutrino::emitPostgresProject(
    const ProcedureView &view, const Scenario &scenario,
    const std::string &outDir, const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);

  // WP5 (): BOTH procedure.sql AND the docker/psql test harness are
  // rendered from the CANONICAL SPEC (the frozen contract, ), not
  // ProcedureView — the spec is emitted here and re-parsed so the migrated
  // renderer (GenPostgresSpec) consumes exactly the external contract (no
  // View.h, no re-parsed expression text). Single-sourcing the harness's
  // STRUCTURE off the same spec means it can never drift from procedure.sql;
  // the scenario is folded ONCE into the TestRealization artifact (WP2/)
  // and supplies only the concrete values/ledger. emitPostgresProject keeps
  // ProcedureView solely as the registry EmitFn signature (to emit the spec +
  // fold the realization).
  // The shared adapter emits + re-parses our OWN spec and fails closed (abort,
  // not a user diagnostic) if it does not parse to an object — an internal
  // invariant, off the  throw ratchet ().
  neutrino::SelfEmittedSpec spec =
      neutrino::ingestSelfEmittedSpec(view, coordinationPlan);
  const llvm::json::Object *specObj = &spec.object();

  // The base coordination schema, plus two INDEPENDENT additive extensions:
  // the optional `memo` column (, present only when an effect declares a
  // memo) and the Oracle S2d () quorum-acceptance guard tables (present
  // only when the spec is attested). Both extensions are empty by default, so
  // an unattested memo-less spec's schema.sql is byte-identical to before.
  // Evidence-only (): an effectless coordination emits the ledger-free
  // schema + an audit-view reconciliation; the quorum tables are appended the
  // same way. The effectful path is byte-identical to before.
  // The single mint of the DDL-authoring capability ( slice 2):
  // emitPostgresProject is befriended to forge + the RawSql bytes() sink.
  const pgddl::DdlCap cap = pgddl::DdlCap::forge();
  //  B2: the COMPLETE coordination schema (base tables + the rail's
  // quorum/temporal tables, the postings memo variant read from the finalized
  // sequence) is composed by the per-rail declarative schema recipe. No
  // handwritten base-schema, `RawSql operator+` splice, or direct plan read
  // here.
  pgddl::RawSql schema =
      generatePostgresQuorumSchemaFromSpec(cap, coordinationPlan);

  std::vector<std::pair<std::string, pgddl::RawSql>> files = {
      {(fs::path(outDir) / "schema.sql").string(), schema},
      {(fs::path(outDir) / "procedure.sql").string(),
       pgddl::rawSql(cap, generatePostgresProcedureFromSpec(coordinationPlan))},
      {(fs::path(outDir) / "reconciliation.sql").string(),
       pgddl::rawSql(cap, std::string(coordinationPlan.evidenceOnly
                                          ? kReconciliationEvidence
                                          : kReconciliation))},
      {(fs::path(outDir) / "run_db_test.sh").string(),
       pgddl::rawSql(cap,
                     generatePostgresDbTestFromSpec(
                         *specObj, realize(view, scenario, coordinationPlan),
                         coordinationPlan))},
  };
  std::vector<std::string> written;
  for (auto &f : files) {
    std::ofstream os(f.first);
    os << f.second.bytes();
    written.push_back(f.first);
  }
  fs::permissions((fs::path(outDir) / "run_db_test.sh").string(),
                  fs::perms::owner_exec | fs::perms::group_exec |
                      fs::perms::others_exec,
                  fs::perm_options::add);
  return written;
}
