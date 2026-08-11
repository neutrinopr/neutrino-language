#!/usr/bin/env bash
# Translator static-analysis gate (Trust lane — Translator track, step 2).
#
# Runs clang-tidy over the hand-written translator sources (lib/ + tools/) using
# the real build flags from the compilation database. The check selection and the
# blocking set (bugprone / clang-analyzer / cert promoted to errors) live in
# `.clang-tidy`. Exits non-zero if any blocking finding is reported, so it can gate
# CI / `make acceptance`. Generators and verifiers are security-critical surfaces:
# the gate fails closed.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${BUILD_DIR:-out}"
cd "$HERE"

# Locate clang-tidy: $CLANG_TIDY, then PATH, then the homebrew LLVM toolchain.
TIDY="${CLANG_TIDY:-}"
if [ -z "$TIDY" ]; then
  if command -v clang-tidy >/dev/null 2>&1; then
    TIDY="clang-tidy"
  elif LLVM_PREFIX="$(brew --prefix llvm 2>/dev/null)" && [ -x "$LLVM_PREFIX/bin/clang-tidy" ]; then
    TIDY="$LLVM_PREFIX/bin/clang-tidy"
  else
    echo "error: clang-tidy not found (set \$CLANG_TIDY or install clang-tidy)" >&2
    exit 2
  fi
fi

if [ ! -f "$BUILD/compile_commands.json" ]; then
  echo "error: $BUILD/compile_commands.json missing — run 'make build' first" >&2
  exit 2
fi

# macOS quirk: a homebrew-LLVM clang-tidy cannot parse the much newer Apple SDK
# libc++ headers. Parse against LLVM's own libc++ instead (the build still uses the
# system compiler; this only affects analysis). No-op on Linux / matching toolchains.
EXTRA=()
if [ "$(uname)" = "Darwin" ]; then
  LLVM_PREFIX="${LLVM_PREFIX:-$(brew --prefix llvm 2>/dev/null)}"
  if [ -n "$LLVM_PREFIX" ] && [ -d "$LLVM_PREFIX/include/c++/v1" ]; then
    EXTRA=(--extra-arg=-nostdinc++ --extra-arg=-isystem"$LLVM_PREFIX/include/c++/v1")
  fi
fi

# Hand-written translator sources. Paths have no spaces, so a newline list +
# word-splitting is portable (avoids `mapfile`, which macOS bash 3.2 lacks).
FILES="$(ls lib/*.cpp; find tools -name '*.cpp')"

# Each clang-tidy invocation independently re-parses the (large) MLIR/LLVM header
# set, so the gate is CPU-bound and embarrassingly parallel across files. Fan out
# over the runner's cores (override with $TIDY_JOBS) instead of the old serial
# loop — this is the dominant CI cost. Ordering of findings may interleave, but
# each file's diagnostics still name the file, and the gate stays fail-closed.
JOBS="${TIDY_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
echo "static-analysis gate: clang-tidy over $(printf '%s\n' "$FILES" | grep -c .) files ($TIDY), $JOBS parallel"

# xargs runs one clang-tidy per file across $JOBS workers; it exits non-zero (123)
# if ANY invocation reports a blocking finding (clang-tidy exits non-zero on the
# errors .clang-tidy promotes), so the gate fails closed just like the serial loop.
# NOTE: parallel stdout may interleave across files. That is fine while findings
# are human-read; if this output is ever machine-parsed (e.g. the  diagnostics
# taxonomy), switch to per-file capture (mktemp per invocation, then `cat` serially)
# so interleaving can't corrupt the parse.
printf '%s\n' $FILES | xargs -P "$JOBS" -n1 "$TIDY" -p "$BUILD" "${EXTRA[@]}" --quiet
rc=$?
[ "$rc" -eq 0 ] || rc=1

if [ "$rc" -ne 0 ]; then
  echo "static-analysis gate: FAILED (blocking findings above)" >&2
else
  echo "static-analysis gate: OK (no blocking findings)"
fi
exit "$rc"
