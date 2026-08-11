# Testing — tiers and entry points ()

The translator test surface is organized into three explicit tiers so CI can grow
without one shell script becoming the hidden test architecture. Each tier has a stable
entry point (a `make` target, a CTest label, and a CI job).

| Tier | Entry point | CTest | CI job | Needs | Time |
|------|-------------|-------|--------|-------|------|
| **fast** | `make test-fast` | `ctest -L fast` | `fast (no build)` | python3 only | ~seconds |
| **unit** | `make unittest` | `ctest -L unit` | `linux` / `macos` | C++ build + gtest | ~seconds |
| **ir** | `make ir-test` | `ctest -R ^lit` | `linux` / `macos` | C++ build + lit + FileCheck | ~seconds |
| **full** | `make test` (alias `make test-full`) | `ctest -LE 'umbrella\|fast\|golden\|s5f\|acceptance'` | `linux` / `macos` | C++/MLIR build + lit + FileCheck | ~2 min |
| **acceptance** | `make acceptance` / `make acceptance-suite` | `ctest -L acceptance` | provisioned CI + local | full + forge + docker | minutes |

## Pull-request CI budget and merge policy

Normal PR updates run only the no-build fast tier and changed-line formatting.

**Temporary hosted-budget mode:** while the GitHub-hosted Actions budget is
exhausted, a ready-for-review event or `ci:full` label runs only the native suite
on `[self-hosted, macOS, X64, translator-macbook]`. It does not start the hosted
Linux build, clang-tidy, release/package/image, oracle, wrapper, or compliance
jobs. A later commit removes `ci:full`, making the earlier macOS result visibly
stale and requiring the label to be applied again after the next batch of fixes.
The hosted Linux build matrix is paused; this is reduced platform coverage, not
Linux equivalence. Restore the hosted PR jobs and Linux matrix before the next
release-readiness gate or as soon as hosted budget is available.

This repository does **not** currently have a branch-protection ruleset or merge
queue, so there is no `merge_group` enforcement. Until one is configured, the
merge owner must verify that the final PR head has a green macOS `ci:full` run
before merging a code-changing PR during temporary hosted-budget mode. A commit
after that run invalidates the result and requires another `ci:full`. The full
workflows on `push: main` are a post-merge safety net only; they detect breakage
after landing and do not protect main.

The temporary macOS-only policy is itself the explicit owner-approved reduction
for the hosted spending-limit block. A queued/offline self-hosted macOS job is
still not green. Any merge without a green final-head macOS run needs a separate,
explicit emergency owner override with reviewed local evidence; it is not
equivalent to a CI pass.

- **fast** — a stdlib-`unittest` suite under `test/checks/fast/` (`<family>_test.py`, ): the
  Python contract validators run against their committed positive + negative fixtures, **no build
  required** (no MLIR, no third-party deps). A coarse smoke gate (positive accepted / each negative
  fails closed) for quick PR signal before paying for the MLIR build. `make test-fast` runs the whole
  suite (`python3 -m unittest`); each family is also its own CTest test (`ctest -L fast`).
