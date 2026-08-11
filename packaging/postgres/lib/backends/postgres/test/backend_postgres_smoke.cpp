//===- backend_postgres_smoke.cpp - link-smoke for NeutrinoBackendPostgres
//() ---===//
//
// Proves the Postgres backend is usable STANDALONE: this executable links ONLY
// `NeutrinoBackendPostgres` (see CMakeLists.txt) — not `NeutrinoEmit`,
// `NeutrinoAnalysis`, or any other backend. If the carve were leaky (the SQL
// renderer reached a ProcedureView / spec-producer / other-backend symbol),
// this would fail to LINK, so the target graph itself enforces the  D3
// boundary. It renders procedure.sql from a committed capability-spec (argv[1])
// through the backend's public spec->SQL entry point.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenPostgresSpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "backend-postgres-smoke: %s\n", msg);
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 2)
    return fail("usage: backend-postgres-smoke <capability-spec.json>");
  std::ifstream in(argv[1]);
  if (!in)
    return fail("cannot open the capability-spec");
  std::stringstream ss;
  ss << in.rdbuf();

  llvm::Expected<llvm::json::Value> j = llvm::json::parse(ss.str());
  if (!j)
    return fail("capability-spec is not valid JSON");
  const llvm::json::Object *spec = j->getAsObject();
  if (!spec)
    return fail("capability-spec is not a JSON object");

  // The migrated spec->SQL renderer (leaf-only): rebuilds compute ASTs from the
  // spec (exprFromJson) and lowers via toSql, no ProcedureView. Linking +
  // calling it here with ONLY libNeutrinoBackendPostgres.a on the link line is
  // the boundary proof.
  llvm::Expected<neutrino::CoordinationPlan> coordinationPlan =
      neutrino::planFromSpec(*spec);
  if (!coordinationPlan)
    return fail("capability-spec failed coordination-plan normalization");
  std::string sql = generatePostgresProcedureFromSpec(*coordinationPlan);
  if (sql.find("CREATE OR REPLACE FUNCTION") == std::string::npos)
    return fail("rendered procedure.sql missing CREATE OR REPLACE FUNCTION");

  puts("backend-postgres-smoke OK (Postgres backend links standalone: "
       "capability-spec -> procedure.sql via the leaf, no NeutrinoEmit)");
  return 0;
}
