#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The M6 end-to-end demo, local chain edition.
#
#   .neu (authored coordination) -> neutrino-gen -> Solidity -> solc -> anvil
#   -> attest + execute on chain -> ledger totals read back and CHECKED.
#
# Two runs on purpose:
#   APPROVED run    supply_approved=1 -> value moves, balanced by construction,
#                   creditTotal == debitTotal == amount, status Reconciled.
#   SUPPRESSED run  supply_approved=0 -> BOTH legs suppressed, zero value moves,
#                   yet the coordination still reconciles as a no-op.
# The second run is not an error case; it is the product: fail-closed
# coordination, visible on chain.
#
# Requirements: a built neutrino-gen (BIN_DIR), solc, foundry (anvil, cast).
# Optional: CONTRACT_DIR — skip neutrino-gen; use a pre-generated Solidity project
# tree (expects src/*.sol, same layout as neutrino-gen --target=solidity -o).
#  AD5 instrument: same harness vs a contract from the other pipeline.
# No network access, no keys of value: anvil's first dev account, local only.
set -euo pipefail

# macOS strips DYLD_* when exec'ing hardened binaries (which /bin/bash is), so a
# dyld override cannot survive INTO this script from outside. Machines whose
# foundry needs one pass it under a non-DYLD name; healthy installs ignore this.
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
PACK="${PACK:-token_mint}"
SRC="$ROOT/domains/packs/$PACK/pack/source/$PACK.neu"
SCN="$ROOT/domains/packs/$PACK/pack/scenario/${PACK}_happy_path.json"
WORK="${WORK:-$(mktemp -d)}"
PORT="${PORT:-8590}"
RPC="http://127.0.0.1:$PORT"
KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

step() { printf '\n== %s\n' "$*"; }
die() { printf 'DEMO FAIL: %s\n' "$*" >&2; exit 1; }


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
  if [ -z "${CONTRACT_DIR:-}" ]; then
    local gen="${BIN_DIR}/neutrino-gen"
    if [ ! -x "$gen" ]; then
      die "neutrino-gen not found at $gen — build with: ninja -C out neutrino-gen (see demo/QUICKSTART.md)"
    fi
  fi
  require_cmd solc "install a Solidity compiler and put it on PATH"
  require_cmd anvil "install Foundry (https://book.getfoundry.sh) and put anvil/cast on PATH"
  require_cmd cast "install Foundry and put cast on PATH"
  require_cmd xxd "usually provided by vim/xxd or macOS base tools"
}

require_demo_toolchain

if [ -n "${CONTRACT_DIR:-}" ]; then
  step "1/6 CONTRACT_DIR override (AD5): use pre-generated project at $CONTRACT_DIR"
  [ -d "$CONTRACT_DIR" ] || die "CONTRACT_DIR is not a directory: $CONTRACT_DIR"
  GEN_DIR="$CONTRACT_DIR"
else
  step "1/6 generate: $PACK.neu -> Solidity (scenario-checked)"
  "$BIN_DIR/neutrino-gen" --target=solidity --scenario="$SCN" "$SRC" -o "$WORK/solidity" \
    || die "neutrino-gen refused (see diagnostics.json)"
  GEN_DIR="$WORK/solidity"
fi
SOL="$GEN_DIR/src/TokenMint.sol"
[ -f "$SOL" ] || die "expected $SOL"

step "2/6 compile with the target's own toolchain (solc)"
solc --bin --bin-runtime --optimize -o "$WORK/out" "$SOL" >/dev/null || die "solc rejected the artifact"
BIN=$(cat "$WORK"/out/TokenMint.bin)
RUNTIME=$(cat "$WORK"/out/TokenMint.bin-runtime)
[ -n "$BIN" ] || die "empty creation bytecode"

step "3/6 local chain (anvil, port $PORT)"
pkill -f "anvil --port $PORT" 2>/dev/null || true
anvil --port "$PORT" --silent >/dev/null 2>&1 &
ANVIL=$!
trap 'kill $ANVIL 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do cast block-number --rpc-url "$RPC" >/dev/null 2>&1 && break; sleep 0.5; done
cast block-number --rpc-url "$RPC" >/dev/null 2>&1 || die "anvil did not come up"

step "4/6 deploy, and bind the address to THIS run's bytecode"
ADDR=$(cast send --private-key "$KEY" --rpc-url "$RPC" --json --create "0x$BIN" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
[ "${#ADDR}" -eq 42 ] || die "no contract address"
ONCHAIN=$(cast code "$ADDR" --rpc-url "$RPC")
[ "$ONCHAIN" = "0x$RUNTIME" ] || die "deployed bytecode is not this run's artifact"
echo "   deployed $ADDR (runtime bytecode verified against this run's solc output)"

step "5/6 APPROVED coordination: attest + execute, then read the ledger back"
cast send --private-key "$KEY" --rpc-url "$RPC" "$ADDR" 'attest(string)' mint-001 >/dev/null
cast send --private-key "$KEY" --rpc-url "$RPC" "$ADDR" \
  'execute(string,string,string,uint256,string,uint256)' \
  mint-001 token-reserve holder-001 2500 EUR 1 >/dev/null
K=$(cast keccak mint-001)
CREDIT=$(cast call "$ADDR" 'creditTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC")
DEBIT=$(cast call "$ADDR" 'debitTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC")
STATUS=$(cast call "$ADDR" 'statusOf(bytes32)(uint8)' "$K" --rpc-url "$RPC")
echo "   creditTotal=$CREDIT debitTotal=$DEBIT status=$STATUS"
[ "$CREDIT" = "2500" ] || die "credit read-back: got $CREDIT, scenario says 2500"
[ "$DEBIT" = "2500" ] || die "balanced-by-construction violated"
[ "$STATUS" = "1" ] || die "expected Reconciled"

step "6/6 SUPPRESSED coordination: unapproved mint moves NOTHING, and still reconciles"
cast send --private-key "$KEY" --rpc-url "$RPC" "$ADDR" 'attest(string)' mint-002 >/dev/null
cast send --private-key "$KEY" --rpc-url "$RPC" "$ADDR" \
  'execute(string,string,string,uint256,string,uint256)' \
  mint-002 token-reserve holder-001 2500 EUR 0 >/dev/null
K2=$(cast keccak mint-002)
CREDIT2=$(cast call "$ADDR" 'creditTotal(bytes32)(uint256)' "$K2" --rpc-url "$RPC")
STATUS2=$(cast call "$ADDR" 'statusOf(bytes32)(uint8)' "$K2" --rpc-url "$RPC")
echo "   creditTotal=$CREDIT2 status=$STATUS2"
[ "$CREDIT2" = "0" ] || die "suppression failed: value moved with approval input unset"
[ "$STATUS2" = "1" ] || die "suppressed run must still reconcile (as a no-op)"

printf '\nDEMO PASS: authored coordination -> verified artifact -> on-chain,\n'
printf 'value moves only when the caller-supplied approval input is set, balanced by\nconstruction, receipts above.\n'
