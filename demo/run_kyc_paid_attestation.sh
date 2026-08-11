#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# THE MAIN DEMO: agents doing real work, coordinated through compiled agreements,
# paid in ERC20 for the work.
#
#   requester-agent (acmebank)  has a KYC case and a dossier file. Passes the
#                               dossier DIGEST into execute as requester-supplied
#                               metadata (from a local handoff), then settles the
#                               fee in dEUR by a separate scripted ERC20 transfer
#                               once the coordination reconciles.
#   verifier-agent  (kycpro)    READS the dossier, runs real checks (required
#                               fields, document expiry, sanctions), refuses bad
#                               documents OFF-chain, and posts the case CHECKPOINT
#                               on-chain for good ones — an open, unattributed
#                               attest(case); the checkpoint is NOT bound to the
#                               digest.
#
# The coordination contract (KycAttestation.sol) was COMPILED from
# demo/kyc/kyc_attestation.neu -- nobody wrote its accounting logic by hand: the
# fee debit and compensation credit are one guarded, balanced pair recorded
# exactly when the checkpoint is present. The ERC20 transfer is a script step,
# not contract custody.
#
# Agent identities: both agents register on a local DemoAgentRegistry modeled on
# the ERC-8004 registration shape (demo scaffolding on anvil — not a live-registry
# adoption claim). Registration happens before coordination begins.
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
WORK="${WORK:-$(mktemp -d)}"; PORT="${PORT:-8592}"; RPC="http://127.0.0.1:$PORT"
KEY_REQ=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
KEY_VER=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
ADDR_REQ=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
ADDR_VER=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
CASE=case-042; FEE=15000   # 150.00 dEUR at 2 decimals

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

# Exact-file-bytes keccak256 via cast (no sha256, no third hash path, no
# normalization). Hex form is 0x-stripped for the stringy execute() input.
dossier_keccak() {
  local doc="$1" hex
  [ -f "$doc" ] || die "dossier_keccak: missing file $doc"
  hex=$(xxd -p -c 256 "$doc" | tr -d '\n')
  cast keccak "0x$hex" | sed 's/^0x//'
}

# CONTRACT_DIR (optional,  AD5): substitute pre-generated coordination project.
if [ -n "${CONTRACT_DIR:-}" ]; then
  [ -d "$CONTRACT_DIR" ] || die "CONTRACT_DIR is not a directory: $CONTRACT_DIR"
  GEN_DIR="$CONTRACT_DIR"
  say "[stage]" "CONTRACT_DIR override (AD5): $GEN_DIR"
else
  say "[stage]" "compiling the agreement: kyc_attestation.neu -> Solidity"
  "$BIN_DIR/neutrino-gen" --target=solidity --scenario="$ROOT/demo/kyc/kyc_happy_path.json" \
    "$ROOT/demo/kyc/kyc_attestation.neu" -o "$WORK/g" >/dev/null
  GEN_DIR="$WORK/g"
fi
[ -f "$GEN_DIR/src/KycAttestation.sol" ] || die "expected $GEN_DIR/src/KycAttestation.sol"
solc --bin --bin-runtime --optimize -o "$WORK/coord" "$GEN_DIR/src/KycAttestation.sol" >/dev/null
solc --bin --optimize -o "$WORK/erc20" "$ROOT/demo/kyc/DemoEUR.sol" >/dev/null
solc --bin --optimize -o "$WORK/registry" "$ROOT/demo/kyc/DemoAgentRegistry.sol" >/dev/null

