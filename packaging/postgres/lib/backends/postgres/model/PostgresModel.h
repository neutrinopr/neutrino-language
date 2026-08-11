//===- PostgresModel.h - typed PostgreSQL legalization model -------------===//
//
// The PostgreSQL adapter consumes only the verified BackendProjectionGraph.
// Projection traversal materializes typed target idioms and the SQL sink lays
// them out. No backend entry reads the CoordinationPlan, capability spec, L2
// input, or any alternate semantic authority. The coordination constructs are
// TYPED shapes
// (Raise/Assign/If/FlatIf/StatusWrite, the LedgerUpsert/PostingInsert effect
// DML, typed params, reviewed M-of-N quorum guard, and comments). No production
// path can author the legacy verbatim Line kind; every emitted leaf has a typed
// factory and syntax owned below the model boundary.
// Backend-internal seam header: consumes only the typed coordination leaf,
// never View.h.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_POSTGRES_POSTGRESMODEL_H
#define NEUTRINO_BACKENDS_POSTGRES_POSTGRESMODEL_H

#include "Neutrino/BackendProjection.h"

#include "PgSqlText.h" // pgddl::RawSql / DdlCap — the  slice-2 DDL funnel

#include <algorithm>
#include <array>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

namespace neutrino {
namespace postgres_model {

// Shared fail-closed projection boundary used by the public ABI wrapper and
// graph materializer; the single implementation preserves the throw ratchet.
[[noreturn]] void fail(const char *code, const std::string &message);

struct PgProcedure;
struct PgFunction;

//  G1-S1: the generated (mode, role) -> atom status accessor — the ONLY
// reader of the Postgres coordination_status atoms. The legalizer passes the
// PROJECTED `ExecutionMode` and `LifecycleRole` it consumed from the verified
// `BackendProjectionGraph`; this maps that pair to the column atom via the
// generated `NEU_PG_STATUS_ATOM` table. The atom NEVER appears inline in a
// legalizer body, and the table can neither SELECT nor CHANGE a role — an
// unmapped pair fails closed (caught by the byte-goldens).
inline std::string pgStatusAtom(projection::ExecutionMode mode,
                                projection::LifecycleRole role) {
  using projection::ExecutionMode;
  using projection::LifecycleRole;
  struct Binding {
    ExecutionMode mode;
    LifecycleRole role;
    const char *atom;
  };
  static constexpr std::array<Binding, 4> bindings = {{
#define NEU_PG_STATUS_ATOM(ModeSym, RoleSym, Atom)                             \
  {ExecutionMode::ModeSym, LifecycleRole::RoleSym, Atom},
#include "PostgresTargetEnums.inc"
#undef NEU_PG_STATUS_ATOM
  }};
  const auto binding =
      std::find_if(bindings.begin(), bindings.end(), [&](const Binding &item) {
        return item.mode == mode && item.role == role;
      });
  return binding == bindings.end() ? "<unmapped-status-atom>" : binding->atom;
}

// Closed carrier for top-level schema declarations. It is deliberately
// disjoint from PgStmt, so a schema node cannot inhabit PgFunction::body.
// Kinds and factories are added only when their corresponding handwritten
// schema declarations are retired.
struct PgSchemaDecl {
  enum class Kind {
#define NEU_PG_PGSCHEMADECL_NODE(Sym, Ordinal, Handler, IsLeaf, Feature)       \
  Sym = Ordinal,
#include "PostgresTargetNodes.inc"
    Count
  };

  const Kind kind;
  const std::vector<std::string> operands;

