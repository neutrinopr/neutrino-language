# Extraction manifest — NeutrinoBackendPostgres (`lib/backends/postgres`)

M5 extraction Track A (/): the self-contained PostgreSQL backend unit, ready for an M6 git-subtree split with
no further reorganization. It links ONLY the shared bottom leaves (below) — no ProcedureView, no sibling
backend — so the target graph itself proves the boundary (the link-smoke).

The lists below are machine-checked against the CMake/link graph by
[`scripts/gates/check_extraction_manifests.py`](../../../scripts/gates/check_extraction_manifests.py): declared Sources ==
the module's CMake sources + its link-smoke, Leaf dependencies == its `LINK_LIBS PUBLIC`, and every
declared public header exists. A drift between this manifest and `CMakeLists.txt` fails CI.

R4a (): sources are organized into package-role subdirs — `recipes/` (idiom
recipe `.td`), `model/` (`PostgresTargetNodes.td` + its generated node-registry
`.inc`), `generated/` (recipe builder/adapter `.inc`), `provider/` (recipe
provider + typed model/renderer), `leaf/` (below-waist SQL text/syntax leaf),
`harness/` (the role-authenticated DB-test). The public spec entry
(`GenPostgresSpec.cpp`) and the reviewed `CoordinationEnvelope.sql.inc` stay at the
unit root; `test/` is unchanged.

## Sources owned
- GenPostgresSpec.cpp
- CoordinationEnvelope.sql.inc
- generated/PostgresTargetNodes.inc
- generated/PostgresTargetEnums.inc
- generated/PostgresPrinterHandlers.inc
- generated/PostgresRecipeBuilders.inc
- generated/PostgresRecipeBuilders.decl.inc
- generated/PostgresRecipeAdapter.inc
- generated/PostgresProjection.inc
- generated/PgDdlBuilders.inc
- provider/PostgresRecipePackage.inc
- provider/PostgresSpecModel.cpp
- model/PostgresModel.cpp
- provider/PostgresRecipeProvider.cpp
- leaf/PgSqlText.cpp
- leaf/PgSqlSyntax.cpp
- harness/PostgresDbTest.cpp
- test/backend_postgres_smoke.cpp
- test/postgres_model_test.cpp
- test/postgres_recipe_resolution_test.cpp
- test/postgres_stmt_shell_render_harness.cpp
- test/postgres_effect_render_driver.cpp
- test/postgres_projection_referee_test.cpp

