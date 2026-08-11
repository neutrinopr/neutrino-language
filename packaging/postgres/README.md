# NeutrinoBackendPostgres — standalone package candidate ()

**Status: clean-clone engineering unblocked; publication gated on .** This directory is the M7 open-core S3b
() evidence that the PostgreSQL backend is a *separately ownable* package —
an exact extraction manifest plus a standalone build/install skeleton plus a
fail-closed reach-back audit. The final clean-clone configure/build/test/package
run against a fresh checkout is performed by a **separate PR**, not here.

**Current state:**  and the SHARED  schema/startup/discovery prerequisites LANDED ( itself remains open; the PostgreSQL package moves — PgDdl.h to package-internal and the recipe-runtime relocation — are pending work for the second  clean-clone PR); the clean-clone execution is a separate, second  PR; publication and license ratification remain gated on .

Parent: . Boundary: [`docs/process/M7_BACKEND_PACKAGE_BOUNDARY_ADR.md`](../../docs/process/M7_BACKEND_PACKAGE_BOUNDARY_ADR.md) (, signed). In-tree source of truth: [`lib/backends/postgres/EXTRACTION.md`](../../lib/backends/postgres/EXTRACTION.md).

## Contents

| File | Purpose |
|---|---|
| `extraction-manifest.json` | The **exact** machine-readable extraction inventory: compiled sources, generated `.inc` build products (each with its generator + `.td` input), TableGen inputs, public vs internal headers, tests/fixtures/goldens, shared-leaf link deps, the  public-core contract, and license/provenance. Derived from `EXTRACTION.md`, reconciled with the live CMake graph. |
| `scripts/check_package_reachback.py` | **Fail-closed** reach-back audit. Manifest-driven: proves every `#include` in every owned file resolves to the package's own headers/`.inc` or a **declared** public-core / package-internal header — anything else (a sibling backend header, an undeclared `Neutrino/…`, a path that escapes the unit) fails closed. Mirrors `scripts/gates/check_extraction_boundaries.py`. |
| `scripts/check_standalone_configure.sh` | Focused **standalone-configure** check: proves `packaging/postgres/CMakeLists.txt` still configures as a self-contained CMake project (core stubbed, pinned `llvm-tblgen`, every generated-`.inc` build step declared). |
| `CMakeLists.txt` | Standalone package build/install **skeleton**. Regenerates every `.inc` as a **build product** from its `.td` (never a copied source), builds `NeutrinoBackendPostgres` against an installed public core, and adds the `install(EXPORT)` surface that does not exist in-tree. Not `add_subdirectory()`'d by the root — it does not touch the in-tree build. |
| `cmake/NeutrinoBackendPostgresConfig.cmake.in` | The installed-package `find_package(NeutrinoBackendPostgres)` config. |

## Generated `.inc` are build products, never copied sources

