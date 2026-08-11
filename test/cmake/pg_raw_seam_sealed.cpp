//===- pg_raw_seam_sealed.cpp -  compile-NEGATIVE boundary probes -----===//
//
// This TU stands in for "any translation unit outside the governed legalization
// TU". Each PROBE_* selector isolates ONE sealed raw-authoring path and MUST
// FAIL TO COMPILE. The `postgres-raw-seam-sealed[.N]` CTests compile this file
// once per probe and pass iff that probe's compile fails with its expected
// diagnostic — so if any single path re-opens, exactly that probe starts
// compiling and the suite fails (the probes are independent). A structural
// boundary the type system holds, proven at build time, not a scanner fixture.
//
//===----------------------------------------------------------------------===//

#include "PostgresModel.h"

#include <string>
#include <utility>

using namespace neutrino::postgres_model;

#if defined(PROBE_RAWCAP_REMOVED)
// The legacy capability type is absent at the endpoint.
PgStmt probe() {
  PgStmt::RawCap cap;
  (void)cap;
  return PgStmt::blank();
}

#elif defined(PROBE_RAWLINE_REMOVED)
// The legacy raw factory is absent, rather than merely access-restricted.
PgStmt probe() { return PgStmt::rawLine("DROP TABLE postings;"); }

#elif defined(PROBE_IMPL_REMOVED)
// The private raw-author implementation type is deleted entirely.
auto probe() { return sizeof(PgStmt::Impl); }

#elif defined(PROBE_AGGREGATE)
// Forge a Line by brace/aggregate construction — the PgStmt constructor is
// private, so a `PgStmt{…}` build cannot bypass the factories/seam.
PgStmt probe() {
  return PgStmt{
      PgStmt::Kind::Line, "DROP TABLE postings;", {}, {}, false, {}, {}};
}

#elif defined(PROBE_MUTATION)
// Mutate a factory-obtained instance — the fields are const.
PgStmt probe() {
  PgStmt s = PgStmt::blank();
  s.kind = PgStmt::Kind::Line;
  return s;
}

#elif defined(PROBE_CTOR_PROBE_COMPLETION)
// The reviewer's exact attack: complete the old test-only friend name in an
// external TU and use it to reach the private canonical constructor with an
// arbitrary generated-node operand. The friend declaration is deleted, so the
// actual formerly privileged name has no access and this must not compile.
namespace neutrino {
namespace postgres_model {
struct PgStmtCtorProbe {
  static PgStmt go() {
    return PgStmt(PgStmt::Kind::ProgressFlag, {}, {}, {}, false, {}, {},
                  {"true; DROP TABLE postings; --"});
  }
};
} // namespace postgres_model
} // namespace neutrino
PgStmt probe() { return neutrino::postgres_model::PgStmtCtorProbe::go(); }

#else
#error "pg_raw_seam_sealed.cpp must be compiled with a -DPROBE_* selector"
#endif
