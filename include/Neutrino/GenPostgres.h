#ifndef NEUTRINO_GENPOSTGRES_H
#define NEUTRINO_GENPOSTGRES_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/TestRealization.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// The migrated PostgreSQL renderer is entirely View.h-free: BOTH procedure.sql
// and the docker+psql shell test harness (run_db_test.sh) render from the
// canonical spec (generatePostgresProcedureFromSpec /
// generatePostgresDbTestFromSpec, GenPostgresSpec.h, WP5/). This header
// retains only the target's EmitFn entry, which takes a ProcedureView solely to
// emit the spec and fold the TestRealization (M5 WP2, ).

// Target-owned generator contract (): the `postgres` target's emit entry —
// writes schema.sql, procedure.sql, reconciliation.sql, run_db_test.sh; returns
// written paths. Matches the registry EmitFn; `postgres` is a value-lowering
// target (security-gated). See docs/backends/BACKEND_GENERATORS.md.
std::vector<std::string>
emitPostgresProject(const ProcedureView &view, const Scenario &scenario,
                    const std::string &outDir,
                    const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENPOSTGRES_H
