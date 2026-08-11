#!/usr/bin/env bash
# [/] PostgreSQL leg of the execution-claim cross-implementation VALUE
# ratchet (test/ir/oracle/execution_claim_vector.test). One digest —
#   f08e38690b06cf6770ea204af8ce6039c6b990aca51d6702e0df119e35632325
# — must be identical across EVERY rail (the C++ reference recompute, the
# committed vector JSON, the guard + envelope Forge suites, the observer JS), so
# none can silently drift to a stand-in. This proves the in-database SQL rail
# (`neu_execution_claim`, emitted by the temporal legalizer ) reproduces the
# SAME digest byte-for-byte for the SAME vector inputs — the PostgreSQL twin of
# the on-chain CoordinationEnvelope.claim recompute leg.
#
# The vector (executionClaimHash("coord-id", "F-1", [{amount,money,1000},
# {flow_id,string,F-1}])) is fed with its inputs SORTED by name (amount, flow_id)
# — the same canonical order the legalizer's buildClaimArrays and the reference
# both frame — so a divergence in the SQL framing (length prefix, domain tag,
# field order, digest) breaks this test.
#
# Usage: pg_claim_vector_db_test.sh <sqldir>
#   <sqldir> is any GENERATED temporal PostgreSQL package; its schema.sql carries
#   the reviewed neu_frame + neu_execution_claim envelope functions (loaded as-is
#   — the functions are single-sourced from the generator, never hand-authored
#   here).
set -euo pipefail
DIR="${1:?usage: pg_claim_vector_db_test.sh <sqldir>}"
[ -f "$DIR/schema.sql" ] ||
  { echo "FAIL: $DIR missing schema.sql"; exit 1; }

VEC=f08e38690b06cf6770ea204af8ce6039c6b990aca51d6702e0df119e35632325

# Tie the proof to the GENERATED artifact: the emitted schema must carry the
# envelope claim function (a drop of the temporal envelope emission fails here).
grep -q 'CREATE OR REPLACE FUNCTION neu_execution_claim' "$DIR/schema.sql" ||
  { echo "FAIL: generated schema.sql has no neu_execution_claim envelope"; exit 1; }

CID=$(docker run -d -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)
cleanup(){ docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT
psql(){ docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U test -d neutrino "$@"; }

echo '=== PostgreSQL execution-claim reproduces the  cross-impl vector ==='
echo 'waiting for postgres...'
ready=0
for _ in $(seq 1 60); do
  if docker exec "$CID" pg_isready -U test -d neutrino >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'FAIL: postgres did not become ready'; exit 1; }

# Load ONLY the generated schema (defines pgcrypto + neu_frame + neu_execution_claim).
psql -q < "$DIR/schema.sql" >/dev/null

# Recompute the vector claim in-database over the SORTED inputs (amount, flow_id).
GOT=$(psql -tAq <<'SQL'
SELECT neu_execution_claim(
  'coord-id', 'F-1',
  ARRAY['amount', 'flow_id']::text[],
  ARRAY['money', 'string']::text[],
  ARRAY['1000', 'F-1']::text[]);
SQL
)
[ "$GOT" = "$VEC" ] ||
  { echo "FAIL: PostgreSQL neu_execution_claim = $GOT, expected $VEC (rail drift)"; exit 1; }
echo "  [1] OK: PostgreSQL neu_execution_claim == $VEC"

# NON-VACUITY (mutation): a single perturbed field (amount 1000 -> 1001) must
# produce a DIFFERENT digest — the framing is load-bearing, not a constant.
BAD=$(psql -tAq <<'SQL'
SELECT neu_execution_claim(
  'coord-id', 'F-1',
  ARRAY['amount', 'flow_id']::text[],
  ARRAY['money', 'string']::text[],
  ARRAY['1001', 'F-1']::text[]);
SQL
)
[ "$BAD" != "$VEC" ] ||
  { echo "FAIL: a perturbed input still hashed to the vector — digest is vacuous"; exit 1; }
echo "  [2] OK: a perturbed field diverges from the vector (framing is load-bearing)"

echo 'PASS: the PostgreSQL rail reproduces the  execution-claim vector'
