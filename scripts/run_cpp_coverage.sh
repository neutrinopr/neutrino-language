#!/usr/bin/env bash
# Compiler C++ source-coverage report (M5 tooling S6, ). Consumes the .profraw files written by an
# instrumented run of the full C++ suite (built with NEUTRINO_ENABLE_COVERAGE=ON — see
# `make cpp-coverage`), merges them, and reports line/region coverage of OUR sources (lib/ include/
# tools/) with llvm-cov. Distinct from the semantic `make coverage` (L1-L10 language coverage).
#
#   run_cpp_coverage.sh <build-dir> [llvm-profdata] [llvm-cov]
#
# Fail-closed: if no .profraw or no instrumented binary is found, the instrumented run did not happen
# (or wrote nowhere) — exit non-zero rather than emit an empty/vacuous report.
set -euo pipefail
BD="${1:?usage: run_cpp_coverage.sh <build-dir> [llvm-profdata] [llvm-cov]}"
PROFDATA="${2:-llvm-profdata}"
COV="${3:-llvm-cov}"

shopt -s nullglob
raws=("$BD"/*.profraw)
if [ "${#raws[@]}" -eq 0 ]; then
  echo "error: no .profraw under $BD/ — run the instrumented suite first (make cpp-coverage)" >&2
  exit 1
fi

$PROFDATA merge -sparse "${raws[@]}" -o "$BD/neutrino.profdata"

# Every tool binary carries the coverage mapping for the sources it links (lib/ is shared). Report
# over all of them so the union covers the whole compiler.
main=""
extra=()
for t in neutrino-opt neutrino-translate neutrino-emit neutrino-gen neutrino-equiv neutrino-bundle; do
  bin="$BD/tools/$t/$t"
  [ -x "$bin" ] || continue
  if [ -z "$main" ]; then main="$bin"; else extra+=(-object "$bin"); fi
done
if [ -z "$main" ]; then
  echo "error: no instrumented tool binary under $BD/tools/ — was $BD built with NEUTRINO_ENABLE_COVERAGE=ON?" >&2
  exit 1
fi

# Keep only OUR translation units: drop the prebuilt LLVM/MLIR + system headers (which have no
# coverage mapping anyway, but this keeps the report to the compiler we own).
IGNORE='(/usr/|/opt/|/Cellar/|llvm@?[0-9]*/|/out-|/build/|/\.cargo/)'

echo "== compiler C++ coverage ($BD) =="
$COV report "$main" "${extra[@]}" -instr-profile="$BD/neutrino.profdata" \
  -ignore-filename-regex="$IGNORE" | tee "$BD/coverage-report.txt"
echo "wrote $BD/coverage-report.txt"

# HTML drill-down (best-effort; the text report is the required artifact).
if $COV show "$main" "${extra[@]}" -instr-profile="$BD/neutrino.profdata" \
     -ignore-filename-regex="$IGNORE" -format=html -output-dir="$BD/coverage-html" >/dev/null 2>&1; then
  echo "wrote $BD/coverage-html/index.html"
fi
