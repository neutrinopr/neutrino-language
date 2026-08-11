# Sanitizer & compiler-coverage lanes (developer, )

Optional developer lanes for the **native C++ translator**: AddressSanitizer / UndefinedBehaviorSanitizer
runtime-safety builds, and clang **source-based coverage** of the compiler's own C++.

They are **off by default and fully isolated**: each lane configures a *separate* build dir
(`out-asan/`, `out-ubsan/`, `out-asan-ubsan/`, `out-cov/`) via CMake options that are `OFF` in the
normal build. `make build`, `make test`, `ctest`, and the release path are **unaffected** — they still
use `out/` with `-DCMAKE_BUILD_TYPE=Release` and none of these flags.

> **Not the same as `make coverage`.** The existing `coverage` target reports **Neutrino
> semantic/language coverage** — which of the L1–L10 *language levels* a procedure exercises and its
> maturity ceiling (a property of the compiled capability). The lanes here are **compiler C++ line/region
> coverage** — how much of *our own C++* (`lib/`/`include/`/`tools/`) the test suite executes. Different
> artifact, different question.

## Prerequisites

- **Compiler:** the lanes use the **same compiler as the normal build** — i.e. whatever CMake selects
  by default (Apple `clang` on macOS; the system/`CC` compiler on Linux). They do **not** pin a
  compiler (a Homebrew `clang++` fails to link on this macOS setup); the sanitizer/coverage runtimes
  ship with that compiler.
- **Coverage tools (must match the compiler):** clang source-coverage requires the `llvm-profdata` /
  `llvm-cov` that read the profile to be the **same LLVM as the compiler that wrote it**. So on macOS
  the coverage lane defaults to Apple's `xcrun llvm-profdata` / `xcrun llvm-cov` (matching Apple
  clang); on Linux it defaults to `$(LLVM_PREFIX)/bin/llvm-*`. Override `LLVM_PROFDATA` / `LLVM_COV` if
  your compiler differs (a version mismatch shows up as `unsupported instrumentation profile format
  version` at merge time). Sanitizers embed a self-contained runtime, so they need no external tools.
- **Disk:** room for a second (instrumented) build tree — each lane does a full MLIR build into its own
  `out-*/` dir.

## Commands

```sh
make asan          # AddressSanitizer: build our targets + run the full C++ suite (out-asan/)
make ubsan         # UndefinedBehaviorSanitizer                                   (out-ubsan/)
make asan-ubsan    # both, combined                                          (out-asan-ubsan/)
make cpp-coverage  # clang source coverage of the compiler over the full suite     (out-cov/)
```

Each `*san` target builds our translation units with the sanitizer, then runs the **full C++ self-test
suite** (`test/run_cpp_tests.sh`) against the instrumented tools, so a memory-safety (ASan) or
undefined-behaviour (UBSan) bug anywhere the suite exercises fails the run with a diagnostic.

`make cpp-coverage` instruments (`-fprofile-instr-generate -fcoverage-mapping`), runs the suite writing
one `.profraw` per tool invocation, then `scripts/run_cpp_coverage.sh` merges them
(`llvm-profdata`) and prints a per-file report (`llvm-cov report`) to `out-cov/coverage-report.txt`
(plus an HTML drill-down at `out-cov/coverage-html/index.html` when `llvm-cov show` succeeds). It fails
closed if no coverage data was produced (no vacuous "0 files" report).

### Tuning

Sanitizer runtime options are overridable (defaults chosen for a clean signal):

```sh
make asan  ASAN_OPTIONS="detect_leaks=1:abort_on_error=1"   # enable leak detection
make ubsan UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1"
```

`detect_leaks=0` is the ASan default here because MLIR/LLVM `Context`-owned objects are intentionally
released at process exit, not freed — leak detection is opt-in to avoid drowning real use-after-free /
overflow findings in expected-leak noise.

## Known limitation: sanitizers need an instrumented LLVM/MLIR

The prebuilt LLVM/MLIR from Homebrew is **not** sanitizer-instrumented — only our code is. For
**coverage** that is fine (coverage maps only our sources, and `make cpp-coverage` produces a clean,
complete report). For **ASan/UBSan** it is a real limitation: MLIR's uniqued-storage allocator
(`StorageUniquer` / `BumpPtrAllocator`) is header-inlined into our sanitized translation units, so it
poisons memory that the *non-instrumented* MLIR library then legitimately uses — and ASan reports a
**`use-after-poison` inside `mlir::StorageUniquer`** (e.g. building a `DictionaryAttr` in `viewOf`).

This is a **known false positive of partial instrumentation**, not a bug in our code, and it **cannot
be suppressed at runtime** (`detect_container_overflow=0` / `poison_heap=0` / a suppressions file do
not clear a use-after-poison). A **clean** ASan/UBSan run therefore requires an **ASan/UBSan-built
LLVM/MLIR** on `LLVM_PREFIX` — the moment one is present, these lanes run against it unchanged.

So today:
- `make cpp-coverage` — **fully working**, clean report. This is the ready-to-use lane.
- `make asan` / `ubsan` / `asan-ubsan` — **wired and runnable, but they FAIL against the stock brew
  LLVM** and cannot complete the suite. Every tool that uniques an MLIR attribute (i.e. all of them)
  trips the `StorageUniquer` artifact; the binaries are built with `-fsanitize-recover=address` /
  `=undefined` so each tool *continues past* its reports and prints the full set (useful for reading),
  but ASan still exits the tool non-zero, so `test/run_cpp_tests.sh` fails at the first case that
  asserts a clean exit (partway through, not on the very first report). So today this is **fail-first
  in effect**, not a green run: its value is surfacing reports for a human — a stack entirely inside
  `mlir::`/`llvm::` (or ODS-generated `neutrino::…verify`/`…constraint` frames reading that storage) is
  the artifact; a genuinely different `neutrino::` stack would be a real finding. A **clean, gating**
  run is blocked on an ASan-built LLVM — tracked in ****. The lane runs against one unchanged the
  moment it is on `LLVM_PREFIX`.

Building an ASan LLVM/MLIR (so the sanitizer lanes run clean end-to-end) is tracked as a follow-up,
not bundled into exposing the lanes here.

## Other notes

- **UBSan** instruments inlined LLVM/MLIR header code too, so it can also surface UB *inside* LLVM
  headers, not our code — same "artifact vs our-code" reading as above.
- These are **developer lanes**, not part of `make test`/`acceptance` — they are slower (a second full
  build) and their findings are advisory investigation aids.

## CI

**Not wired into CI in this slice**, on purpose: each lane is a *second* full instrumented MLIR build
(minutes) with a real disk cost, so running them on every PR would blow the macOS self-hosted runner
budget for low marginal signal on a mostly-deterministic codegen tree. The intended future hook is a
**scheduled / on-demand** job (nightly `workflow_dispatch` or a `run-sanitizers` label) that runs
`make asan-ubsan` and `make cpp-coverage` on Linux and uploads the coverage report as an artifact —
tracked as a follow-up rather than gating every PR here.
