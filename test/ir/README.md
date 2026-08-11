# IR-level regression suite (`test/ir/`) —

Compiler-native IR checks using LLVM **FileCheck**. Where the golden-artifact tests
(R0 `[43]`, the per-domain `generated/` diffs) catch end-state *output* drift, these
smaller checks pin **dialect** and **inspection-projection** behavior at the IR level — so a
change is *explained* ("the `neutrino.debit` attribute set changed", "the events projection
stopped emitting the reconcile fact"), not just observed as a byte diff. Run with `make ir-test`
(≡ `ctest --test-dir out -R ^lit`); PR CI runs the `lit` CTest test on its own (not via `make test`).

## Mechanism: `lit` + FileCheck + `-verify-diagnostics` (LLVM-idiomatic)

Driven by **`lit`** (), the standard LLVM/MLIR regression-test driver. The installed LLVM ships
`FileCheck` but not `llvm-lit`; `lit` is a standalone pure-Python PyPI package (`pip install lit`,
independent of an LLVM source build), so we pin it like `clang-format`. It runs the `// RUN:` lines
in each fixture:
- **positive output** — `%neutrino-opt %s | %FileCheck %s` (FileCheck pattern-matches the IR/text);
- **IR verifier errors** — `%neutrino-opt --split-input-file --verify-diagnostics %s` with
  `// expected-error {{…}}` on the offending op: the MLIR-idiomatic way to assert a *coded* diagnostic
  directly ([MLIR Testing Guide](https://mlir.llvm.org/getting_started/TestingGuide/)), not by grepping
  stderr. `// -----` separates independent cases. `expected-error` matches its text as a **regex**, so
  escape `[` `]` `(` `)` (or use a plain substring, as `verifier_diagnostics.mlir` does). The kernel
  verifier negatives — `not_balanceable` and the  guarded-balance shapes — live here.
- **source / compiler-waist rejections** — `%not %neutrino-gen … %s -o %t.d 2>&1 | %FileCheck %s`:
  `%not` (the LLVM `not` tool) asserts the non-zero exit (the input is **rejected**, fail-closed — no
  artifact emitted) and FileCheck matches the coded diagnostic. Used for `.neu` sources the whole
  compiler waist must refuse (e.g. `guarded_one_sided.neu`, ).

CMake registers the whole suite as the CTest test `lit` (`ctest -R lit` / `make ir-test`); each fixture
is a lit sub-test named in the output. This retired the old `scripts/run_ir_tests.sh` driver () —
the fixtures were already in native lit format, so they run under real `lit` unchanged.

### Placeholders substituted in `RUN:` lines

| placeholder | becomes |
|---|---|
| `%s` | the test file itself (input **and** the FileCheck check-file) |
| `%neutrino-translate` | the built `neutrino-translate` |
| `%neutrino-opt` | the built `neutrino-opt` |
| `%neutrino-emit` | the built `neutrino-emit` |
| `%FileCheck` | `FileCheck` (from the build's LLVM prefix) |

## What's covered

- **`dialect_from_source.neu`** — *parser/dialect verification.* `neutrino-translate`
  lowers core `.neu` to the `neutrino` dialect; CHECK lines pin the op names and the
  attributes the generators consume (`neutrino.procedure` / `input` / `debit` / `credit`
  / `assert_balanced`).
- **`lowering_pipeline.mlir`** — *dialect verify round-trip + the events inspection projection.*
  `neutrino-opt` parses, runs the C++ dialect verifier, and re-prints the IR (`IR:`
  prefix); `neutrino-emit --kind=events` projects the IR's expected fact ordering
  (`EVENTS:` prefix) — **inspection only, not a backend**. Backends are the spec-derived
  `neutrino-gen --target=postgres|solidity`; the raw-MLIR `sql`/`contract` projections
  were retired in .

(The fail-closed dialect verifier is additionally pinned by `[3]` in
`run_cpp_tests.sh`, which rejects `test/unbalanced.mlir`.)

## Adding an IR test (dialect / inspection behavior)

1. Add a `test/ir/<name>.neu` (source→IR) or `test/ir/<name>.mlir` (IR→IR round-trip / events
   inspection) file. `//` is a comment in both formats, so RUN/CHECK lines live in the file.
2. Put one or more `RUN:` lines at the top using the placeholders above, e.g.
   `// RUN: %neutrino-emit --kind=events %s | %FileCheck %s --check-prefix=EVENTS`.
3. Write `CHECK:` (or `<PREFIX>:`) lines for the *stable* substrings that define the
   behavior — use `{{.*}}` for volatile bits (SSA numbers, operand order). Pin exactly
   what a regression should have to update on purpose.
4. To capture expected output while authoring: run the tool by hand
   (`out/tools/.../neutrino-emit --kind=events test/ir/<name>.mlir`) and turn the relevant
   lines into CHECKs.
5. Run it with `make ir-test` (≡ `ctest --test-dir out -R ^lit`) — `lit` drives the whole `test/ir/`
   suite as the CTest test `lit`, and each fixture is a lit sub-test named in the output. A newly
   added fixture is picked up on the next `lit` run (lit discovers `test/ir/*.{neu,mlir}` by suffix;
   `pip install lit` is required — see the mechanism section above). `make test` no longer runs the
   IR suite; PR CI runs the `lit` CTest test separately.

These IR fixtures pin **dialect and inspection-projection** behavior only (source→IR, opt
round-trip, `--kind=events`). **Backend shape is not tested here:**  retired the raw-MLIR
`sql`/`contract` projections, and backends are now the spec-derived `neutrino-gen
--target=postgres|solidity` path — pin a new backend lowering in the `neutrino-gen` /
generated-artifact suites (per-domain `generated/` diffs, R0 `[43]`), not with a `--kind=<backend>`
RUN line here.
