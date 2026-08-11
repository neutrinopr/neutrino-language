#!/usr/bin/env bash
# M5 signature domain () — behavioral acceptance for one cross-border
# PostgreSQL leg, driven against freshly generated schema/procedure bytes.
#
# Usage: acceptance_db_test.sh <sql-dir> <damage|export> <verified procedure>
set -euo pipefail
SQLDIR="${1:?usage: acceptance_db_test.sh <sql-dir> <leg> <procedure>}"
LEG="${2:?usage: acceptance_db_test.sh <sql-dir> <leg> <procedure>}"
PROC="${3:?usage: acceptance_db_test.sh <sql-dir> <leg> <procedure>}"
[ -f "$SQLDIR/schema.sql" ] && [ -f "$SQLDIR/procedure.sql" ] \
  || { echo "FAIL: $SQLDIR missing schema.sql/procedure.sql"; exit 1; }

case "$LEG" in
  damage)
    OSET=inspection_oracles; M=3; KEY='claim-ok'
    EXEC="execute_$PROC('shipment-ok','claim-ok','insurer-001','customer-il-001',300,'EUR','proof')"
    LA='insurance.reserve'; DA=-300; LB='customer.indemnity'; DB=300 ;;
  export)
    OSET=customs_oracles; M=2; KEY='clearance-ok'
    EXEC="execute_$PROC('shipment-ok','clearance-ok','customer-il-001','broker-it-001',500,'EUR','proof')"
    LA='customer.wallet'; DA=-500; LB='customer.escrow'; DB=500 ;;
  *) echo "FAIL: unknown leg '$LEG' (expected damage|export)"; exit 1 ;;
esac

mk_arr() {
  local n=$1 extra=${2:-} out="" i
  for i in $(seq 1 "$n"); do out="$out${out:+,}'obs-$i'"; done
  [ -n "$extra" ] && out="$out,'$extra'"
  printf "ARRAY[%s]" "$out"
}
VALID=$(mk_arr "$M")
SUB=$(mk_arr $((M-1)))
UNAUTH=$(mk_arr $((M-1)) 'obs-999')

CID=$(docker run -d \
  -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino \
  postgres:16-alpine)
cleanup(){ docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT
psql(){ docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U test -d neutrino "$@"; }
echo "=== $LEG ($PROC, quorum $M-of-N) ==="
echo 'waiting for postgres...'
ready=0
for _ in $(seq 1 60); do
  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'FAIL: postgres did not become ready'; exit 1; }

psql -q < "$SQLDIR/schema.sql" >/dev/null
psql -q < "$SQLDIR/procedure.sql" >/dev/null
psql -q >/dev/null <<SQL
INSERT INTO authorized_observer(observer_set, observer_id) VALUES
  ('$OSET','obs-1'), ('$OSET','obs-2'), ('$OSET','obs-3'), ('$OSET','obs-4');
SQL

expect_fail(){
  local out
  if out=$(psql -tAq 2>&1); then echo "FAIL: $1 not refused"; exit 1; fi
  if ! printf '%s' "$out" | grep -qF "$2"; then
    echo "FAIL: $1 refused for the WRONG reason (want '$2'); got: $out"
    exit 1
  fi
}
postings_for(){ psql -tAq <<SQL
SELECT count(*) FROM postings WHERE idempotency_key='$1';
SQL
}
balance_of(){ psql -tAq <<SQL
SELECT COALESCE(SUM(balance),0) FROM ledger_balance WHERE ledger='$1';
SQL
}

expect_fail 'execute without accepted quorum' 'quorum not accepted' <<SQL
SELECT $EXEC;
SQL
N=$(postings_for "$KEY")
[ "$N" = "0" ] \
  || { echo "FAIL: unaccepted execute wrote postings=$N (want 0)"; exit 1; }
echo '  [b] missing quorum blocks release (execute refused, no value): PASS'

expect_fail 'below-threshold accept' 'quorum not met' <<SQL
SELECT accept_$PROC('k-sub', 'h', $SUB);
SQL
echo "  [d1] below-threshold set ($((M-1)) of $M) fails closed: PASS"

expect_fail 'non-member accept' 'unauthorized observer' <<SQL
SELECT accept_$PROC('k-unauth', 'h', $UNAUTH);
SQL
echo '  [d2] non-member signer fails closed: PASS'

psql -tAq >/dev/null <<SQL
SELECT accept_$PROC('$KEY', 'h', $VALID);
SELECT $EXEC;
SQL
N=$(postings_for "$KEY")
[ "$N" = "2" ] \
  || { echo "FAIL: accepted execute postings=$N (want 2)"; exit 1; }
BA=$(balance_of "$LA")
BB=$(balance_of "$LB")
[ "$BA" = "$DA" ] || { echo "FAIL: $LA balance=$BA (want $DA)"; exit 1; }
[ "$BB" = "$DB" ] || { echo "FAIL: $LB balance=$BB (want $DB)"; exit 1; }
[ $((BA + BB)) -eq 0 ] \
  || { echo "FAIL: not balanced ($LA=$BA + $LB=$BB != 0)"; exit 1; }
echo "  [a/c] valid quorum -> execute: $LA=$BA $LB=$BB, BALANCED: PASS"

psql -q >/dev/null <<SQL
CREATE ROLE forger NOLOGIN;
SQL
expect_fail 'unprivileged accept denied' 'permission denied' <<SQL
SET ROLE forger;
SELECT accept_$PROC('k-forge', 'h', $VALID);
SQL
echo '  [d3] unprivileged accept_ denied: PASS'

echo "ALL ACCEPTANCE CHECKS PASSED ($LEG)"
