//===- postgres_effect_render_driver.cpp - real-path C1 render driver ----===//
//
//  C1 real-generator mutation witness. Renders a committed capability-spec
// to procedure.sql through the ACTUAL production path —
// planFromSpec -> generatePostgresProcedureFromSpec (which drives
// projection materialization / PgStmt::effectLedgerComment / rendering) — and
// writes the SQL to stdout. Unlike the standalone shell
// harness (a stub PgStmt + only the generated include), this exercises the real
// factory + routing, so the render-pair driver's negative bites when
// the effectful idiom stops emitting EffectLedgerComment, the operands are
// misordered, or the factory is deleted — not only when the handler text
// drifts.
//
// The SAME source is compiled twice (see CMakeLists.txt): once linking the
// committed backend, and once with PostgresModel.cpp recompiled against a
// .td-MUTATED PostgresPrinterHandlers.inc — proving the .td mutation changes
// the production comment bytes through the real path.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenPostgresSpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

using namespace neutrino;

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: postgres-effect-render <capability-spec.json>\n");
    return 2;
  }
  std::ifstream in(argv[1]);
  if (!in) {
    fprintf(stderr, "cannot open the capability-spec\n");
    return 2;
  }
  std::stringstream ss;
  ss << in.rdbuf();

  llvm::Expected<llvm::json::Value> j = llvm::json::parse(ss.str());
  if (!j) {
    fprintf(stderr, "capability-spec is not valid JSON\n");
    return 2;
  }
  const llvm::json::Object *spec = j->getAsObject();
  if (!spec) {
    fprintf(stderr, "capability-spec is not a JSON object\n");
    return 2;
  }
  llvm::Expected<neutrino::CoordinationPlan> coordinationPlan =
      neutrino::planFromSpec(*spec);
  if (!coordinationPlan) {
    fprintf(stderr, "capability-spec failed coordination-plan normalization\n");
    return 2;
  }
  std::string sql = generatePostgresProcedureFromSpec(*coordinationPlan);
  fputs(sql.c_str(), stdout);
  return 0;
}
