//===- pg_rawsql_sealed.cpp -  slice 2 compile-NEGATIVE probes --------===//
//
// This TU stands in for "any translation unit that is not a reviewed DDL author
// / sink". Each PROBE_* selector isolates ONE fail-closed property of the
// pgddl::RawSql DDL funnel and MUST FAIL TO COMPILE. The
// `pg-rawsql-sealed.<PROBE>` CTests compile this file once per probe and pass
// iff that probe's compile fails with its expected diagnostic — a structural
// boundary the type system holds, proven at build time.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/PgDdl.h"

#include <string>

namespace pgddl = ::neutrino::pgddl;

#if defined(PROBE_FROM_STRING)
// Author a RawSql from a bare string — the string constructor is private, so
// raw DDL cannot enter the funnel without the rawSql(cap, ...) authority.
pgddl::RawSql probe() {
  return pgddl::RawSql(std::string("DROP TABLE postings;"));
}

#elif defined(PROBE_APPEND_STRING)
// Append raw text to a RawSql — the only combiner is RawSql + RawSql; there is
// no string-taking overload, so raw text cannot be spliced into an authored
// value.
pgddl::RawSql probe(pgddl::RawSql a) {
  return a + std::string("; DROP TABLE x;");
}

#elif defined(PROBE_APPEND_CHARPTR)
// Same, via a string literal — still no matching operator+.
pgddl::RawSql probe(pgddl::RawSql a) { return a + "; DROP TABLE x;"; }

#elif defined(PROBE_RAW_EXTRACT)
// Extract the raw bytes outside a reviewed sink — bytes() is private,
// befriended only to printPostgres + emitPostgresProject +
// materializePostgresPackageArtifacts.
const std::string &probe(pgddl::RawSql a) { return a.bytes(); }

#elif defined(PROBE_PACKAGE_UNREGISTERED_EXTRACT)
// : the backend-package sink is befriended as ONE EXACT SYMBOL
// (neutrino::materializePostgresPackageArtifacts). A DIFFERENT function in the
// same package -- even one whose name and signature closely resemble the
// registered sink -- still cannot reach the private bytes(). This is what keeps
// the third sink a single named entry rather than a package-wide grant.
namespace neutrino {
std::vector<std::pair<std::string, std::string>>
materializePostgresPackageArtifactsUnregistered(
    const projection::BackendProjectionGraph &, pgddl::RawSql a) {
  return {{"schema.sql", a.bytes()}};
}
} // namespace neutrino

#elif defined(PROBE_CAP_FORGE)
// Mint the authoring capability via forge() — it is a private static,
// befriended only to the reviewed authoring entries.
pgddl::RawSql probe() {
  return pgddl::rawSql(pgddl::DdlCap::forge(), "DROP TABLE postings;");
}

#elif defined(PROBE_CAP_CTOR)
// Forge the capability by constructing it directly — the ctor is private (and
// user-provided, so `DdlCap{}` cannot bypass it via aggregate-init).
pgddl::RawSql probe() {
  pgddl::DdlCap c;
  return pgddl::rawSql(c, "DROP TABLE postings;");
}

#else
#error "pg_rawsql_sealed.cpp must be compiled with a -DPROBE_* selector"
#endif