  static PgSchemaDecl authorizedObserverTable() {
    return PgSchemaDecl(Kind::AuthorizedObserverTable, {});
  }
  static PgSchemaDecl coordinationStatusTable() {
    return PgSchemaDecl(Kind::CoordinationStatusTable, {});
  }
  static PgSchemaDecl ledgerBalanceTable() {
    return PgSchemaDecl(Kind::LedgerBalanceTable, {});
  }
  static PgSchemaDecl postingIdempotencyTable() {
    return PgSchemaDecl(Kind::PostingIdempotencyTable, {});
  }
  static PgSchemaDecl committedGroupTable() {
    return PgSchemaDecl(Kind::CommittedGroupTable, {});
  }
  // The effectful postings table, in its base and memo-column variants. The
  // caller selects the variant from the already-decided memo presence; the two
  // are distinct fixed schema kinds, so the memo decision never enters the
  // `.td`.
  static PgSchemaDecl postingsTable() {
    return PgSchemaDecl(Kind::PostingsTable, {});
  }
  static PgSchemaDecl postingsWithMemoTable() {
    return PgSchemaDecl(Kind::PostingsWithMemoTable, {});
  }
  static PgSchemaDecl keyClaimTable() {
    return PgSchemaDecl(Kind::KeyClaimTable, {});
  }
  static PgSchemaDecl quorumAcceptanceTable() {
    return PgSchemaDecl(Kind::QuorumAcceptanceTable, {});
  }
  static PgSchemaDecl temporalQuorumAcceptanceTable() {
    return PgSchemaDecl(Kind::TemporalQuorumAcceptanceTable, {});
  }
  //  B3: the  temporal-shape +  upgrade preflights as typed
  // instantiations of generated printer nodes (byte-exact DO $$ text in .td).
  static PgSchemaDecl quorumAcceptanceTemporalPreflight() {
    return PgSchemaDecl(Kind::QuorumAcceptanceTemporalPreflight, {});
  }
  static PgSchemaDecl committedGroupPreflight() {
    return PgSchemaDecl(Kind::CommittedGroupPreflight, {});
  }
  static PgSchemaDecl keyClaimPreflight() {
    return PgSchemaDecl(Kind::KeyClaimPreflight, {});
  }
  static PgSchemaDecl quorumAcceptanceUpgradePreflight() {
    return PgSchemaDecl(Kind::QuorumAcceptanceUpgradePreflight, {});
  }

private:
  PgSchemaDecl(Kind k, std::vector<std::string> ops)
      : kind(k), operands(std::move(ops)) {}
};

// One legalized PL/pgSQL statement. The coordination constructs are TYPED
// shapes — a `Raise` is the fail-closed revert, an `Assign` is a compute write,
// an `If`/`FlatIf` is a guarded block, a `StatusWrite` is the
// coordination_status lifecycle transition, a `LedgerUpsert`/`PostingInsert` is
// an effect DML write. The operand/predicate text inside a shape is already
// lowered (operand SQL / toSql / guardToSql) and carried verbatim; this is not
// a SQL AST. The retired `Line` enum value remains only for ordinal stability
// and is rejected by the canonical constructor.
struct PgStmt {
  // The statement kinds are GENERATED from PostgresTargetNodes.td (): the
  // `.td` is the single source of truth, expanded here into the enum (Ordinal
  // fixes each value, kept identical to the pre-migration hand-written enum so
  // the PostgreSQL byte-goldens are unchanged). check_target_node_registry.py
  // reconciles this registry with the generated typed-tree traversal + printer.
  enum class Kind {
#define NEU_PG_PGSTMT_NODE(Sym, Ordinal, Handler, IsLeaf, Feature)             \
  Sym = Ordinal,
#include "PostgresTargetNodes.inc"
  };
  // ENCAPSULATED ( slice 1, mirroring SolStmt/): the fields are
  // public-READABLE but `const`, and the constructor is private, so a PgStmt is
  // IMMUTABLE and NOT an aggregate. External code therefore cannot author a raw
  // Line by a `{Kind::Line, …}` aggregate-init or by field mutation
  // (`s.kind = …` / `s.text = …`) — both are compile errors. The ONLY
  // construction paths are the TYPED factories below (fixed shapes with
  // already-lowered field values, not raw pass-through text). The raw Line
  // authoring seam is absent at the  endpoint.
  const Kind kind;
  const std::string
      text;              // Line: statement; Raise: message; Assign: target
                         // var; If/FlatIf: condition; StatusWrite: status field
  const std::string aux; // Raise: RAISE format arg; Assign: expression;
                         // StatusWrite: the procedure literal
  const std::string aux2; // StatusWrite: the p_<key> reference
  const bool flag;        // StatusWrite: true = DO UPDATE, false = DO NOTHING
  const std::vector<PgStmt> body;       // If/FlatIf children
  const std::vector<std::string> parts; // LedgerUpsert / PostingInsert operands
  // The ordered, already-lowered field values a GENERATED printer handler
  // projects by ordinal (, arity-generic). A migrated typed-.td node
  // (ProgressFlag) carries its operands here; fixed renderer-adapter kinds
  // retain their existing typed carrier fields and are selected by the
  // schema-generated traversal.
  const std::vector<std::string> operands;
  // The repeated per-item tuples a GENERATED framed-lines printer handler
  // projects — one already-lowered tuple per rendered item line (). Read by
  // the generated `resolveGroups` bridge; the scalar-only kinds leave it empty.
  const std::vector<std::vector<std::string>> group;

  //  B1: Blank/Raise/Assign/StatusWrite declarations and construction
  // bodies are generated from RecipeFactoryNode records. StatusWrite retains
  // the typed `(proc, key, field, doUpdate)` carrier for its fixed INSERT +
  // ON CONFLICT spelling. The include is public so existing typed callers keep
  // their stable API while the constructor stays private and no handwritten
  // factory body remains.
#include "PostgresRecipeBuilders.decl.inc"
  // The temporal-accept `quorum_acceptance` INSERT (): the temporal-rail
  // sibling of quorumAcceptInsert. The FIXED two-line statement (header /
  // VALUES) migrated off the raw pgLine seam into a generated typed-.td `lines`
  // node. `proc`/`key` are the already-lowered VALUES operands; `p_policy`,
  // `p_canonical_claim_hash`, `p_execution_claim` and the nested observer-count
  // subquery are literal template text owned by PostgresTargetNodes.td, and the
  // whole INSERT framing is rendered by the shared generated printer driver.

