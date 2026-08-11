//===- PostgresRecipeProvider.h - roled PostgreSQL from-spec seam --------===//
//
// Backend-internal  seam. The public from-spec ABI wrappers hydrate the
// verified BackendProjectionGraph and dispatch to the roled provider that owns
// the target-node composition, so the from-spec adapter itself holds no tracked
// construction. The PostgreSQL analog of the merged Solidity  disposition.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_POSTGRES_POSTGRESRECIPEPROVIDER_H
#define NEUTRINO_BACKENDS_POSTGRES_POSTGRESRECIPEPROVIDER_H

#include "PostgresModel.h"

namespace neutrino {
namespace postgres_model {

// The procedure projection: materializes the verified graph into typed idioms
// and renders procedure.sql. Lives in the recipe-provider (the roled provider
// plumbing) so the from-spec ABI adapter holds no tracked construction.
std::string materializePostgresProcedureArtifact(
    const projection::BackendProjectionGraph &projection);

// The quorum-acceptance schema projection: dispatches the verified graph to the
// schema materializer behind the DdlCap authority. Same roled-provider seam.
pgddl::RawSql materializePostgresQuorumSchemaArtifact(
    const pgddl::DdlCap &cap,
    const projection::BackendProjectionGraph &projection);

} // namespace postgres_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_POSTGRES_POSTGRESRECIPEPROVIDER_H