The `PgStmt::Kind` enum and the first generated printer handler are GENERATED (//)
from `PostgresTargetNodes.td` (the source of truth, using the shared `lib/backends/TargetPrinter.td`
schema) into the committed `PostgresTargetNodes.inc` and `PostgresPrinterHandlers.inc` by
[`scripts/generators/gen_target_node_registry.py`](../../../scripts/generators/gen_target_node_registry.py),
reconciled against the generated + remaining handwritten `addStmt` dispatch by
[`scripts/gates/check_target_node_registry.py`](../../../scripts/gates/check_target_node_registry.py).
The migrated node is `ProgressFlag` (`v_progress := <bool>;`); the other kinds stay handwritten
dispatch during the partial migration. The `.td` is not a compiled/linked source (it is a TableGen
schema over the pinned llvm-tblgen); the backend stays MLIR-free and leaf-only.

Internal (non-public) headers: PostgresSpecInternal.h — the decode/db-test seam; PostgresModel.h — the
typed procedure+schema legalization model () behind the unchanged public entry points;
PostgresRecipeProvider.h — the roled from-spec seam the public ABI dispatches to ( R4d), so the adapter
holds no tracked construction; PgSqlText.h — the
below-waist raw PL/pgSQL text authority (, the sole `sql::Stmt::line` friend + the `Seam` capability);
PgSqlSyntax.h — the below-waist SQL-syntax leaf (the StringRef-only escaper/quoter).

## Shared leaf dependencies
- NeutrinoSpecContract
- NeutrinoCodeText
- NeutrinoRecipe

## Public headers
- Neutrino/GenPostgresSpec.h
- Neutrino/PgDdl.h

## Integration headers
- Neutrino/RecipeRuntime.h
- Neutrino/RecipeSessionStore.h

## Conformance slice
- `backend-postgres-smoke` — the leaf-only link-smoke (`test/`)
- `postgres-model-test` — the typed-legalization-model unit test (structure + single source, `test/`)
- `postgres-progressflag-golden` / `postgres-progressflag-td-mutation` — the  `.td`->generated->golden
  proof: one render harness (`test/postgres_stmt_shell_render_harness.cpp`) compiled against the committed
  printer include reproduces the byte-faithful golden line (`v_progress := false;` in
  `test/progress_flag_golden.sql`), and against a `.td`-mutated regenerated include (real generator + pinned
  llvm-tblgen, `:=`->`::=`) renders the mutated form and fails it (`test/`)
- `postgres-effectledgercomment-golden` / `-td-mutation` / `-real-path-mutation` — the  C1 proof for the
  per-effect ledger comment (`EffectLedgerComment`, the last executable `pgLine` site retired): the shell harness
  (`test/postgres_stmt_shell_render_harness.cpp`) is the focused handler unit; the GOVERNING witness
  (`test/postgres_effect_render_driver.cpp`) runs the real `planFromSpec`->`generatePostgresProcedureFromSpec`
  path (legalization + factory + printer) on a real effectful spec, built twice — the committed backend, and a
  build-time copy of `PostgresModel.cpp` whose only delta is the include repointed at a `.td`-mutated file
  (real generator + pinned llvm-tblgen, `(${ledger})`->`{${ledger}}`) — so the mutation changes production bytes
  through the real path (`test/`)
- `postgres-idempotencyguardcomment-golden` / `-td-mutation` / `-real-path-mutation` — the  C2 proof for the
  fixed zero-operand `IdempotencyGuardComment`: the shared shell harness pins the exact comment bytes, while the
  real-path pair recompiles a test-only `PostgresModel.cpp` copy against a TableGen-mutated handler and proves the
  production legalization/factory/print path adopts that mutation (`test/`)
- `postgres-balancedinvariantcomment-golden` / `-td-mutation` / `-real-path-mutation` — the  C3 proof for the
  final fixed zero-operand `BalancedInvariantComment`: the handler pair pins and mutates the exact banner, while the
  production-path pair proves the real balanced legalization decision consumes the generated `.td` syntax. C3 also
  deletes `pgLine`, `PgStmt::rawLine`, `RawCap`, and `PgStmt::Impl`; the canonical constructor rejects the retired
  `Kind::Line` value, leaving an explicit zero raw-statement-authority endpoint (`test/`)
- `anti-inference-boundary` — the  S4 gate: `PostgresModel.cpp` legalizes off the normalized CoordinationPlan
  () and reintroduces no raw-spec semantic inference (semantics normalize once; targets legalize; CodeText prints)
- `test/ir/backend/postgres_goldens.test` — the `[81]` byte-golden procedure + harness
- `test/ir/backend/postgres_from_spec.test`, `test/ir/legality/postgres_legality.test`
- `test/ir/oracle/oracle_delivery.neu` — the S2d quorum-guard gating + `test/backend-guard/oracle_delivery/`

## Non-ownership (explicit)
- Does NOT own the registry ENTRY (lib/targets/PostgresTarget.cpp) — it stays in `NeutrinoEmit` (it needs the spec producer +
  `realize()`), the aggregator that folds the view→spec→renderer call.
- Does NOT own the `include/Neutrino/` directory — it EXPOSES only its own headers (above); the shared
  contract/adapter headers are the leaves'.
- Does NOT own domain byte-goldens (`examples/domains/*/generated/`) — the shared conformance corpus.
- Does NOT own cross-cutting gates (`scripts/check_*`, the lit non-vacuous manifest, the root CMake).

> ** — generated `.inc` are BUILD PRODUCTS.** The artifacts marked above are
> no longer committed. They are produced into
> `${CMAKE_CURRENT_BINARY_DIR}/generated`, which is on the unit's private
> include path, so in-package `#include`s resolve unchanged. An extraction must
> carry the `.td` sources and the generator, not the `.inc`: the artifact is
> reproducible from them and byte-identical regeneration is what proves the
> extraction preserved semantics. A source-tree copy reappearing is a defect,
> not a fallback.
