#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Publication-claim sweep (, H1–H3): scans the PUBLIC demo/entry
# surfaces for claim classes the mechanics cannot back, and FAILS on any hit.
# CASE-INSENSITIVE by design — a claim does not stop being a claim in caps
# (the DemoEUR.sol 'AUTHORITY' survivor is why), and the census covers every
# tracked demo source surface INCLUDING Solidity.
#
#   ./demo/check_claims.sh              sweep the tree (exit 1 on any hit)
#   ./demo/check_claims.sh --self-test  prove EVERY class bites its own
#                                       specimen, then prove the harness
#                                       notices a dead rule (mutation control)
#
# Surfaces: README.md + everything tracked under demo/ that is .md/.sh/.neu/.sol
# (this script excluded). materials/ and docs/ self-declare outside the public
# mirror and are the owner's rows, not this sweep's.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SURFACES=("$ROOT/README.md")
while IFS= read -r f; do SURFACES+=("$f"); done < <(
  find "$ROOT/demo" -maxdepth 2 \
    \( -name '*.md' -o -name '*.sh' -o -name '*.neu' -o -name '*.sol' \) \
    ! -name 'check_claims.sh' | sort
)

# PAIRED data: BANNED[i] is the class regex (grep -iE); SPECIMEN[i] is a
# known-positive sentence that class MUST catch. One specimen per class, so
# the self-test proves the full denominator — a rule without a specimen it
# demonstrably bites is decoration (the five-of-eighteen finding).
BANNED=(
  'bound to (the|its) (dossier|document|digest|keccak)'
  'names the exact document'
  'every claim (made on stage is re-verified|auditable) from chain state'
  'strict profile'
  'implements ERC'
  'conforms to ERC'
  'holds the supply authority'
  'authority gating'
  'authority-style'
  'value moves only with authority'
  'moved without authority'
  'authority signalled'
  'no fee can move'
  'the (authority|AUTHORITY) on when payment'
  'leaves (the requester.s )?escrow'
  'escrows (a|the|intent)'
  'atomic (token )?release'
  'evaluator-released (payment|funds)'
)
SPECIMEN=(
  'the attestation is bound to the dossier keccak'
  'the attestation names the exact document version'
  'every claim made on stage is re-verified from chain state'
  'expressible as a strict profile of the shape'
  'this contract implements ERC-8001'
  'this demo conforms to ERC-8183'
  'the issuer holds the supply authority'
  'compiled authority gating protects the mint'
  'an authority-style attest surface'
  'value moves only with authority'
  'no value moved without authority'
  'authority signalled on-chain'
  'so no fee can move'
  'the coordination is the AUTHORITY on when payment is owed'
  'the fee leaves escrow on attestation'
  'the requester escrows intent first'
  'atomic token release on attestation'
  'evaluator-released payment on verdict'
)

# A line that explicitly DENIES a claim is not the claim: absence markers and
# the honesty-boundary sentences name the banned phrase in order to negate it.
ALLOW='(NOT|not) bound to|Not "a strict profile"|Absent, explicitly'

scan() {
  local rc=0
  for pattern in "${BANNED[@]}"; do
    for f in "${SURFACES[@]}"; do
      local hits
      hits=$(grep -inE "$pattern" "$f" 2>/dev/null | grep -viE "$ALLOW" || true)
      if [ -n "$hits" ]; then
        echo "CLAIM SWEEP HIT: '$pattern' in $f:"
        echo "$hits" | head -3
        rc=1
      fi
    done
  done
  return $rc
}

# THE validator, factored so the mutation control exercises the same code
# path the real self-test relies on: every class must bite its own specimen.
# Quiet unless it fails (the mutation control expects failure and must not
# spam); returns nonzero on the first dead rule.
validate_pairs() {
  local quiet="${1:-}"
  local TMP; TMP="$(mktemp -d)"
  local i rc=0
  for i in "${!BANNED[@]}"; do
    printf '%s\n' "${SPECIMEN[$i]}" > "$TMP/s.txt"
    if ! grep -iqE "${BANNED[$i]}" "$TMP/s.txt"; then
      [ -n "$quiet" ] || \
        echo "SELF-TEST FAIL: class $i ('${BANNED[$i]}') does not catch its specimen"
      rc=1
    fi
  done
  rm -rf "$TMP"
  return $rc
}

self_test() {
  [ "${#BANNED[@]}" -eq "${#SPECIMEN[@]}" ] \
    || { echo "SELF-TEST FAIL: ${#BANNED[@]} rules but ${#SPECIMEN[@]} specimens"; return 1; }
  # 1. The intact denominator must validate.
  validate_pairs || return 1
  echo "SELF-TEST: all ${#BANNED[@]} classes bite their specimens"
  # 2. Corrupt one rule and run THE SAME VALIDATOR — it must FAIL. Testing
  #    the dead regex directly would only prove the regex is dead; routing
  #    through the validator proves the validator NOTICES dead rules, and
  #    a removed or inverted validator now fails this control instead of
  #    passing it (the eb0e40a0 review's finding).
  local saved="${BANNED[7]}"
  BANNED[7]='^this regex matches nothing at all$'
  if validate_pairs quiet; then
    BANNED[7]="$saved"
    echo "SELF-TEST FAIL: mutation control — the validator passed with a dead rule"
    return 1
  fi
  echo "SELF-TEST: mutation control PASS — the VALIDATOR fails on a dead rule"
  # 3. Restore, and prove restoration by running the validator once more.
  BANNED[7]="$saved"
  validate_pairs || { echo "SELF-TEST FAIL: restoration did not validate"; return 1; }
  echo "CLAIM SWEEP SELF-TEST PASS: ${#BANNED[@]}/${#BANNED[@]} classes proven, validator mutation-checked"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit $?
fi

if scan; then
  echo "CLAIM SWEEP CLEAN: ${#SURFACES[@]} public surfaces, ${#BANNED[@]} banned classes (case-insensitive), 0 hits"
else
  echo "CLAIM SWEEP FAIL: prohibited claim language survives (see hits above)"
  exit 1
fi
