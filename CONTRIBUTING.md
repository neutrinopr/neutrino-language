# Contributing

Thanks for your interest in Neutrino. This document covers how to build, test,
and structure changes.

## Prerequisites

- CMake 3.20+, Ninja, a C++17 compiler
- LLVM/MLIR 15 development files
- Python 3 (validators and test helpers)

Optional, for deeper validation: `FileCheck`, `solc`, Foundry (`forge`),
Docker/Colima for PostgreSQL integration, and `clang-format` / `clang-tidy`.

## Build and test

```bash
bash demo/check_claims.sh   # no-build claim-honesty sweep over public surfaces
make build                  # configure and build the native tools into out/
make test                   # native build plus compiler self-tests and fixtures
make acceptance             # full tier plus backend validation, equivalence, static analysis
```

CTest mirrors the fast and full tiers after configuration:

```bash
cmake -S . -B out -G Ninja \
  -DMLIR_DIR="$(llvm-config-15 --prefix)/lib/cmake/mlir" \
  -DLLVM_DIR="$(llvm-config-15 --prefix)/lib/cmake/llvm"

ctest --test-dir out -L fast
ctest --test-dir out -L full
```

The backend- and production-domain-free graph has its own configure and
standalone export checks:

```bash
cmake -S . -B out-core -G Ninja -DNEUTRINO_CORE_ONLY=ON \
  -DMLIR_DIR="$(llvm-config-15 --prefix)/lib/cmake/mlir" \
  -DLLVM_DIR="$(llvm-config-15 --prefix)/lib/cmake/llvm"
cmake --build out-core --target core-only
cmake --build out-core --target core-only-export-check
```

Additional targeted checks:

```bash
make fmt-check          # changed-line clang-format check
make tidy               # clang-tidy over compiler sources
make ir-test            # FileCheck-based IR regression suite
make native-build-gate  # compile generated native-code fixtures
make release-gate       # release-readiness build/test/manifest gate
```

See [`docs/testing/TESTING.md`](docs/testing/TESTING.md) for the full test
architecture.

## Change checklist

1. Update source, schemas, fixtures, and docs together when a contract changes.
2. Run `bash demo/check_claims.sh` for the no-build claim sweep, and `make test` for schema/validator changes (the validators run under the build).
3. Run `make test` for compiler, language, or generator changes.
4. Run `make acceptance` before release-sensitive backend changes.
5. Regenerate committed fixtures only through the documented Make targets or
   generator commands — keep generated-artifact churn intentional and reviewable.

When adding or changing a backend target, start with
[`docs/backends/BACKEND_GENERATORS.md`](docs/backends/BACKEND_GENERATORS.md).

For **LLVM/MLIR coding conventions** — RTTI/cast rules (`dynamic_cast` is
banned), MLIR construction/ownership, error handling, container choices, and how
the `cpp-policy` ratchet gate works — read the gate sources under
[`scripts/gates/`](scripts/gates/).

Optional **sanitizer** (`make asan` / `ubsan` / `asan-ubsan`) and **compiler
code-coverage** (`make cpp-coverage`) lanes are off by default and isolated in
their own build dirs; see
[`docs/testing/SANITIZERS_COVERAGE.md`](docs/testing/SANITIZERS_COVERAGE.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `include/Neutrino/` | Public compiler headers, MLIR ODS/TableGen dialect definitions, version constants. |
| `lib/` | C++ compiler implementation: frontend, dialect, verifier, generators, validators, manifests. Registry entry adapters live in `lib/emit/`; backend/policy renderers are leaf-only subprojects under `lib/backends/`, `lib/policy/`, `lib/slots`, `lib/views`. |
| `tools/` | CLI entry points: translate, opt, emit, gen, equiv, bundle. |
| `docs/` | Language, artifact, backend, testing, spec, and process documentation. |
| `docs/schemas/` | JSON schemas for generated artifacts and sidecar contracts. |
| `examples/` | Source examples, scenarios, generated fixtures, profiles, and validation fixtures. |
| `domains/` | Domain packs with committed generated Solidity/PostgreSQL artifacts. |
| `scripts/` | Python and shell validators, quality gates, and release helpers. |
| `test/` | Compiler fixtures, negative cases, conformance tests, and IR checks. |
| `unittests/` | C++ unit tests. |
| `demo/` | End-to-end demo scripts and narrative. |
| `cmake/` | CMake modules and test registration. |
| `packaging/` | Packaging inputs for distributing the native tools. |
| `linguist/` | Language-detection metadata for `.neu`. |
| `out/`, `build/`, `dist/` | Local build tree, generated artifacts, and release packages. Untracked. |

## Tools

Built tools live under `out/tools/<tool>/<tool>`:

| Tool | Purpose |
| --- | --- |
| `neutrino-translate` | Parse `.neu` source and emit textual Neutrino MLIR. |
| `neutrino-opt` | Load the dialect and run MLIR verification. |
| `neutrino-emit` | Emit inspection-only text projections. |
| `neutrino-gen` | Generate canonical artifacts and backend projects. |
| `neutrino-equiv` | Run cross-backend equivalence checks from one source/scenario pair. |
| `neutrino-bundle` | Run a bundle of generation targets from one input directory. |

```bash
out/tools/neutrino-gen/neutrino-gen --list-targets
out/tools/neutrino-gen/neutrino-gen --version-json
```