pkill -f "anvil --port $PORT" 2>/dev/null || true
anvil --port "$PORT" --silent >/dev/null 2>&1 & trap 'kill %1 2>/dev/null||true' EXIT
for _ in $(seq 1 60); do cast block-number --rpc-url "$RPC" >/dev/null 2>&1 && break; sleep 0.5; done
COORD=$(cast send --private-key "$KEY_REQ" --rpc-url "$RPC" --json --create "0x$(cat "$WORK"/coord/KycAttestation.bin)" | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
[ "$(cast code "$COORD" --rpc-url "$RPC")" = "0x$(cat "$WORK"/coord/KycAttestation.bin-runtime)" ] || die "coord bytecode unbound"
TOKEN=$(cast send --private-key "$KEY_REQ" --rpc-url "$RPC" --json --create "0x$(cat "$WORK"/erc20/DemoEUR.bin)" | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
REG=$(cast send --private-key "$KEY_REQ" --rpc-url "$RPC" --json --create "0x$(cat "$WORK"/registry/DemoAgentRegistry.bin)" | python3 -c 'import sys,json;print(json.load(sys.stdin)["contractAddress"])')
K=$(cast keccak $CASE)
say "[stage]" "coordination live at $COORD; settlement token (dEUR) at $TOKEN"
say "[stage]" "demo agent registry (ERC-8004 registration shape) at $REG"

# Both agents register before coordinating (local registry; not mainnet 8004).
say "[stage]" "two ERC-8004-shape agents registering on the local registry"
cast send --private-key "$KEY_REQ" --rpc-url "$RPC" "$REG" \
  'register(string)' "demo://acmebank/requester-agent" >/dev/null
cast send --private-key "$KEY_VER" --rpc-url "$RPC" "$REG" \
  'register(string)' "demo://kycpro/verifier-agent" >/dev/null
AGENT_REQ=$(cast call "$REG" 'agentOf(address)(uint256)' "$ADDR_REQ" --rpc-url "$RPC" | awk '{print $1}')
AGENT_VER=$(cast call "$REG" 'agentOf(address)(uint256)' "$ADDR_VER" --rpc-url "$RPC" | awk '{print $1}')
[ "$AGENT_REQ" != "0" ] || die "requester agent not registered"
[ "$AGENT_VER" != "0" ] || die "verifier agent not registered"
say "[requester-agent]" "registered as agentId=$AGENT_REQ (demo registry)"
say "[verifier-agent]" "registered as agentId=$AGENT_VER (demo registry)"

# ---------------- the verifier's REAL work ------------------------------------
verify_dossier() {  # returns 0 = pass; prints named findings
  local doc="$1" ok=0
  for field in subject_name date_of_birth document_type document_number document_expiry sanctions_screening source_of_funds; do
    grep -q "^$field:" "$doc" || { say "[verifier-agent]" "  finding: missing field '$field'"; ok=1; }
  done
  local expiry sanct
  expiry=$(grep '^document_expiry:' "$doc" | awk '{print $2}')
  sanct=$(grep '^sanctions_screening:' "$doc" | awk '{print $2}')
  if [ "$(printf '%s\n' "$expiry" "$(date +%F)" | sort | head -1)" = "$expiry" ] && [ "$expiry" != "$(date +%F)" ]; then
    say "[verifier-agent]" "  finding: identity document EXPIRED ($expiry)"; ok=1
  fi
  [ "$sanct" = "clear" ] || { say "[verifier-agent]" "  finding: sanctions screening not clear ('$sanct')"; ok=1; }
  return $ok
}

verifier_agent() {
  # round 1: the requester's first dossier
  local doc="$ROOT/demo/kyc/dossier-case-042-v1.md"
  say "[verifier-agent]" "job received for $CASE. Reading $(basename "$doc") and verifying:"
  if verify_dossier "$doc"; then die "v1 dossier must fail"; fi
  # keccak of the refused dossier is computed for the log (exact file bytes) but
  # never attested — no digest is published for a refused document.
  local refuse_digest; refuse_digest=$(dossier_keccak "$doc")
  say "[verifier-agent]" "  dossier keccak256=${refuse_digest:0:16}… (not attested)"
  echo "$refuse_digest" > "$WORK/refused.keccak"
  say "[verifier-agent]" "VERDICT: refuse. No attestation, no fee. Awaiting a corrected dossier."
  echo refused > "$WORK/round1"

  # round 2: the corrected dossier
  until [ -f "$WORK/dossier2.submitted" ]; do sleep 0.3; done
  doc="$ROOT/demo/kyc/dossier-case-042-v2.md"
  say "[verifier-agent]" "corrected dossier received. Re-verifying $(basename "$doc"):"
  verify_dossier "$doc" || die "v2 dossier must pass"
  local digest; digest=$(dossier_keccak "$doc")
  say "[verifier-agent]" "all checks pass. Posting the case CHECKPOINT on-chain (attest is open/unattributed; keccak256 ${digest:0:16}… recorded LOCALLY, not on-chain)"
  echo "$digest" > "$WORK/verified.keccak"
  cast send --private-key "$KEY_VER" --rpc-url "$RPC" "$COORD" 'attest(string)' $CASE >/dev/null
}

requester_agent() {
  until [ -f "$WORK/round1" ]; do sleep 0.3; done
  say "[requester-agent]" "verifier refused v1 -- correcting the dossier (new passport) and resubmitting."
  touch "$WORK/dossier2.submitted"
  say "[requester-agent]" "watching the chain for the attestation..."
  for _ in $(seq 1 120); do
    [ "$(cast call "$COORD" 'attested(bytes32)(bool)' "$K" --rpc-url "$RPC")" = "true" ] && break; sleep 0.5
  done
  local digest; digest=$(cat "$WORK/verified.keccak")
  say "[requester-agent]" "checkpoint observed. Executing; passing the locally handed-off keccak digest as requester-supplied execute metadata."
  cast send --private-key "$KEY_REQ" --rpc-url "$RPC" "$COORD" \
    'execute(string,string,string,string,uint256,string,uint256)' \
    $CASE "$digest" acmebank-ops kycpro-desk $FEE EUR 1 >/dev/null
  local credit; credit=$(cast call "$COORD" 'creditTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC" | awk '{print $1}')
  [ "$credit" = "$FEE" ] || die "coordination fee ledger wrong: $credit"
  say "[requester-agent]" "coordination Reconciled: fee of $FEE owed per the compiled agreement. Settling in dEUR."
  cast send --private-key "$KEY_REQ" --rpc-url "$RPC" "$TOKEN" 'transfer(address,uint256)' "$ADDR_VER" $FEE >/dev/null
  # Replay must be refused by the compiled contract.
  if cast send --private-key "$KEY_REQ" --rpc-url "$RPC" "$COORD" \
      'execute(string,string,string,string,uint256,string,uint256)' \
      $CASE "$digest" acmebank-ops kycpro-desk $FEE EUR 1 >/dev/null 2>"$WORK/replay.err"; then
    die "replay accepted"
  fi
  say "[requester-agent]" "replay attempt REFUSED by the contract."
}

verifier_agent & V=$!
requester_agent & R=$!
wait $V || die "verifier agent failed"; wait $R || die "requester agent failed"

# ------- the auditor: chain-audited facts from state; digest equality LOCALLY -------
[ "$(cast call "$COORD" 'statusOf(bytes32)(uint8)' "$K" --rpc-url "$RPC")" = "1" ] || die "not reconciled"
[ "$(cast call "$COORD" 'creditTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC" | awk '{print $1}')" = "$FEE" ] || die "fee ledger"
[ "$(cast call "$COORD" 'debitTotal(bytes32)(uint256)' "$K" --rpc-url "$RPC" | awk '{print $1}')" = "$FEE" ] || die "unbalanced"
BAL=$(cast call "$TOKEN" 'balanceOf(address)(uint256)' "$ADDR_VER" --rpc-url "$RPC" | awk '{print $1}')
[ "$BAL" = "$FEE" ] || die "verifier not paid: $BAL"
# Auditor recomputes keccak256 over exact v2 dossier bytes and byte-matches the
# digest the agents used (not sha256; not a third hash path).
AUDITOR_DIGEST=$(dossier_keccak "$ROOT/demo/kyc/dossier-case-042-v2.md")
AGENT_DIGEST=$(cat "$WORK/verified.keccak")
[ "$AUDITOR_DIGEST" = "$AGENT_DIGEST" ] || die "auditor keccak mismatch: $AUDITOR_DIGEST != $AGENT_DIGEST"
say "[auditor]" "keccak256 of v2 dossier file bytes matches the locally handed-off digest (${AUDITOR_DIGEST:0:16}…) — a LOCAL equality, not a chain fact"
# refused v1 had a distinct digest and was never attested
REFUSED_DIGEST=$(cat "$WORK/refused.keccak")
[ "$REFUSED_DIGEST" != "$AUDITOR_DIGEST" ] || die "v1 and v2 digests unexpectedly identical"
# Auditor lists both agent registrations from the local registry.
REQ_URI=$(cast call "$REG" 'agents(uint256)(address,string,uint64)' "$AGENT_REQ" --rpc-url "$RPC" | sed -n '2p' | tr -d '"')
VER_URI=$(cast call "$REG" 'agents(uint256)(address,string,uint64)' "$AGENT_VER" --rpc-url "$RPC" | sed -n '2p' | tr -d '"')
say "[auditor]" "registry: agentId=$AGENT_REQ owner=$ADDR_REQ uri=$REQ_URI"
say "[auditor]" "registry: agentId=$AGENT_VER owner=$ADDR_VER uri=$VER_URI"
[ -n "$REQ_URI" ] && [ -n "$VER_URI" ] || die "auditor could not list agent URIs"
echo
echo "DEMO PASS: two ERC-8004-shape agents registered on a local demo registry;"
echo "real verification work on a real document -- bad dossier refused (no fee"
echo "moved), corrected dossier checkpointed on-chain (open attest; digest stays a"
echo "local handoff), compiled accounting reconciled the pay-for-work pair balanced"
echo "by construction, replay refused, ERC20 fee settled by a scripted transfer,"
echo "auditor re-derived the digest from file bytes (local equality) and listed both"
echo "agent registrations, and the verifier holds $FEE dEUR. Chain-audited facts:"
echo "status, coordination totals, registry entries, token balance, replay refusal."