- **unit** — `unittests/` (gtest): direct C++ assertions for pure, non-user-facing logic
  that has no good textual/tool surface (the value model, JSON/hash primitives, the pure
  front-end scanners). This is the LLVM-idiomatic "where lit doesn't fit" layer — see the
  § below. Anything with a CLI/IR surface stays in **ir**/**full**, not here.
- **ir** — the `test/ir/` regression suite driven by **lit** (FileCheck for positive
  tool/IR output; `-verify-diagnostics` for verifier/frontend errors). Runs as the CTest
  test `lit`; see [`../test/ir/README.md`](../../test/ir/README.md).
- **full** — `make test` builds the toolchain and runs the build-dependent CTest acceptance surface
  directly (`ctest -LE 'umbrella|fast|golden|s5f'`): the **lit** acceptance suite (the migrated
  coded-diagnostic assertions) plus the contract/policy/validator/arch gates. **Authoritative.** The
  bash monolith `test/run_cpp_tests.sh` that this used to run is **retired** () — every numbered
  section was migrated to lit (`test/ir/`) or a native CTest gate; the per-group non-vacuous manifests
  in `test/ir/lit.cfg.py` are the anti-shrink guard its fixed section count used to be. (`fast` is the
  no-build tier, run by `make test-fast`; `golden`/`s5f` are fixture-/docker-gated — all three have
  dedicated CI steps + entrypoints.)
- **acceptance** — the heavyweight backend / e2e checks that need Foundry/`forge`, `solc`, and a
  Docker Postgres. Since  each is a **labeled CTest test** (`acceptance-*`) whose recipe lives once
  in [`../../test/acceptance/run.sh`](../../test/acceptance/run.sh); `ctest -L acceptance` runs them all
  and **skips (exit 77) what the box can't provision**. `make acceptance-suite` = `ctest -L acceptance`;
  `make acceptance` also folds in `tidy test validate capability-check mutation property security
  cross-rail`. The per-target `make` wrappers (`make solidity-reference-test`, `db-test`, …) are thin
  `ctest -R …` invocations that set `NEUTRINO_REQUIRE_TOOLS=1`, so a **provisioned CI job fails loudly
  rather than silently skipping** its evidence.
  Every `requires-forge` row runs against ONE cmake-configured Forge tool identity (executable, `solc`,
  and — on macOS — the declared native-library prefix its Mach-O closure needs), carried on the test's
  CTest `ENVIRONMENT` property so a bare `ctest` behaves like `make`. A forge that is present but whose
  native closure does not resolve is reported as **INFRASTRUCTURE (exit 66) before any conformance step**,
  never as a backend result and never as a skip. See
  [FORGE_TOOLCHAIN.md](FORGE_TOOLCHAIN.md) for the setup commands, the receipts and the negative probe.

The `make` targets are the primary invokers; **CTest** is the surface underneath (`enable_testing`
in `CMakeLists.txt`) so IDEs and `ctest -L <label>` / `ctest -LE <exclude>` get the same entry points.
`make test` is `ctest -LE 'umbrella|fast|golden|s5f|acceptance'` (the build-dependent surface minus the
heavy provisioning tests); there is no longer a single `full`-labeled test (it ran the retired bash
monolith, ).

Source-governance self-tests share the `neutrino_source_tree_gate` CTest
resource lock. Several deliberately inject and restore invalid source fragments
to prove their scanners bite; the lock keeps `ctest -j` enabled without another
gate observing a transient probe. This includes the `fast` discovery umbrella
and `lit`, because each can reach the same mutation probes through a second
entrypoint. The `source-tree-gate-lock` policy test inspects CTest's configured
JSON and fails if a governed entrypoint loses the lock. Decision-path clone
probes copy source inputs only and exclude live build trees for the same reason.

### Test ownership & heaviness labels (, residual of )

Every test carries CTest **labels** so the suite can be sliced by *who owns it* and *what it needs*.
The vocabulary is closed and enforced by [`check_ctest_labels.py`](../../scripts/gates/check_ctest_labels.py)
(`ctest-labels` gate): an unknown/typo'd label fails, and a backend-owned test may not depend on a
*second* backend (two `backend-*` labels) unless it is explicitly an `e2e` test ( T9).

| Kind | Labels | Meaning |
|------|--------|---------|
| ownership | `backend-solidity` · `backend-postgres` · `slot` · `policy` | which module owns the test |
| heaviness | `acceptance` · `e2e` | needs external provisioning · spans >1 backend / full source→artifact→verify loop |
| provision | `requires-solc` · `requires-forge` · `requires-postgres` · `requires-docker` | the external toolchain it needs — skips if absent (Docker availability = a *usable daemon*, `docker info`, not just the CLI) |
| family | `fast` `golden` `s5f` `ir`/`lit` `contract` `validator` `schema` `policy` `grammar` … | the validator/kind family |

Common selections:

```
ctest -L e2e                                       # cross-backend / full-pipeline acceptance
ctest -L backend-solidity -LE requires-solc        # the light Solidity surface, no toolchain
ctest -LE 'requires-solc|requires-forge|requires-postgres|requires-docker'   # everything a bare box can run
```

Separately, optional **developer lanes** run the full C++ suite under runtime instrumentation —
`make asan` / `ubsan` / `asan-ubsan` (sanitizers) and `make cpp-coverage` (clang source coverage of
the *compiler's* C++, distinct from the semantic `make coverage`). They are off by default and build
into their own `out-*/` dirs, so the tiers above are unaffected. See
[`SANITIZERS_COVERAGE.md`](SANITIZERS_COVERAGE.md).

## Current test categories (in the lit acceptance suite)

The bash monolith `test/run_cpp_tests.sh` is **retired** (): its numbered checks were migrated to
lit + FileCheck / co-located Python helpers under `test/ir/` (run as the `lit` CTest test) or to the
native CTest gates. They fall into these categories:

- **Frontend & IR core** — `.neu` → MLIR translation, dialect verification, fail-closed
  rejection of malformed source/IR (`[1]`–`[3b]`): the `test/ir/` regression suite, the lit CTest test
  `lit` (see the § below and [`../test/ir/README.md`](../../test/ir/README.md)).
- **Backend codegen & equivalence** — byte-stable generation of slot/solidity/postgres/
  capability/coverage/security/views fixtures (R0 characterization `[43]` under `test/ir/pipeline/`),
  cross-backend equivalence.
- **Domain dialect & proposals** — dialect validation/hash-pinning, dataset-analysis
  proposals, the dialect registry (`[35]`, `[36]`, `[48]` under `test/ir/domain/` + `lang/`).
- **Contract validators** — binding topology/manifest, cross-rail fixture catalog,
  version/compatibility surface, L2 domain-semantics (`[49]`–`[60]` under `test/ir/{domain,compat,samples}/`).
- **Layout & language boundary** — domain-layout hygiene (`[53]`), conformance suite and
  the M3 language boundary (`[56]`, `[57]` under `test/ir/{compat,samples}/`).

## Adding tests for a new domain or backend

1. **Fixtures / golden artifacts** — follow
   [`ADDING_A_NEW_DOMAIN.md`](../domains/ADDING_A_NEW_DOMAIN.md) §4 (the R0 characterization + per-target diffs
   live in `test/ir/pipeline/check_characterization.py`; the byte-stable golden gates are the
   `neutrino_golden` CTest tests, `ctest -L golden`). This lands in the **full** tier.
2. **IR / lowering behavior** — add a FileCheck (or `-verify-diagnostics`) case under `test/ir/`
   (especially for a **new backend**): see [`../test/ir/README.md`](../../test/ir/README.md). Runs under
   `lit` (`make ir-test` ≡ `ctest -R ^lit`).
3. **A new stdlib contract validator** — add a positive + a `negatives/` fixture set, wire
   the exhaustive coded-diagnostic assertions into a co-located Python helper + `.test` driver under
   `test/ir/` and pin it in the group's non-vacuous manifest in `test/ir/lit.cfg.py` (**full**), and add a
   coarse positive/negatives smoke family `test/checks/fast/<family>_test.py` (a `FastCase`
   subclass) plus its row in the `NEUTRINO_FAST_CHECKS` table in `CMakeLists.txt` (**fast**) so
   gross breakage is caught before the build.
4. **Heavyweight backend checks** (forge/docker) belong in the **acceptance** tier targets,
   not the fast/full PR gate.
5. **A pure C++ helper** (no CLI/IR surface) — add a gtest case under `unittests/` (the
   **unit** tier); see § *The C++ unit tier* below.

## The C++ unit tier (gtest under `unittests/`, )

The LLVM ecosystem splits its tests by surface: **lit + FileCheck** for anything with a
tool/IR/textual surface, and **gtest** (`unittests/`) reserved for support/data-structure/API
logic that has no such surface. We follow the same split. The unit tier is for **pure,
non-user-facing** functions that were previously exercised only *indirectly* through the CLI:

- **value model** (`ValueModel.h`) — `classifyValueType` / `isNumericCategory` / `categoryName` /
  `governedCategories`;
- **JSON/hash primitives** (`JsonUtil.h`) — `jsonEscape` (byte-exact against fixture stability)
  and `sha256Hex` (the capability-spec identity digest, against known vectors);
- **pure front-end scanners** (`ParseUtil.h`) — `computeDeps`, `parseValueToken`,
  `collectQuotedStrings`, `splitBlockHeader`, the `allow`-grammar/version scanners.

Anything with a CLI/IR/diagnostic surface stays in **ir** (lit) or **full** — this tier is
*only* for direct C++ assertions where lit would be contrived.

**Build & run:** `make unittest` (≡ build `NeutrinoUnitTests` + `ctest -R ^unittests`). gtest is
resolved the standard out-of-tree way (flang D80377, MLIR standalone PR ): if the LLVM
being built against shipped its gtest (`LLVM_INSTALL_GTEST=ON` → the `llvm_gtest` target) it is
reused; otherwise googletest is vendored via `FetchContent` (the usual brew/prebuilt-LLVM case).

**Adding a unit:** drop a `<Thing>Test.cpp` into `unittests/`, add it to the source list in
`unittests/CMakeLists.txt`, and link the library that owns the function under test. Keep it to
pure functions — no MLIRContext, no filesystem, no golden artifacts.

## Tooling philosophy ()

The tooling refactor () moves orchestration into the standard MLIR-compiler stack while keeping
semantics in Python. The intended division of responsibilities, going forward:

- **CMake / Ninja / CTest** own **build, test registration, the generated-artifact DAG, and
  orchestration.** New tests are registered as their own CTest test (with labels), not appended to a
  shell monolith.
- **Python** owns **semantic / schema / domain validators only** — the meaning of an artifact. CTest
  *invokes* these; it never re-implements them. (See the role map in
  [TOOLING_INVENTORY.md](../process/TOOLING_INVENTORY.md).)
- **Shell** is **thin compatibility glue only** — tool wrappers (clang-format/-tidy, forge/solc) and
  `test/checks/*.sh` standalone gates. The 4.5k-line `test/run_cpp_tests.sh` legacy monolith has been
  fully decomposed into lit (`test/ir/`) + individual CTest tests and **deleted** () — no bash test
  monolith remains.

### Fail-closed is a test-layer property (no vacuous passes)

Migrating a check to CTest does **not** by itself make it sound. Every test — extracted or new —
**must assert it actually found and checked its intended inputs.** A test that scans zero files,
discovers no fixtures, or skips all its assertions **must fail**, not pass empty. Concretely:

- a discovery/sweep check asserts a **floor** on what it found (e.g. `check_renderer_includes.py
  --selftest` refuses if it discovers `< 3` migrated renderers);
- a check that reads a sample asserts the **read actually happened** (e.g. the fast families floor
  their fixture counts; a lit `-verify-diagnostics` test fails if the expected diagnostic is *not*
  produced, so it can't pass vacuously);
- CTest registration alone is not fail-closed — the *script/fixture* carries the guarantee.

This rule is mandatory: extracting `[89]` under it immediately surfaced (and fixed) a guard-rail grep
that had been **vacuously self-matching its own search list** in the monolith.

### Individually-registered checks (S1, )

`test/checks/*.sh` are the target shape: standalone, fail-closed, one CTest test each
(`renderer-include-lock`, `cpp-policy`, the arch scanners), registered in `CMakeLists.txt`, listed
separately by `ctest --test-dir out -N`, and run directly by `make test` (the CTest surface). During
the migration they were also invoked from `run_cpp_tests.sh`; that monolith is now deleted (). (The
`guarded-balance` gate moved to a lit `-verify-diagnostics` test — see § Decomposing the full runner.)

**Policy ratchet gate (`cpp-policy`,  S1 / ).** `scripts/gates/check_cpp_policy.py` pins the C++
error-handling / RTTI / ownership surface so it can only shrink: `dynamic_cast` is hard-zero across
`include/`+`lib/`+`tools/`, and `throw`/`std::runtime_error` (in `lib/`) and `std::shared_ptr` (in
`include/`+`lib/`) are pinned by a **per-file** ceiling in `scripts/gates/cpp_policy_baseline.json`. The
ratchet is by **equality**: an increase is a new violation, and a *reduction* also fails until it is
banked — regenerate the baseline with `python3 scripts/gates/check_cpp_policy.py --write-baseline` so the
ceiling moves down. Files are discovered by walking the tree (no hand-maintained list) and the scan
fails closed below a 20-file floor. It runs in the no-build `fast` tier and as its own CTest test.
The *rules* it enforces (and the current migration debt) live in [`AGENTS.md`](../../AGENTS.md).

### Granular fast tier (S2, ; native `unittest` since S5c, )

The **fast** tier is a stdlib **`unittest`** suite under `test/checks/fast/` — one module per validator
family (`<family>_test.py`, a `FastCase` subclass). Python owns the validators, so the tier is Python
too: the old bash harness (`scripts/run_fast_checks.sh` + `test/checks/fast/*.sh` + `_harness.sh`) is
retired. `make test-fast` runs the whole suite with `python3 -m unittest discover` (no cmake, no MLIR,
no third-party deps), and each family is ALSO its own labeled CTest test:

- `ctest --test-dir out -N -L fast` lists the **granular families** (22 today), not just an umbrella —
  a failure names the family (`fast-capability-spec`, `fast-target-profile-legality`, …) and families
  run in parallel. Each CTest row runs `python3 test/checks/fast/<family>_test.py`.
- Family labels beyond `fast` (`validator`, `schema`, `contract`, `artifact`, `completeness`,
  `release`, `domain`, `policy`, `grammar`) let you slice the tier: `ctest -L schema`, etc.
- The aggregate `make test-fast` entry stays as the CTest test `fast` under the **`umbrella`** label
  (kept off the `fast` label because `ctest -L` matches labels as a regex — otherwise the umbrella
  would double-run the whole tier under `-L fast`). The umbrella discovers the same `*_test.py` modules.
- `FastCase` (`test/checks/fast/_fastcase.py`) provides the harness the shells used — `val_ok`/
  `val_reject` (exit-code assertions), an auto-cleaned `self.tmp`, and `require_floor`, the
  **non-vacuous** guard: a family fails closed if it discovered/asserted fewer fixtures than its known
  minimum, so a wrong dir / renamed / eroded fixture set cannot pass on zero work. For the
  negative/tamper suites the floor is pinned to the committed count so a *partial* erosion of the
  fail-closed proof fixtures is caught too, not only an empty glob. Adding a fast check is a new
  `<family>_test.py` + one `NEUTRINO_FAST_CHECKS` row in `CMakeLists.txt`.

### Structural/meta gates via checker `--selftest` (S5d, )

The policy/architecture gates — `cpp-policy` (), `renderer-include-lock` (/), and
`arch-{backend,domain,root-scripts}-isolation` () — are Python checkers with a **`--selftest`**
mode: the checker runs its own positive + fail-closed negative self-tests (an empty tree, a malformed
config/baseline, an introduced violation, plus the false-positive guards), so there is no bash wrapper
— the CTest `COMMAND` is the checker itself (`python3 scripts/gates/check_*.py [--rule <r>] --selftest`).
They are labeled `policy`/`contract`/`domain-scaling` (not `fast`), and are source-only (each derives
the repo root from its own location, so they need no build). The no-build `fast` CI job also runs
`cpp-policy` + the arch scanners via their `--selftest` (they can't go through `ctest`, which needs an
MLIR configure the toolchain-free runner lacks). This retired
`test/checks/{cpp_policy,renderer_include_lock,arch_boundaries}.sh`.

### IR regression suite via `lit` (S5-F1,  — supersedes the  driver)

The IR regression suite under `test/ir/` is driven by **`lit`**, the standard LLVM/MLIR regression
driver — the LLVM-idiomatic replacement for the hand-rolled `scripts/run_ir_tests.sh` () and the
`cmake -P` scaffolding. `lit` is a pure-Python PyPI package (`pip install lit`, pinned in CI like
`clang-format`), independent of an LLVM source build.

- **Two idiomatic mechanisms**, both native `// RUN:` lines: **FileCheck** for positive tool/IR output
  (`%neutrino-opt %s | %FileCheck %s`), and **`-verify-diagnostics` + `// expected-error {{…}}`** for
  verifier errors (`%neutrino-opt --split-input-file --verify-diagnostics %s`) — asserting the *coded*
  diagnostic directly instead of grepping stderr (see [`../test/ir/README.md`](../../test/ir/README.md)).
- **CMake registers the whole suite as one CTest test `lit`** (labels `ir;lit;frontend`); each fixture
  is a lit sub-test named in the output. `ctest -R lit` / `make ir-test` run it; tool paths + lit are
  injected via a generated `lit.site.cfg.py` (working artifacts go to the build tree).
- **Fail-closed:** lit registration is conditional on `lit` being found at configure (build-only jobs
  configure fine without it), and CI's build-and-test job installs lit and **asserts the `lit` test is
  registered** — so a missing lit can't silently drop the IR suite.
- The IR suite is a first-class CTest test `lit` (the old bash `[61]` wrapper is retired). `make test`
  runs it as part of the CTest surface (`ctest -LE 'umbrella|fast|golden|s5f'`, and `lit` is labeled
  `ir;lit;frontend`); `make ir-test` runs just it (`ctest -R '^lit$'`).

### Generated-sample-artifact DAG (S4, )

Committed sample artifacts (a domain's `capability-spec.json` + `test-realization.json`) are
regenerated by the compiler, so staleness is a real risk. Slice 4 starts moving that from a
procedural shell diff into the **CMake/Ninja build graph**, so a stale fixture is a dependency edge,
not something a self-test has to remember to re-derive.

```
ninja -C out generate-sample-artifacts     # or: make generate-sample-artifacts
```

- The reusable **`neutrino_sample_artifacts(<domain>)`** CMake function models one domain. It declares
  two Ninja `OUTPUT`s in the **build** tree (`out/generated-samples/<domain>/`, never overwriting the
  committed fixtures): `capability-spec.json` (from `neutrino-gen --target=capability-spec`, DEPENDS =
  tool + source `.neu`) and `test-realization.json` (`--target=test-realization`, DEPENDS = tool +
  source + scenario). Ninja rebuilds exactly what a changed input invalidates — touch the **scenario**
  and only the test-realization regenerates (the capability-spec is scenario-free); touch the
  **source** and both do.
- A **validate + drift stamp** (`samples.validated`) byte-compares each generated artifact against its
  committed fixture *and* runs the owning Python validators (the generated test-realization is
  cross-checked against the freshly generated capability-spec, so their `capabilityHash` binding is
  proven in-DAG). The stamp is written only if every step passed.
- **Fail-closed / non-vacuous:** the source, scenario, and both committed fixtures must exist at
  configure time (`FATAL_ERROR` otherwise — a renamed domain can't register an empty DAG); a missing
  generated output (Ninja) or any failed compare/validate step fails the build; the stamp cannot be
  produced without validation actually running. CI runs the target and asserts the DAG-precision
  reschedule.
- The first slice models the canonical `core_sample_installment` sample; **adding another is
  one `neutrino_sample_artifacts(<domain>)` call.** Broader fixture-tree migration builds on this.
  Existing `make test-fast` / `make test` behavior is unchanged (the `neutrino_golden` CTest drift
  gates run under `ctest -L golden`).

### Decomposing the full runner (S5, ) — ✅ COMPLETE ()

> **Status: done.** `test/run_cpp_tests.sh` has been **deleted**. Every numbered section was migrated to
> lit + FileCheck / co-located Python helpers under `test/ir/` (the `lit` CTest test) or to a native
> CTest gate (`golden` / `s5f` / contract smokes). `make test` now runs the CTest surface directly
> (`ctest -LE 'umbrella|fast|golden|s5f'`), and the per-group non-vacuous manifests in `test/ir/lit.cfg.py`
> are the anti-shrink guard the monolith's fixed section count used to be. The sections below are a
> historical record of the incremental decomposition (S5a–S5n).

`test/run_cpp_tests.sh` was a ~4.5k-line, hand-numbered (`[1]`…`[93]`) monolith. S5 peeled coherent,
low-risk **groups** out of it into standalone CTest / lit tests **incrementally** — during the
transition the runner stayed the `full` umbrella (it still invoked every not-yet-peeled group), so
`make test` behavior was preserved while sections gained individual failure localization + labels.

Migrated groups so far — the **frontend + IR-verifier core** and the ** kernel guarded-balance
gate**, moved onto the lit foundation (§ above):

| Peeled section(s) | Now | Mechanism |
| --- | --- | --- |
| `[1]`/`[2]`/`[3]` translate-lowers + opt-verifies + reject-unbalanced | `test/ir/*` under `lit` | FileCheck (positive) + `-verify-diagnostics` (`verifier_diagnostics.mlir`) |
| `[93]`  guarded-balance (IR shapes + `.neu` waist) | `test/ir/verifier_diagnostics.mlir` + `test/ir/guarded_one_sided.neu` | `-verify-diagnostics` + `%not %neutrino-gen … \| %FileCheck` |
| `[3b]` malformed-`.neu` rejection table | 7 `test/ir/neg_*.neu` fixtures under `lit` | `%not %neutrino-translate %s … \| %FileCheck` (each fixture carries its own RUN/CHECK) |

- **Adding an IR verifier negative** is a `// -----` case in `verifier_diagnostics.mlir` with an
  `// expected-error`; a **source/waist rejection** is a `test/ir/*.neu` with `%not … | %FileCheck`.
  No hand-numbered section in the monolith. The whole frontend + IR-verifier group is now lit-native:
  the bash `ir_verifier.sh`, `guarded_balance.sh`, and `frontend_negatives.sh` are all retired.
  (The `neg_*.neu` fixtures append their RUN/CHECK at the *end* so the code's line numbers stay stable
  for the `run_cpp_tests.sh` language-intelligence sections that also consume some of them.)
- lit runs via `ctest -R lit`; CI asserts the `lit` test stays registered/runnable.

#### S5e (): artifact-generation + golden-diff sections → native CTest

The largest group in the monolith — *generate an artifact, `diff -q` a committed golden, `grep`
specific fields* — moves to a **bash-free** CTest gate built on the S4 DAG (§ above):

```
ninja -C out generate-golden-artifacts   # regenerate every golden artifact into the build tree
ctest --test-dir out -L golden --output-on-failure
```

- The reusable **`neutrino_golden(NAME … DOMAIN … TARGET … SUBDIR … [SCENARIO_FREE] FILES … [FIELDSCRIPT …])`**
  CMake function declares a Ninja `OUTPUT` that regenerates the artifact into `out/generated-goldens/<name>/`
  (never over the committed golden; DEPENDS = `neutrino-gen` + source `.neu` [+ scenario]). A CTest
  **fixture** (`golden-artifacts-setup`, `FIXTURES_SETUP`) builds that target once; each per-artifact
  test then drift-checks with **`cmake -E compare_files`** and pins semantic fields with **`cmake -P`**
  (`test/cmake/golden_diff.cmake` + a per-target `fields_*.cmake`) — **no shell**.
- Fail-closed / non-vacuous: the source + committed golden must exist at configure (`FATAL_ERROR`);
  a missing generated file, a byte drift, or an absent field pin fails the test. Goldens are byte-stable.
- CI (`build-and-test.yml`) asserts the `-L golden` / `-L ctest-native` surface is registered + labeled,
  then RUNS it — `make test` no longer covers these sections, so the CTest gate is the authoritative one.

Migrated sections (the `run_cpp_tests.sh` blocks are retired; the `[16b]`/`[22b]` spec-derivation
invariance checks — *not* golden-diffs — stay in bash and self-generate their base):

| Peeled section(s) | Now |
| --- | --- |
| `[11]`/`[13]`/`[32]` `generate.slot` (msi / soa / fbo + fbo binding policy) | `golden-slot-{msi,soa,fbo}` |
| `[14]` v0.1 static capability goldens | retired; v1 uses `capability_claims.test` for exact verified-catalog/schema/byte binding |
| `[16]` `generate.coverage` (coverage.json + L5/Level-1 pins, msi + soa) | `golden-coverage-{msi,soa}` |
| `[22]` `generate.security` (security.json + 5-category/ok pins, msi) | `golden-security-msi` |

**Adding a golden gate** is one `neutrino_golden(...)` call. Remaining golden-diff / artifact sections
to migrate in later slices (inventory):

- [ ] `[43]` T9-R0 characterization — solidity + postgres subtree byte-goldens (2 domains) + the schema-hash bridge vector.
- [ ] `[50]` M2 promotion `core_scheme_settlement` — slot + security + postgres golden subtrees.
- [ ] `[81]` PostgreSQL `procedure.sql` / `run_db_test.sh` byte-goldens (4 domains) + lifecycle/money-guard field pins.
- [ ] `[38]` D1b slot binding-topology golden.
- [ ] The postgres/solidity per-domain golden fixtures under `examples/domains/*/generated/{postgres,solidity}`.

#### S5f (): validator / backend-gen / equivalence sections → native CTest

The sibling of S5e: `run_cpp_tests.sh` sections whose assertion *is* a validator/generator/equivalence
run (pass == exit 0) move to a **bash-free** CTest path — a bare `add_test` where exit 0 is the whole
assertion, or a `cmake -P` where a multi-step run or a field pin is needed.

```
ctest --test-dir out -L s5f --output-on-failure
```

Migrated (the `run_cpp_tests.sh` blocks are retired; CI runs `-L s5f` since `make test` no longer does):

| Peeled section | Now | Mechanism |
| --- | --- | --- |
| `[18]` property testing (invariants over seeded-random inputs, via `neutrino-equiv`) | `s5f-property` | bare `add_test` (`property_test.py`, exit 0 == pass) |
| `[17]` mutation testing (critical mutants caught + `alter_compute_expr` survivor) | `s5f-mutation` | `cmake -P` (`mutation_test.py` exit 0 + report field pin) |
| `[8]` generality (2nd domain translates/verifies/generates both backends) | `s5f-generality` | `cmake -P` (4 tool steps, each exit 0) |

**Adding one** is a `add_test(... python3 validate_X.py <committed>)` (exit 0 == pass) or a small
`test/cmake/s5f_*.cmake`. Remaining validator/schema/equivalence sections to migrate (inventory) —
these bundle **Python-tampering negatives** (mutate a fixture → assert a coded rejection), so they stay
in the full runner until a later slice gives them a `cmake -P` shape:

- [ ] `[51]` cross-rail fixture catalog positive → bare `add_test`; its wrong-org / drifted-compat negatives need a mutation harness.
- [ ] `[72]`/`[73]` published compatibility manifest + sovereign-lowering envelope (positive validate + fail-closed negatives).
- [ ] `[42]` binding-manifest ↔ D1b topology; `[38]` slot binding-topology.
- [ ] `[90]` neutrino-equiv spec-vs-artifact structural (positive; field-parses `equivalence.json`).
- [ ] `[35]`/`[36]`/`[58]`/`[60]`/`[64]` domain-dialect / L2 validators (already have fast-tier smoke; full-tier does the exhaustive coded-diagnostic negatives).
