#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# THE MAIN DEMO: two autonomous agents coordinating THROUGH the Neutrino-generated
# contract. No side channel exists -- the contract is the only medium, and its
# compiled semantics (checkpoint gating, paired accounting, replay refusal,
# balance) are the only rules. The checkpoint is an OPEN, unattributed
# attest(string): the contract requires its presence, not an authenticated
# identity — the demo keys are scripted to play their roles.
#
#   [walletco-agent]  wants the mint executed. Acts early, gets refused, adapts.
#   [issuerco-agent]  runs the issuer-side policy locally. Posts the checkpoint
#                     when that local policy clears.
#
# Beats: 1. walletco tries before the checkpoint exists -> chain refuses ("missing attestation")
#        2. walletco ADAPTS: watches chain state and waits
#        3. issuerco's local policy clears -> posts the CHECKPOINT on-chain (its only signal to anyone)
#        4. walletco sees the attestation in state -> executes -> value moves, balanced
#        5. a replay attempt                        -> chain refuses ("replay")
# Every agent decision is driven by a chain read; the interleaved log IS the demo.
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
SRC="$ROOT/domains/packs/token_mint/pack/source/token_mint.neu"
SCN="$ROOT/domains/packs/token_mint/pack/scenario/token_mint_happy_path.json"
WORK="${WORK:-$(mktemp -d)}"; PORT="${PORT:-8591}"; RPC="http://127.0.0.1:$PORT"
KEY_ISSUER=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80  # anvil dev 0
KEY_WALLET=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d  # anvil dev 1
MINT=mint-001

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

# -- stage: generate, compile, chain, deploy (proven in run_local_demo.sh) -----
# CONTRACT_DIR (optional,  AD5): substitute pre-generated project for neutrino-gen.
if [ -n "${CONTRACT_DIR:-}" ]; then
  [ -d "$CONTRACT_DIR" ] || die "CONTRACT_DIR is not a directory: $CONTRACT_DIR"
  GEN_DIR="$CONTRACT_DIR"
  say "[stage]" "CONTRACT_DIR override (AD5): $GEN_DIR"
else
  "$BIN_DIR/neutrino-gen" --target=solidity --scenario="$SCN" "$SRC" -o "$WORK/g" >/dev/null
  GEN_DIR="$WORK/g"
fi
[ -f "$GEN_DIR/src/TokenMint.sol" ] || die "expected $GEN_DIR/src/TokenMint.sol"
solc --bin --bin-runtime --optimize -o "$WORK/out" "$GEN_DIR/src/TokenMint.sol" >/dev/null
pkill -f "anvil --port $PORT" 2>/dev/null || true
anvil --port "$PORT" --silent >/dev/null 2>&1 & ANVIL=$!
trap 'kill $ANVIL 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do cast block-number --rpc-url "$RPC" >/dev/null 2>&1 && break; sleep 0.5; done
ADDR=$(cast send --private-key "$KEY_ISSUER" --rpc-url "$RPC" --json --create \
  "0x$(cat "$WORK"/out/TokenMint.bin)" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
[ "$(cast code "$ADDR" --rpc-url "$RPC")" = "0x$(cat "$WORK"/out/TokenMint.bin-runtime)" ] \
  || die "bytecode not bound to this run"
K=$(cast keccak $MINT)
say "[stage]" "agreement compiled, contract live at $ADDR -- agents start, no channel between them"

# -- the walletco agent: event-driven, adapts to refusals ----------------------
walletco_agent() {
  say "[walletco-agent]" "goal: execute $MINT for 2500 VST. Trying immediately."
  if cast send --private-key "$KEY_WALLET" --rpc-url "$RPC" "$ADDR" \
       'execute(string,string,string,uint256,string,uint256)' \
       $MINT token-reserve holder-001 2500 EUR 1 >/dev/null 2>&1; then
    die "chain accepted an unattested execute -- semantics broken"
  fi
  say "[walletco-agent]" "REFUSED by the contract (missing attestation). Adapting: watching chain state."
  for _ in $(seq 1 120); do
    [ "$(cast call "$ADDR" 'attested(bytes32)(bool)' "$K" --rpc-url "$RPC")" = "true" ] && break
    sleep 0.5
  done
  say "[walletco-agent]" "observed attestation ON-CHAIN. Executing now."
  cast send --private-key "$KEY_WALLET" --rpc-url "$RPC" "$ADDR" \
    'execute(string,string,string,uint256,string,uint256)' \
    $MINT token-reserve holder-001 2500 EUR 1 >/dev/null
  say "[walletco-agent]" "executed. Verifying settlement from state, not from anyone's word:"
  say "[walletco-agent]" "  creditTotal=$(cast call "$ADDR" 'creditTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC")  status=$(cast call "$ADDR" 'statusOf(bytes32)(uint8)' "$K" --rpc-url "$RPC") (1=Reconciled)"
  if cast send --private-key "$KEY_WALLET" --rpc-url "$RPC" "$ADDR" \
       'execute(string,string,string,uint256,string,uint256)' \
       $MINT token-reserve holder-001 2500 EUR 1 >/dev/null 2>&1; then
    die "replay accepted"
  fi
  say "[walletco-agent]" "replay attempt REFUSED by the contract. Settled; standing down."
}

# -- the issuerco agent: attests when its policy clears ------------------------
issuerco_agent() {
  say "[issuerco-agent]" "local issuer-side policy check for $MINT (reserve coverage, mandate)..."
  sleep 3   # the policy taking time is WHY walletco's first attempt must fail
  say "[issuerco-agent]" "policy CLEARED. Attesting on-chain -- my only signal to anyone."
  cast send --private-key "$KEY_ISSUER" --rpc-url "$RPC" "$ADDR" 'attest(string)' $MINT >/dev/null
}

walletco_agent & W=$!
issuerco_agent & I=$!
wait $I; wait $W || die "walletco agent failed"

# -- the auditor's view: nothing above is taken on trust -----------------------
[ "$(cast call "$ADDR" 'creditTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC")" = "2500" ] || die "credit != 2500"
[ "$(cast call "$ADDR" 'debitTotal(bytes32)(uint256)'  "$K" --rpc-url "$RPC")" = "2500" ] || die "unbalanced"
[ "$(cast call "$ADDR" 'statusOf(bytes32)(uint8)'      "$K" --rpc-url "$RPC")" = "1"    ] || die "not reconciled"
echo
echo "DEMO PASS: two agents, zero direct communication -- coordinated entirely through"
echo "the compiled agreement. Early action refused, checkpoint posted on-chain,"
echo "settlement balanced by construction, replay refused. All verified from state."