Every file under `lib/backends/postgres/generated/` is a **build product** —
regenerated from a `.td` source of truth by a pinned-`llvm-tblgen` generator
(`gen_target_node_registry.py` / `backend_recipe_gen.py` /
`gen_backend_idiom_recipes.py`). The package's contract is the `.td`, not the
`.inc`. The skeleton reproduces each generator invocation into the build tree;
a clean clone does not vendor the committed bytes as authored source. (The
committed in-tree copies exist only as a byte-check convenience; removing even
that is 's job and is **out of scope here**.)

## Public-core dependency contract ()

Under the signed boundary the core ↔ backend integration is a **versioned
subprocess protocol** over a serialized canonical artifact — bytes, not
LLVM/C++ types:

- **Canonical artifact:** `neutrino.finalized-projection/1` — a lossless
  serialization of `BackendProjectionGraph` (`kProjectionSchemaVersion = 5`),
  canonical JSON. Schema `docs/schemas/finalized-projection-v1.schema.json` is
  delivered by the landed shared schema/startup/discovery prerequisites;  itself remains open.
- **Protocol:** `neutrino.backend-protocol/1` (length-framed request/result/error
  over stdio; version negotiation + capability discovery).
- **Package descriptor:** `neutrino.backend-package/1` (target identity, protocol
  versions, target-profile identity, entry, closure `sha256`/`byteLen`,
  compatibility bounds, license identity, manifest digest).
- **Package-internal (never exported):** the C++/LLVM `TargetRecipeProvider`
  interface (`RecipeRuntime.h`) and the recipe runtime (`NeutrinoRecipe`) move
  **inside** the package (normative, ADR §5) — they are *not* a public-core
  dependency under the extracted model.
- **The package owns:** its harness artifacts (`schema.sql` / `procedure.sql` /
  `reconciliation.sql` / `run_db_test.sh`), target-profile realization, its six
   leaf hooks, and the  carve-out bodies (`CoordinationEnvelope.sql.inc`)
  pinned by the closure `sha256`.

The manifest records both the **current** in-tree link surface (the three shared
leaves) and this target boundary.

## Gate state

- ** SATISFIED** — the backend-free core installed export is pinned and machine-derived.
- ** seams LANDED via ** — `neutrino.backend-source-runtime/1` and
  `neutrino.backend-startup/1` are the real contracts this package builds and
  starts against.
- ** PENDING-RATIFICATION** — a publication/license gate ONLY. It does not
  stop reversible clean-clone engineering. No package is published and neither
  backend is declared licensed until  records its zero-unresolved-rights
  decision; `licenseIdentity` stays `pending-ratification-845`, never defaulted.

## Disjoint from

- **** (build-time `.inc` generation policy) — this manifest only
  *classifies* the generated `.inc` as build products; it does not remove the
  committed copies or rewire the in-tree gates.
- **** (core discovery seam) — this *records* the  contract; it does
  not implement the core seam or drop backend link edges.
- **** (core-only build + core export manifest) — this owns only the
  PostgreSQL backend surface.

## Verifying today

```
python3 packaging/postgres/scripts/check_package_reachback.py --selftest    # biting mutations
python3 packaging/postgres/scripts/check_package_reachback.py               # fail-closed reach-back audit
python3 packaging/postgres/scripts/emit_extraction_receipt.py --selftest    # biting mutations
python3 packaging/postgres/scripts/emit_extraction_receipt.py --check       # fail-closed receipt self-check
python3 packaging/postgres/scripts/emit_extraction_receipt.py               # emit the receipt to stdout
bash   packaging/postgres/scripts/check_standalone_configure.sh             # standalone-configure check
python3 -c "import json; json.load(open('packaging/postgres/extraction-manifest.json'))"
python3 scripts/gates/check_extraction_manifests.py                         # EXTRACTION.md honesty (postgres unit)
```

The reach-back audit and the extraction receipt are covered in the no-build PR tier by
`test/checks/fast/postgres_package_extraction_test.py` (`ctest -R fast-postgres-package-extraction`).

## Extraction receipt (`emit_extraction_receipt.py`, )

The **extraction receipt** is the content-addressed proof artifact  requires: source
identity (repo HEAD + the unit's last-touch revision), core identity (the  finalized-
projection artifact + backend protocol + pinned `COMPATIBILITY.json`), the public-core
dependency graph, per-file SHA-256 digests of every owned authored source / generated build
product / packaging file, the conformance-slice test set, and the license/provenance state.
It is **never timestamped**, so the same tree emits byte-identical bytes, and it is a build
PRODUCT (not committed) — the clean-clone execution (publication gated on ) emits it in the
fresh checkout and compares against the monorepo baseline. The owned-file set is exactly the
one `check_package_reachback.py` audits (imported, single source of truth) plus the TableGen
inputs and packaging files, so the receipt can never silently diverge from the reach-back
surface. `--check` fails closed if any owned file is missing, a declared public-core header
does not resolve, or the compatibility surface is absent. The license **identity** is the one
item explicitly `gated:845` (named, never silently defaulted); it is a tracked gate, not an
unresolved file.

The reach-back audit is **delimiter-aware**: a slashless name is a standard-library
header only in the angled form (`<string>`); a quoted `"X.h"` is a local include
that must be an owned/declared header. `--selftest` proves an undeclared quoted
local header is rejected (it is not waved through as stdlib).

The recipe runtime (`RecipeRuntime.h` / `TargetRecipeProvider` + `NeutrinoRecipe`)
is **bundled** as an OBJECT library (`nbp_recipe_runtime`, built from the
`lib/recipe` sources) whose objects are **folded into the backend archive**
(`$<TARGET_OBJECTS:>`) — it is not a linked or exported target, so the installed
targets surface exposes no recipe-runtime name (a private implementation detail
per  §5, not public package topology). It is **not** linked as
`Neutrino::Recipe` from the public core. The only public-core C++ link edges are
`Neutrino::SpecContract` + `Neutrino::CodeText`. `check_standalone_configure.sh`
asserts the emitted `NeutrinoBackendPostgresTargets.cmake` is backend-only.

## `PgDdl.h` disposition (resolved, )

`include/Neutrino/PgDdl.h` is a **postgres-owned public header**: per its banner
it crosses the leaf → registry boundary (the leaf's public schema entry returns
`pgddl::RawSql`; `emitPostgresProject` consumes it), and its only non-unit
includer is `lib/targets/PostgresTarget.cpp` (the registry entry). It is now
declared in `EXTRACTION.md` `## Public headers` and installed by the package.
Under the  boundary the registry entry retires for descriptor discovery and
project assembly moves inside the package, at which point `PgDdl.h` becomes
package-**internal** — `` executes that move.
