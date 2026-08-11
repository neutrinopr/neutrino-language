#!/usr/bin/env bash
#  PR2 review — balance obligation is scoped to (procedure, key).
#
# The generated `execute_<proc>` checks its balanced invariant with
#   SELECT COALESCE(SUM(signed_amount), 0) FROM postings
#   WHERE procedure = '<proc>' AND idempotency_key = p_<key>
# Coordination identity is (procedure, key) () and `postings` carries a
# procedure column, so the balance SUM MUST filter by procedure: a SIBLING
# procedure reusing the same raw idempotency key must not be able to fail this
# procedure's balance, nor mask its own imbalance.
#
# This test proves that, on a REAL container:
#   ISOLATION: two procedures write postings under the SAME raw key; each
#     procedure's PROCEDURE-SCOPED balance sums only its own rows.
#   NON-VACUITY (mutation): the UNSCOPED sum (key only, the pre-fix query) DOES
#     see the sibling's imbalance — so the `procedure =` filter is load-bearing,
#     not decorative.
#
# Usage: balance_scope_db_test.sh <sqldir>
#   <sqldir> has a byte-golden schema.sql (the coordination tables incl.
#   `postings(procedure, …, signed_amount, idempotency_key)`) and a
#   procedure.sql whose balance predicate is asserted procedure-scoped below.
set -euo pipefail
DIR="${1:?usage: balance_scope_db_test.sh <sqldir>}"
[ -f "$DIR/schema.sql" ] && [ -f "$DIR/procedure.sql" ] ||
  { echo "FAIL: $DIR missing schema.sql/procedure.sql"; exit 1; }

# Tie the behavioral proof to the GENERATED artifact: the emitted balance guard
# must be procedure-scoped (a revert to the key-only query fails here + [81]/[99]).
grep -qE "FROM postings WHERE procedure = '[^']+' AND idempotency_key" "$DIR/procedure.sql" ||
  { echo "FAIL: generated balance predicate is not procedure-scoped"; exit 1; }

CID=$(docker run -d -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)
cleanup(){ docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT
psql(){ docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U test -d neutrino "$@"; }

echo '=== balance obligation is (procedure, key)-scoped (two procedures, one key) ==='
echo 'waiting for postgres...'
ready=0
for _ in $(seq 1 60); do
  if docker exec "$CID" pg_isready -U test -d neutrino >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'FAIL: postgres did not become ready'; exit 1; }

# Apply the committed schema so `postings` is the REAL generated shape.
psql < "$DIR/schema.sql"

# Two procedures share the SAME raw idempotency key 'shared-key-001':
#   alpha posts a BALANCED pair (nets to 0); beta posts an IMBALANCED single row.
psql <<'SQL'
INSERT INTO postings(procedure, entry, ledger, party, amount, currency, signed_amount, idempotency_key)
VALUES ('alpha','a_debit','l','p', 100,'USD', -100,'shared-key-001'),
       ('alpha','a_credit','l','p',100,'USD',  100,'shared-key-001'),
       ('beta','b_debit','l','p',  50,'USD',  -50,'shared-key-001');
SQL

# ISOLATION: alpha's PROCEDURE-SCOPED balance sees only alpha's rows -> 0.
scoped=$(psql -tA -c "SELECT COALESCE(SUM(signed_amount),0) FROM postings WHERE procedure = 'alpha' AND idempotency_key = 'shared-key-001';")
[ "$scoped" = "0" ] ||
  { echo "FAIL: procedure-scoped balance for alpha = $scoped, expected 0 (sibling leaked in)"; exit 1; }
echo "  [1] OK: alpha procedure-scoped balance nets to 0 despite beta's shared-key postings"

# NON-VACUITY: the UNSCOPED (pre-fix) query DOES see beta's -50 -> the filter matters.
unscoped=$(psql -tA -c "SELECT COALESCE(SUM(signed_amount),0) FROM postings WHERE idempotency_key = 'shared-key-001';")
[ "$unscoped" = "-50" ] ||
  { echo "FAIL: unscoped balance = $unscoped, expected -50 (mutation/non-vacuity check)"; exit 1; }
echo "  [2] OK: unscoped key-only balance = -50 — the 'procedure =' filter is load-bearing"

echo 'PASS: the balanced obligation is scoped to (procedure, key)'
