//===- PostgresIdiomRecipes.td -  PostgreSQL recipe package root -------===//
//
// The PostgreSQL backend-idiom recipe package. It includes the  closed
// meta-model (BackendIdiom.td) and the stackable evidence recipe fragment
// (). The recipe generator (gen_backend_idiom_recipes.py --symbol postgres)
// consumes this root to emit the postgres recipe module (postgres_recipes.inc);
// the recipe builder generator (gen_recipe_builders.py) consumes it to emit the
// concrete node-construction adapter (PostgresRecipeBuilders.inc). This is the
// first REAL PostgreSQL resolver-reachable recipe package — it owns the provider
// registration/discovery the  shape/builder bootstrap deferred.
//
//===----------------------------------------------------------------------===//

include "BackendIdiom.td"
include "postgres/recipes/PostgresEvidenceIdiomRecipes.td"
include "postgres/recipes/PostgresTemporalIdiomRecipes.td"
include "postgres/recipes/PostgresSchemaIdiomRecipes.td"
include "postgres/recipes/PostgresEffectfulIdiomRecipes.td"

// : the PostgreSQL raw -> SQL-literal-safe escape leaf hook (
// string.escape). The effectful/temporal ledger-upsert + posting-insert nodes
// bind their raw procedure / ledger / entry / memo operands through this hook
// (Hook<> bindings); the provider's applyHook runs postgres_detail::sqlEsc. The
// decorative effect-ledger comment keeps the RAW spellings (Direct bindings).
def PgStringEscapeHook : RegisterLeafHook<
    "postgres.string.escape", HookStringEscape, "postgresEscapeString">;
