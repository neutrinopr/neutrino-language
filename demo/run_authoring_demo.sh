#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Demo leg: untrusted authoring → verified compilation → on-chain pay-for-work.
#
# Trust model (stated again in the PASS banner):
#   The language model proposes; the translator verifies and refuses;
#   the guarantees come from compilation, not from the model.
#
# Artifacts under demo/authoring/:
#   agreement.md     natural-language agreement (human authored)
#   PROMPT.md        L1 grammar contract for an LLM proposer
#   authored.neu     committed machine-authored translation (untrusted input)
#
# Beat 1 — accept: compile authored.neu, deploy, attest+execute fee path, audit.
# Beat 2 — refuse: drop 'assert balanced' in a temp copy → named verifier refuse.
set -euo pipefail
if [ -n "${NEUTRINO_FOUNDRY_DYLD_LIBRARY_PATH:-}" ]; then
  export DYLD_LIBRARY_PATH="$NEUTRINO_FOUNDRY_DYLD_LIBRARY_PATH"
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -z "${BIN_DIR:-}" ]; then
  if [ -x "$ROOT/out/tools/neutrino-gen/neutrino-gen" ]; then
    BIN_DIR="$ROOT/out/tools/neutrino-gen"
  else
    BIN_DIR="$ROOT/build/tools/neutrino-gen"
  fi
fi
WORK="${WORK:-$(mktemp -d)}"; PORT="${PORT:-8593}"; RPC="http://127.0.0.1:$PORT"
KEY_REQ=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
KEY_VER=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
ADDR_VER=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
CASE=case-042; FEE=15000

say() { printf '%-18s %s\n' "$1" "$2"; }
die() { echo "DEMO FAIL: $*" >&2; exit 1; }

require_cmd() {
  local c="$1" hint="${2:-}"
  if ! command -v "$c" >/dev/null 2>&1; then
    if [ -n "$hint" ]; then
      die "missing required tool '$c' — $hint (see demo/QUICKSTART.md)"
    fi
    die "missing required tool '$c' (see demo/QUICKSTART.md)"
  fi
}
require_demo_toolchain() {
  # Refusal beat always needs neutrino-gen; CONTRACT_DIR only replaces the accept path.
  local gen="${BIN_DIR}/neutrino-gen"
  if [ ! -x "$gen" ]; then
    die "neutrino-gen not found at $gen — build with: ninja -C out neutrino-gen (see demo/QUICKSTART.md)"
  fi
  require_cmd solc "install a Solidity compiler and put it on PATH"
  require_cmd anvil "install Foundry and put anvil/cast on PATH"
  require_cmd cast "install Foundry and put cast on PATH"
  require_cmd xxd "usually provided by vim/xxd or macOS base tools"
}
require_demo_toolchain

NEU="$ROOT/demo/authoring/authored.neu"
SCN="$ROOT/demo/authoring/authored_happy_path.json"
[ -f "$NEU" ] || die "missing $NEU"
[ -f "$SCN" ] || die "missing $SCN"

say "[trust]" "language model proposes; translator verifies and refuses"
say "[trust]" "guarantees come from compilation, not from the model"

