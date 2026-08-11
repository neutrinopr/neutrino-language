#!/usr/bin/env bash
# M5 signature domain () — composed/shared-table replay-key isolation.
#
# Usage: composed_replay_isolation_db_test.sh <export-dir> <damage-dir>
#   <verified export procedure> <verified damage procedure>
set -euo pipefail
EXP="${1:?usage: composed_replay_isolation_db_test.sh <export> <damage> <export-proc> <damage-proc>}"
DAM="${2:?usage: composed_replay_isolation_db_test.sh <export> <damage> <export-proc> <damage-proc>}"
EXP_PROC="${3:?verified export procedure required}"
DAM_PROC="${4:?verified damage procedure required}"
for d in "$EXP" "$DAM"; do
  [ -f "$d/schema.sql" ] && [ -f "$d/procedure.sql" ] \
    || { echo "FAIL: $d missing schema.sql/procedure.sql"; exit 1; }
done

SHIP='ship-shared-001'
CLR='clearance-001'
CLM='claim-001'

CID=$(docker run -d \
  -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino \
  postgres:16-alpine)
cleanup(){ docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT
psql(){ docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U test -d neutrino "$@"; }
echo '=== composed cross-border replay isolation (one DB, two legs) ==='
echo 'waiting for postgres...'
ready=0
for _ in $(seq 1 60); do
  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'FAIL: postgres did not become ready'; exit 1; }

psql -q < "$EXP/schema.sql" >/dev/null
psql -q < "$EXP/procedure.sql" >/dev/null
psql -q < "$DAM/procedure.sql" >/dev/null
psql -q >/dev/null <<SQL
INSERT INTO authorized_observer(observer_set, observer_id)
SELECT s, o FROM unnest(ARRAY['customs_oracles','inspection_oracles']) s
            CROSS JOIN unnest(ARRAY['obs-1','obs-2','obs-3','obs-4']) o;
SQL

expect_fail(){
  local out
  if out=$(psql -tAq 2>&1); then echo "FAIL: $1 not refused"; exit 1; fi
  printf '%s' "$out" | grep -qF "$2" \
    || { echo "FAIL: $1 refused for wrong reason (want '$2'); got: $out"; exit 1; }
}
postings_for(){
  psql -tAq -c "SELECT count(*) FROM postings WHERE idempotency_key='$1';"
}
reconciled(){
  psql -tAq -c \
    "SELECT count(*) FROM coordination_status WHERE idempotency_key='$1' AND reconciled;"
}
balance_of(){
  psql -tAq -c \
    "SELECT COALESCE(SUM(balance),0) FROM ledger_balance WHERE ledger='$1';"
}

psql -tAq >/dev/null <<SQL
SELECT accept_$EXP_PROC('$CLR','h',ARRAY['obs-1','obs-2']);
SELECT execute_$EXP_PROC('$SHIP','$CLR','customer-il-001','broker-it-001',500,'EUR','p');
SELECT accept_$DAM_PROC('$CLM','h',ARRAY['obs-1','obs-2','obs-3']);
SELECT execute_$DAM_PROC('$SHIP','$CLM','insurer-001','customer-il-001',300,'EUR','p');
SQL
for k in "$CLR" "$CLM"; do
  [ "$(reconciled "$k")" = 1 ] \
    || { echo "FAIL: key '$k' did not reconcile"; exit 1; }
  [ "$(postings_for "$k")" = 2 ] \
    || { echo "FAIL: key '$k' postings != 2"; exit 1; }
done
for chk in \
  "customer.wallet:-500" "customer.escrow:500" \
  "insurance.reserve:-300" "customer.indemnity:300"; do
  L=${chk%%:*}
  want=${chk##*:}
  got=$(balance_of "$L")
  [ "$got" = "$want" ] \
    || { echo "FAIL: ledger $L=$got (want $want)"; exit 1; }
done
echo '  [1] both legs execute + reconcile independently in one DB: PASS'

before_dam=$(postings_for "$CLM")
expect_fail 'replay export key' 'replay' <<SQL
SELECT execute_$EXP_PROC('$SHIP','$CLR','customer-il-001','broker-it-001',500,'EUR','p');
SQL
[ "$(postings_for "$CLM")" = "$before_dam" ] \
  || { echo 'FAIL: replaying export disturbed damage postings'; exit 1; }
[ "$(reconciled "$CLM")" = 1 ] \
  || { echo 'FAIL: sibling leg lost reconciliation after export replay'; exit 1; }
echo '  [2] replaying one local key leaves the sibling untouched: PASS'

expect_fail 'damage without its own quorum' 'quorum not accepted' <<SQL
SELECT execute_$DAM_PROC('$SHIP','claim-002','insurer-001','customer-il-001',300,'EUR','p');
SQL
echo '  [3] a leg cannot ride a sibling quorum: PASS'

COLLIDE='collide-key-001'
recon_proc(){
  psql -tAq -c \
    "SELECT count(*) FROM coordination_status WHERE idempotency_key='$1' AND procedure='$2' AND reconciled;"
}
post_proc(){
  psql -tAq -c \
    "SELECT count(*) FROM postings WHERE idempotency_key='$1' AND procedure='$2';"
}

psql -tAq >/dev/null <<SQL
SELECT accept_$EXP_PROC('$COLLIDE','h',ARRAY['obs-1','obs-2']);
SELECT execute_$EXP_PROC('$SHIP','$COLLIDE','customer-il-001','broker-it-001',500,'EUR','p');
SQL
[ "$(recon_proc "$COLLIDE" "$EXP_PROC")" = 1 ] \
  || { echo 'FAIL: export did not reconcile under COLLIDE'; exit 1; }

expect_fail 'damage riding export quorum via a shared raw key' 'quorum not accepted' <<SQL
SELECT execute_$DAM_PROC('$SHIP','$COLLIDE','insurer-001','customer-il-001',300,'EUR','p');
SQL
[ "$(post_proc "$COLLIDE" "$DAM_PROC")" = 0 ] \
  || { echo 'FAIL: damage rode the export quorum'; exit 1; }
[ "$(recon_proc "$COLLIDE" "$EXP_PROC")" = 1 ] \
  || { echo 'FAIL: refused damage disturbed export reconciliation'; exit 1; }

psql -tAq >/dev/null <<SQL
SELECT accept_$DAM_PROC('$COLLIDE','h',ARRAY['obs-1','obs-2','obs-3']);
SELECT execute_$DAM_PROC('$SHIP','$COLLIDE','insurer-001','customer-il-001',300,'EUR','p');
SQL
[ "$(recon_proc "$COLLIDE" "$EXP_PROC")" = 1 ] \
  && [ "$(recon_proc "$COLLIDE" "$DAM_PROC")" = 1 ] \
  || { echo 'FAIL: shared raw key lacks independent procedure rows'; exit 1; }
[ "$(post_proc "$COLLIDE" "$EXP_PROC")" = 2 ] \
  && [ "$(post_proc "$COLLIDE" "$DAM_PROC")" = 2 ] \
  || { echo 'FAIL: postings are not isolated per procedure'; exit 1; }
echo '  [4] shared raw keys remain isolated by procedure: PASS'

echo 'COMPOSED REPLAY-ISOLATION CHECKS PASSED'
