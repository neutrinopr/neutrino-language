#!/usr/bin/env bash
# Smoke-test an INSTALLED toolchain () — run from the installed/extracted
# binaries, never the source tree. Point it at a bin dir (default: $NEUTRINO_TOOLS_DIR,
# else PATH).
#
#   scripts/smoke_test.sh [<bin-dir>]
set -euo pipefail

BIN="${1:-${NEUTRINO_TOOLS_DIR:-}}"
run() { local t="$1"; shift; if [ -n "$BIN" ]; then "$BIN/$t" "$@"; else "$t" "$@"; fi; }

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# Hydrate one receipted corpus member through the same pack-only resolver used by
# release. The smoke test must not regain a private in-core fixture fallback.
CURATED_PATHS="$(
  python3 - "$HERE" <<'PY'
import json
from pathlib import Path
import sys

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "scripts" / "gates"))
from m6_pack_resolver import resolve_members

manifest = json.loads((repo / "docs" / "m6-curated-example-corpus.json").read_text())
members = resolve_members(manifest, repo=repo)
member = members[manifest["examples"][3]]
if member.source_path is None or member.scenario_dir is None:
    raise SystemExit("smoke: selected pack lacks source/scenario payloads")
scenarios = sorted(member.scenario_dir.glob("*.json"))
if len(scenarios) != 1:
    raise SystemExit(f"smoke: selected pack has {len(scenarios)} scenarios (want 1)")
print(member.source_path)
print(scenarios[0])
PY
)"
SRC="$(printf '%s\n' "$CURATED_PATHS" | sed -n '1p')"
SCN="$(printf '%s\n' "$CURATED_PATHS" | sed -n '2p')"
[ -n "$SRC" ] && [ -n "$SCN" ] \
  || { echo "FAIL: curated pack hydration"; exit 1; }
WORK="$(mktemp -d "${TMPDIR:-/tmp}/neutrino_smoke.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "smoke: tool help + capability descriptor"
run neutrino-gen --help    >/dev/null 2>&1 || { echo "FAIL: neutrino-gen --help";    exit 1; }
run neutrino-emit --help   >/dev/null 2>&1 || { echo "FAIL: neutrino-emit --help";   exit 1; }
run neutrino-bundle --capabilities | grep -q '"tool": "neutrino-bundle"' \
  || { echo "FAIL: neutrino-bundle --capabilities"; exit 1; }
# version surface is queryable from the installed binary ()
run neutrino-translate --version-json | grep -q '"kind": "neutrino.translator-version"' \
  || { echo "FAIL: neutrino-translate --version-json"; exit 1; }

echo "smoke: one .neu fixture generates security + slot (core targets)"
for tgt in security slot; do
  run neutrino-gen --target="$tgt" --scenario="$SCN" "$SRC" -o "$WORK/$tgt" >/dev/null 2>&1 \
    || { echo "FAIL: neutrino-gen --target=$tgt"; exit 1; }
done
[ -f "$WORK/security/security.json" ]    || { echo "FAIL: no security.json";   exit 1; }
[ -f "$WORK/slot/capability.lock" ]      || { echo "FAIL: no slot capability.lock"; exit 1; }

# Capability MODEL generation is deliberately not smoked here. Models are derived
# from the verified external target catalog ( retired core Solidity
# dispatch), and this release ships the core toolchain + conformance bundle, not
# backend packages -- so an installed release correctly reports
# `capability.catalog.empty: no verified external target profiles`. Asserting a
# solidity capability model here would smoke a backend the release does not
# distribute. The catalog-derived path is covered where packages exist, by
# test/ir/pipeline/capability_claims.test.
run neutrino-gen --target=capability --scenario="$SCN" "$SRC" -o "$WORK/capability" >/dev/null 2>&1 \
  && { echo "FAIL: --target=capability unexpectedly succeeded without any verified backend package"; exit 1; }

echo "SMOKE TESTS PASSED"
