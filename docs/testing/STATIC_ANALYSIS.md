# Translator Static-Analysis Gate

Security-first `clang-tidy` over the hand-written translator sources (`lib/` +
`tools/`). The verification/trust-model spec (Translator track, step 2) calls for
this **before expanding the trust/binding surface**: backend generators and
verifiers are security-critical and must fail closed.

## Run it

```bash
make tidy        # builds (for the compile DB), then runs the gate
make acceptance  # includes `tidy`
```

`make tidy` exits non-zero if any **blocking** finding is reported.

## What blocks vs. what's advisory

- **Blocking** (promoted to errors in [`.clang-tidy`](../../.clang-tidy)):
  `bugprone-*`, `clang-analyzer-*` (the clang static analyzer), `cert-*`
  (security-relevant), and bug-relevant `misc-*`.
- A few checks are **disabled as pure noise** for this codebase (documented in
  `.clang-tidy`): `bugprone-exception-escape` (fires on every plain data struct),
  `bugprone-easily-swappable-parameters`, `-narrowing-conversions`, `cert-err58-cpp`.
- Intentional, reviewed exceptions are acknowledged **inline** with
  `// NOLINT(<check>): <reason>` — e.g. the deliberate `std::system` subprocess
  orchestration in `neutrino-equiv` / `neutrino-bundle`, whose inserted values are
  shell-quoted (`shquote`/`shq`). A *new*, unjustified `system()` still fails the
  gate. A follow-up may move that orchestration to argv-style exec.

Only this project's own headers are diagnosed (`HeaderFilterRegex` matches
`include/Neutrino/*.h`); generated TableGen (`*.inc`) and LLVM/MLIR/system headers
are out of scope.

## Toolchain notes

The gate needs the compilation database (`out/compile_commands.json`, enabled via
`CMAKE_EXPORT_COMPILE_COMMANDS`). In CI ([`static-analysis.yml`](../../.github/workflows/static-analysis.yml))
the build and `clang-tidy` share the LLVM/MLIR 15 toolchain, so analysis matches
the compiler. On macOS, a homebrew-LLVM `clang-tidy` cannot parse the much newer
Apple SDK `libc++`; `scripts/run_tidy.sh` parses against LLVM's own `libc++`
headers instead (the build still uses the system compiler). Override the analyzer
with `CLANG_TIDY=...` if needed.

## Formatting baseline (clang-format)

C++ style is **LLVM** (2-space indent, 80 columns), pinned in
[`.clang-format`](../../.clang-format) and enforced on **changed lines only** —
existing code is grandfathered and reformatted when next touched, so adopting the
policy needed no mass reformat.

**Scope: C++ sources and headers (`.cpp`/`.h`) only.** TableGen dialect sources
(`include/Neutrino/*.td`) are intentionally **not** gated: clang-format on the
pinned LLVM 15 line has no TableGen language mode (it arrives in LLVM 19+) and would
parse `.td` as C++ and mis-format valid TableGen, so `NeutrinoOps.td` stays
hand-maintained. A `.td`-only change reports "clean" because there are no C++/header
lines to check; revisit gating `.td` when the toolchain reaches LLVM 19+.

- `make fmt-check` — fail if the lines changed vs `FMT_BASE` (default `origin/main`)
  are not clang-format-clean. This is the CI gate.
- `make fmt` — reformat those changed lines in place.

Both call [`scripts/run_fmt.sh`](../../scripts/run_fmt.sh), which uses
`git clang-format` against the base ref and resolves `clang-format` from
`$CLANG_FORMAT` → `PATH` → homebrew LLVM (the LLVM 15 line, matching the clang-tidy
gate). CI runs a **separate** `clang-format` job in
[`static-analysis.yml`](../../.github/workflows/static-analysis.yml) (pinned
`clang-format==15.0.7` wheel, which also ships `git-clang-format`; PR-only, since the
check needs a base to diff against) — kept independent of the clang-tidy job so a
format result never hides a static-analysis result.

## Warning policy (where warnings-as-errors apply)

- **clang-tidy gate** — the security set (`bugprone` / `clang-analyzer` / `cert`) is
  **promoted to errors** and blocks (`-warnings-as-errors` over those checks; see
  `.clang-tidy`). Broad clang-tidy expansion beyond that set stays **advisory** until
  it is stable on the pinned toolchain — do not turn on new check families as
  blocking without verifying they are clean at LLVM 15.
- **clang-format gate** — `-Werror`-style only on formatting of changed lines
  (`make fmt-check`); it never affects compiler or tidy results.
- **Compiler build** — **not** `-Werror`. Ordinary build warnings (e.g. an unused
  function, a missing-field-initializer) do not fail the build; promote a warning to
  blocking only by adding it to the clang-tidy gate, not via global `-Werror`.
