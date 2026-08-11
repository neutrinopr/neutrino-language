#!/usr/bin/env bash
# M5 token S1 () — BACKEND guard-loss proof, PostgreSQL rail (review  finding 2). Loads the
# GENERATED schema.sql + procedure.sql (passed as $1) into a real PostgreSQL container and drives
# execute_core_compliance_guard_fixture with compliance_approved = 1 / 0 / 2, asserting the rendered
# `IF p_compliance_approved = 1` guard actually holds: an approval posts both legs (2 postings), and a
# denial (0) or a malformed value (2) produces NO postings while the workflow still reconciles as a
# no-op. The sibling of the generated run_db_test.sh (happy path only); this adds the negative cases the
# review asked for so a backend renderer that mishandled 0/2 in this rail would be caught, not silently
# passed. No Python; all SQL through quoted heredocs.
set -euo pipefail
SQLDIR="${1:?usage: guard_loss_db_test.sh <dir with schema.sql + procedure.sql>}"
[ -f "$SQLDIR/schema.sql" ] && [ -f "$SQLDIR/procedure.sql" ] || { echo "FAIL: $SQLDIR missing schema.sql/procedure.sql"; exit 1; }

CID=$(docker run -d -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)
cleanup(){ docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT
psql(){ docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U test -d neutrino "$@"; }
echo 'waiting for postgres...'
ready=0
for _ in $(seq 1 60); do
  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'FAIL: postgres did not become ready'; exit 1; }

psql -q < "$SQLDIR/schema.sql" >/dev/null
psql -q < "$SQLDIR/procedure.sql" >/dev/null

postings_for(){ psql -tAq <<SQL
SELECT count(*) FROM postings WHERE idempotency_key='$1';
SQL
}

# APPROVED (== 1): both legs post -> 2 postings.
psql -tAq >/dev/null <<'SQL'
SELECT attest_core_compliance_guard_fixture('xfer-approved');
SELECT execute_core_compliance_guard_fixture('xfer-approved', 'sender-001', 'receiver-001', 2500, 'EUR', 1);
SQL
N=$(postings_for 'xfer-approved')
[ "$N" = "2" ] || { echo "FAIL: approved postings=$N (want 2)"; exit 1; }
echo '  [1] approved (==1) posts both legs: PASS'

# DENIED (== 0): guard suppresses -> NO postings, but the workflow still reconciles (no-op).
psql -tAq >/dev/null <<'SQL'
SELECT attest_core_compliance_guard_fixture('xfer-denied');
SELECT execute_core_compliance_guard_fixture('xfer-denied', 'sender-001', 'receiver-001', 2500, 'EUR', 0);
SQL
N=$(postings_for 'xfer-denied')
[ "$N" = "0" ] || { echo "FAIL: denied postings=$N (want 0 — guard loss!)"; exit 1; }
echo '  [2] denied (==0) moves no value: PASS'

# MALFORMED (== 2, out of range): fail-closed -> NO postings.
psql -tAq >/dev/null <<'SQL'
SELECT attest_core_compliance_guard_fixture('xfer-malformed');
SELECT execute_core_compliance_guard_fixture('xfer-malformed', 'sender-001', 'receiver-001', 2500, 'EUR', 2);
SQL
N=$(postings_for 'xfer-malformed')
[ "$N" = "0" ] || { echo "FAIL: malformed postings=$N (want 0 — guard loss!)"; exit 1; }
echo '  [3] malformed (==2) moves no value: PASS'

echo 'ALL POSTGRES GUARD-LOSS CHECKS PASSED'