  //  common callable construction is generated from the real target-node
  // schema: CallableSig carries its scalar/list operands, DeclareSection its
  // repeated declaration tuples, CallableBody its typed children, and
  // CallableClose its fixed zero-field shape. The generated builder reaches
  // the private constructor below; no handwritten factory or alternate path
  // remains here.

  // Construction-level endpoint guard. Kind::Line is the retired legacy kind
  // that represented arbitrary verbatim statement text; it is rejected by enum
  // value regardless of spelling or caller.
  static void ensureAuthorable(Kind k);

  // Non-authoring test witness for the ACTUAL canonical constructor path. It
  // accepts only a kind and returns only whether construction rejected it: no
  // PgStmt, operands, text, or private-constructor authority can escape.
  static bool rejectsAtConstructionForTest(Kind k);

private:
  PgStmt(Kind k, std::string t, std::string a, std::string a2, bool fl,
         std::vector<PgStmt> b, std::vector<std::string> p,
         std::vector<std::string> ops = {},
         std::vector<std::vector<std::string>> grp = {})
      : kind((ensureAuthorable(k), k)), text(std::move(t)), aux(std::move(a)),
        aux2(std::move(a2)), flag(fl), body(std::move(b)), parts(std::move(p)),
        operands(std::move(ops)), group(std::move(grp)) {}
};

// One `p_<name> <type>` PL/pgSQL parameter; the p_-prefixed name and the SQL
// type are structured so legalization can inspect/extend them.
struct PgParam {
  std::string name; // already p_-prefixed
  std::string type; // lowered SQL type (bigint / text / text[])
  // The `p_<name> <type>` rendering is TableGen-owned (): the CallableSig
  // node space-joins the [name, type] tuple, so there is no local render().
};

// One already-legalized PL/pgSQL declaration. Target decisions populate these
// operands directly; DeclareSection owns their exact rendering.
struct PgDeclaration {
  std::string name;
  std::string type;
  std::string initializer; // empty when the declaration has no initializer
};

// A legalized PL/pgSQL function: name + typed params + an optional DECLARE
// section + a typed-statement body.
struct PgFunction {
  std::string name;
  std::vector<PgParam> params;
  bool declare = false;
  std::vector<PgDeclaration> declarations;
  std::vector<PgStmt> body;
};

// One complete callable root produced by the closed recipe grammar. Its parts
// are the generated signature, optional declaration section, body, and close
// nodes in recipe order.
struct PgCallableRoot {
  std::vector<PgStmt> parts;
};

struct PgProcedureHeader {
  std::vector<std::string> lines;
};

struct PgProcedureSeparator {};

struct PgProcedureRevoke {
  pgddl::RawSql sql;
};

using PgProcedurePart = std::variant<PgProcedureHeader, PgCallableRoot,
                                     PgProcedureSeparator, PgProcedureRevoke>;

// The materialized PostgreSQL procedure. Every field comes from projection
// traversal and target idioms. The closed recipe grammar owns the complete
// ordered root; the renderer only traverses its typed parts.
struct PgProcedure {
  bool evidenceOnly = false;
  bool gated = false; // quorum-gated (vs legacy self-attest)
  std::vector<PgProcedurePart> root;
};

// Materialize the already-verified projection into closed PostgreSQL idioms.
// This boundary cannot read or reconstruct source coordination.
PgProcedure materializePostgresProjection(
    const projection::BackendProjectionGraph &projection);

// Render a materialized model to procedure.sql — layout only.
std::string renderPostgresProjection(const PgProcedure &model);

// Render one typed top-level schema declaration through the governed generated
// printer. The caller retains declaration selection and composition order; the
// DdlCap/RawSql boundary remains the only schema-text authority funnel.
pgddl::RawSql renderSchemaDecl(const pgddl::DdlCap &cap,
                               const PgSchemaDecl &declaration);

// The M-of-N quorum acceptance-guard schema DDL (accept-guard tables) — emitted
// only when the projection is attestation-gated; reviewed reference DDL kept
// verbatim (). A fail-closed RawSql ( slice 2); the DdlCap proves an
// authorized caller.
pgddl::RawSql
materializePostgresSchema(const pgddl::DdlCap &cap,
                          const projection::BackendProjectionGraph &projection);

} // namespace postgres_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_POSTGRES_POSTGRESMODEL_H
