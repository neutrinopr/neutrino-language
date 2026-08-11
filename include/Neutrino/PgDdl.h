//===- PgDdl.h - the fail-closed PostgreSQL raw-DDL value type ( s2) --===//
//
// `pgddl::RawSql` is the "channel 2" DDL/schema analogue of the below-waist
// pgtext funnel: the schema / preflight / revoke builders author it, and the
// project emitter sinks it to the .sql/.sh files. It crosses the leaf ->
// registry boundary (the leaf's public schema entry returns it, and
// emitPostgresProject consumes it), so it lives on the public include path. It
// is SYNTAX-ONLY: it holds already-lowered SQL text and reads no model — it
// merely forward-declares (opaque, never includes) the reviewed authoring/sink
// entries it befriends.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_PGDDL_H
#define NEUTRINO_PGDDL_H

#include <string>
#include <utility>
#include <vector>

namespace neutrino {
// The reviewed DDL/schema authoring + sink entries, forward-declared
// (layout-only — opaque, no model/view surface is INCLUDED, so the below-waist
// boundary holds) so the RawSql capability/extractor can befriend exactly them.
struct CoordinationPlan;
class ProcedureView;
struct Scenario;
namespace projection {
struct BackendProjectionGraph;
} // namespace projection
namespace postgres_model {
struct PgProcedure;
std::string renderPostgresProjection(
    const PgProcedure &); // traverses completed recipe root
PgProcedure materializePostgresProjection(
    const projection::BackendProjectionGraph &); // authors revoke trailer
} // namespace postgres_model
std::vector<std::string>
emitPostgresProject(const ProcedureView &, const Scenario &,
                    const std::string &,
                    const CoordinationPlan &); // authors+sinks

// / backend-package sink. The extracted PostgreSQL package's artifact
// materializer: the reviewed sink the  boundary mandates, since the ADR
// assigns schema/procedure/reconciliation.sql to the package rather than the
// core. Declared with a plain return type so this header needs no package
// header, and befriended as this EXACT symbol -- not the protocol entry, not a
// namespace, not a generic accessor.
//
// TRANSITIONAL: this is the THIRD sink only while the legacy in-core project
// emitter still exists. When `emitPostgresProject` retires with the in-core
// PostgreSQL target registry entry (/), its friend declarations here
// AND its registration in scripts/gates/check_pg_channel2_authority.py must
// retire with it, returning the sink count to two.
std::vector<std::pair<std::string, std::string>>
materializePostgresPackageArtifacts(
    const ::neutrino::projection::BackendProjectionGraph &);
} // namespace neutrino

namespace neutrino::pgddl {

// The DDL/schema authoring capability ( slice 2 — the "channel 2" DDL
// analogue of pgtext::Seam). Private ctor; minted ONLY by `forge`, which is
// befriended ONLY to the reviewed authoring entries (projection materialization
// authors the accept_ REVOKE trailer; emitPostgresProject authors the schema +
// wraps
// the project files). A rogue cannot name a way to construct a DdlCap.
class DdlCap {
  DdlCap() {}
  static DdlCap forge();
  friend ::neutrino::postgres_model::PgProcedure(
      ::neutrino::postgres_model::materializePostgresProjection)(
      const ::neutrino::projection::BackendProjectionGraph &);
  friend std::vector<std::string>(::neutrino::emitPostgresProject)(
      const ::neutrino::ProcedureView &, const ::neutrino::Scenario &,
      const std::string &, const ::neutrino::CoordinationPlan &);
  friend std::vector<std::pair<std::string, std::string>>(
      ::neutrino::materializePostgresPackageArtifacts)(
      const ::neutrino::projection::BackendProjectionGraph &);
};

// A fail-closed raw DDL/schema SQL value. IMMUTABLE and OPAQUE:
//   * no public string constructor — a `RawSql` cannot be built from a bare
//     std::string / char*; the ONLY author is `rawSql(cap, text)`, which
//     demands an un-forgeable DdlCap;
//   * no string-append escape — the ONLY combiner is `RawSql + RawSql` (both
//     operands already authored); there is no `operator+`/append taking a
//     string;
//   * no mutable raw accessor — the raw bytes are reachable ONLY through the
//     PRIVATE `bytes()`, befriended to the three reviewed sinks (the projection
//     renderer for the revoke trailer, emitPostgresProject for file writes). No
//     other TU can extract the raw SQL.
class RawSql {
  std::string sql_;
  explicit RawSql(std::string s) : sql_(std::move(s)) {}
  const std::string &bytes() const { return sql_; } // sole (gated) extraction

  friend RawSql rawSql(const DdlCap &, std::string);
  friend RawSql operator+(const RawSql &, const RawSql &);
  friend std::string(::neutrino::postgres_model::renderPostgresProjection)(
      const ::neutrino::postgres_model::PgProcedure &);
  friend std::vector<std::string>(::neutrino::emitPostgresProject)(
      const ::neutrino::ProcedureView &, const ::neutrino::Scenario &,
      const std::string &, const ::neutrino::CoordinationPlan &);
  friend std::vector<std::pair<std::string, std::string>>(
      ::neutrino::materializePostgresPackageArtifacts)(
      const ::neutrino::projection::BackendProjectionGraph &);

public:
  RawSql(const RawSql &) = default;
  RawSql(RawSql &&) = default;
  RawSql &operator=(const RawSql &) = default;
  RawSql &operator=(RawSql &&) = default;
};

// The SOLE author of a RawSql: frames already-lowered/literal DDL text into the
// typed value. Demands a DdlCap, so no un-capped TU can author raw DDL.
RawSql rawSql(const DdlCap &, std::string text);

// The SOLE combiner: concatenate two already-authored RawSql values. There is
// no string-taking overload, so raw text cannot be appended into a RawSql.
RawSql operator+(const RawSql &, const RawSql &);

} // namespace neutrino::pgddl

#endif // NEUTRINO_PGDDL_H
