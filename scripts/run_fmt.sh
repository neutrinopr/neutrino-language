#!/usr/bin/env bash
# Format baseline (M6 / quality-gates): clang-format the translator C++ sources
# (lib/ + include/ + tools/) per the checked-in .clang-format (LLVM house style).
#
# Adopts clang-format on an existing tree WITHOUT a mass reformat: it operates on
# CHANGED LINES only, via `git clang-format` against a base ref. New/changed code
# must be formatted; untouched legacy lines are grandfathered (and reformatted when
# next touched). Deterministic with the pinned LLVM 15 toolchain (same as the
# clang-tidy gate). Companion to scripts/run_tidy.sh.
#
#   run_fmt.sh check [BASE]   # fail if changed lines are not clang-format-clean
#   run_fmt.sh apply [BASE]   # reformat the changed lines in place
#
# BASE defaults to origin/main. Override clang-format via $CLANG_FORMAT.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

MODE="${1:-check}"
BASE="${2:-origin/main}"
DIRS=(lib include tools)
# C++ + headers only. TableGen (include/Neutrino/*.td) is intentionally excluded:
# clang-format on the pinned LLVM 15 line has no TableGen language mode (it lands in
# LLVM 19+) and parses .td as C++, which mis-formats valid TableGen. The dialect .td
# is hand-maintained until the toolchain gains TableGen support. See
# docs/testing/STATIC_ANALYSIS.md.
EXTS="cpp,h"

# Locate clang-format: $CLANG_FORMAT, then PATH, then the homebrew LLVM toolchain
# (mirrors run_tidy.sh's resolution so local + CI agree on the pinned version).
CF="${CLANG_FORMAT:-}"
if [ -z "$CF" ]; then
  if command -v clang-format >/dev/null 2>&1; then
    CF="clang-format"
  elif P="$(brew --prefix llvm 2>/dev/null)" && [ -x "$P/bin/clang-format" ]; then
    CF="$P/bin/clang-format"
  else
    echo "error: clang-format not found (set \$CLANG_FORMAT or install clang-format)" >&2
    exit 2
  fi
fi

# git-clang-format ships beside clang-format; fall back to PATH / versioned names.
GCF=""
cf_dir="$(cd "$(dirname "$(command -v "$CF" || echo "$CF")")" 2>/dev/null && pwd || true)"
for cand in "$cf_dir/git-clang-format" git-clang-format git-clang-format-15; do
  if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then GCF="$cand"; break; fi
done
if [ -z "$GCF" ]; then
  echo "error: git-clang-format not found (ships with clang-format)" >&2
  exit 2
fi

git rev-parse --verify --quiet "$BASE" >/dev/null 2>&1 \
  || { echo "error: base ref '$BASE' not found (fetch it, or pass a valid BASE)" >&2; exit 2; }

if [ "$MODE" = "apply" ]; then
  # git-clang-format exits non-zero when it reformats; that is success for `fmt`
  # (the goal is to apply). Tooling errors already exited 2 above.
  "$GCF" --binary "$CF" --extensions "$EXTS" "$BASE" -- "${DIRS[@]}" || true
  exit 0
fi

# check: show the changed-line reformat diff; clean if git-clang-format made none.
out="$("$GCF" --binary "$CF" --diff --extensions "$EXTS" "$BASE" -- "${DIRS[@]}" 2>&1)"
if printf '%s\n' "$out" | grep -qiE 'no modified files to format|did not modify any files|clang-format did not modify'; then
  echo "format: changed C++/header lines are clang-format clean (base $BASE; .td not gated)"
  exit 0
fi
printf '%s\n' "$out"
echo ""
echo "format: changed C++/header lines need formatting — run 'make fmt' (base $BASE)" >&2
exit 1
