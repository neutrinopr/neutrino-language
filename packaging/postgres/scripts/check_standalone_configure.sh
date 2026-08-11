#!/usr/bin/env bash
# Focused standalone-configure check for the PostgreSQL backend package ().
#
# Proves the standalone package skeleton (packaging/postgres/CMakeLists.txt)
# still CONFIGURES as a self-contained CMake project, with the public core
# stubbed (NBP_STANDALONE_CORE=OFF) — i.e. the extraction skeleton's build graph
# stays well-formed as the manifest/unit evolves. It does not compile (the full
# clean-clone build is a separate PR; publication gated on ); it validates the project parses,
# resolves the pinned llvm-tblgen, and declares every generated-.inc build step.
#
# Exit 0 = configures clean. Exit 1 = the skeleton drifted / cannot configure.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pkg_dir="$(dirname "$here")"                 # packaging/postgres

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/nbp-configure.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT

if ! command -v cmake >/dev/null 2>&1; then
  echo "standalone-configure check SKIPPED: cmake not on PATH" >&2
  exit 0
fi
if ! command -v llvm-tblgen >/dev/null 2>&1; then
  echo "standalone-configure check FAILED: llvm-tblgen not on PATH (required to regenerate the .inc build products)" >&2
  exit 1
fi

if ! cmake -S "$pkg_dir" -B "$build_dir" -DNBP_STANDALONE_CORE=OFF >"$build_dir/configure.log" 2>&1; then
  echo "standalone-configure check FAILED: packaging/postgres did not configure" >&2
  tail -20 "$build_dir/configure.log" >&2
  exit 1
fi

# Topology assertion ( §5): the exported targets surface must expose ONLY
# the backend target — no recipe-runtime / bundled-internal name. The package
# emits the export set into the build tree via export(EXPORT ...).
targets_file="$build_dir/NeutrinoBackendPostgresTargets.cmake"
if [[ ! -f "$targets_file" ]]; then
  echo "standalone-configure check FAILED: exported targets file not emitted ($targets_file)" >&2
  exit 1
fi
if grep -Eiq 'recipe_runtime|recipe-runtime|RecipeRuntime|nbp_recipe' "$targets_file"; then
  echo "standalone-configure check FAILED: the installed targets surface exports a recipe-runtime name (must be a private bundled detail,  §5):" >&2
  grep -Ein 'recipe_runtime|recipe-runtime|RecipeRuntime|nbp_recipe' "$targets_file" >&2
  exit 1
fi
if ! grep -q 'NeutrinoBackendPostgres' "$targets_file"; then
  echo "standalone-configure check FAILED: exported targets file does not contain the backend target" >&2
  exit 1
fi

echo "standalone-configure check OK: packaging/postgres configures self-contained; exported targets surface is backend-only (no recipe-runtime name)"
exit 0
