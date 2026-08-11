#ifndef NEUTRINO_POSTGRES_PACKAGE_ARTIFACTS_H
#define NEUTRINO_POSTGRES_PACKAGE_ARTIFACTS_H

#include "Neutrino/PgDdl.h"

#include <string>
#include <utility>
#include <vector>

// The package-owned artifact boundary used by the external protocol entry.
// `materializePostgresPackageArtifacts` itself is declared in PgDdl.h, because
// that is where it must be befriended as an exact symbol; this header exists so
// the protocol entry can call it without re-declaring the signature.
//
// The entry receives already-extracted bytes: it is NOT a friend of RawSql, so
// the  extraction authority stays pinned to one named function.

namespace neutrino {

// The package-owned artifact boundary, the analogue of SoliditySourceFile. It
// deliberately names no compiler plan, scenario, or source representation.
struct PostgresSourceFile {
  std::string path;
  std::string content;
};

} // namespace neutrino

#endif // NEUTRINO_POSTGRES_PACKAGE_ARTIFACTS_H