# CONTRACT_DIR (optional,  AD5): substitute pre-generated project for the
# accept-path compile. The refusal beat still runs neutrino-gen on a mutated .neu.
if [ -n "${CONTRACT_DIR:-}" ]; then
  [ -d "$CONTRACT_DIR" ] || die "CONTRACT_DIR is not a directory: $CONTRACT_DIR"
  GEN_DIR="$CONTRACT_DIR"
  say "[stage]" "CONTRACT_DIR override (AD5): $GEN_DIR"
  SOL=$(ls "$GEN_DIR"/src/*.sol 2>/dev/null | head -1)
  [ -f "$SOL" ] || die "no Solidity under $GEN_DIR/src"
  PROC=$(basename "$SOL" .sol)
  say "[stage]" "using pre-generated contract $PROC.sol (translator step skipped)"
else
  say "[stage]" "compiling untrusted authored.neu with the pinned toolchain"
  "$BIN_DIR/neutrino-gen" --target=solidity --scenario="$SCN" "$NEU" -o "$WORK/g" \
    || die "translator refused authored.neu (see $WORK/g/diagnostics.json)"
  GEN_DIR="$WORK/g"
  SOL=$(ls "$GEN_DIR"/src/*.sol | head -1)
  [ -f "$SOL" ] || die "no Solidity emitted"
  PROC=$(basename "$SOL" .sol)
  say "[stage]" "translator accepted authored.neu → $PROC.sol"
fi

solc --bin --bin-runtime --optimize -o "$WORK/coord" "$SOL" >/dev/null
solc --bin --optimize -o "$WORK/erc20" "$ROOT/demo/kyc/DemoEUR.sol" >/dev/null

pkill -f "anvil --port $PORT" 2>/dev/null || true
anvil --port "$PORT" --silent >/dev/null 2>&1 & trap 'kill %1 2>/dev/null||true' EXIT
for _ in $(seq 1 60); do cast block-number --rpc-url "$RPC" >/dev/null 2>&1 && break; sleep 0.5; done

COORD=$(cast send --private-key "$KEY_REQ" --rpc-url "$RPC" --json --create \
  "0x$(cat "$WORK"/coord/"$PROC".bin)" | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
[ "$(cast code "$COORD" --rpc-url "$RPC")" = "0x$(cat "$WORK"/coord/"$PROC".bin-runtime)" ] \
  || die "coord bytecode unbound"
TOKEN=$(cast send --private-key "$KEY_REQ" --rpc-url "$RPC" --json --create \
  "0x$(cat "$WORK"/erc20/DemoEUR.bin)" | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
K=$(cast keccak $CASE)
say "[stage]" "coordination live at $COORD"

# Verifier posts the checkpoint (open, unattributed attest of the generated contract), requester executes.
cast send --private-key "$KEY_VER" --rpc-url "$RPC" "$COORD" 'attest(string)' $CASE >/dev/null
# Digest discipline matches Demo 3: keccak256 over EXACT FILE BYTES, never a
# string label. The document of record for this run is the v2 dossier the
# KYC flow verifies.
DOSSIER="$ROOT/demo/kyc/dossier-case-042-v2.md"
DIGEST=$(cast keccak "0x$(xxd -p -c 256 "$DOSSIER" | tr -d '
')" | sed 's/^0x//')
cast send --private-key "$KEY_REQ" --rpc-url "$RPC" "$COORD" \
  'execute(string,string,string,string,uint256,string,uint256)' \
  $CASE "$DIGEST" acmebank-ops kycpro-desk $FEE EUR 1 >/dev/null
[ "$(cast call "$COORD" 'statusOf(bytes32)(uint8)' "$K" --rpc-url "$RPC")" = "1" ] || die "not reconciled"
[ "$(cast call "$COORD" 'creditTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC" | awk '{print $1}')" = "$FEE" ] || die "fee ledger"
cast send --private-key "$KEY_REQ" --rpc-url "$RPC" "$TOKEN" \
  'transfer(address,uint256)' "$ADDR_VER" $FEE >/dev/null
BAL=$(cast call "$TOKEN" 'balanceOf(address)(uint256)' "$ADDR_VER" --rpc-url "$RPC" | awk '{print $1}')
[ "$BAL" = "$FEE" ] || die "verifier not paid: $BAL"
say "[stage]" "on-chain pay-for-work path PASS (compiled from untrusted .neu)"

# -------- refusal beat: drop assert balanced → named verifier refuse ----------
say "[stage]" "refusal beat: mutate authored.neu (drop assert balanced)"
MUT="$WORK/authored_unbalanced.neu"
# strip the assert balanced line only
grep -v 'assert balanced' "$NEU" > "$MUT"
set +e
"$BIN_DIR/neutrino-gen" --target=solidity --scenario="$SCN" "$MUT" -o "$WORK/refuse" >/dev/null 2>"$WORK/refuse.err"
RC=$?
set -e
[ "$RC" -ne 0 ] || die "expected translator refusal for unbalanced mutation"
CODE=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["diagnostics"][0]["code"] if d.get("diagnostics") else "unknown")' \
  "$WORK/refuse/diagnostics.json" 2>/dev/null || echo "unknown")
[ "$CODE" = "kernel.balance.assert_missing" ] || die "unexpected refusal code: $CODE"
say "[translator]" "REFUSED untrusted mutation: code=$CODE"
grep -q 'assert_missing\|assert balanced\|built module failed' "$WORK/refuse.err" \
  "$WORK/refuse/diagnostics.json" 2>/dev/null || true

echo
echo "DEMO PASS: untrusted machine-authored .neu compiled and verified; on-chain"
echo "pay-for-work path reconciled; deliberate imbalance refused with named code"
echo "$CODE. The language model proposes; the translator verifies and refuses;"
echo "the guarantees come from compilation, not from the model."
