#!/usr/bin/env bash
# M5 oracle S2d () — the PostgreSQL M-of-N quorum guard's FAIL-CLOSED matrix. Loads the GENERATED
# schema.sql + procedure.sql (passed as $1), seeds a bound observer set, and drives accept_oracle_delivery
# / execute_oracle_delivery to prove the admission policy holds on the real DB: a quorum admits only when
# >= M DISTINCT AUTHORIZED observers attest the SAME claim, at most once, and the coordination fires only
# for an accepted claim. The generated run_db_test.sh proves the happy path + gate + replay; this proves
# the negatives  requires — unauthorized observer, duplicate observers, fewer than M, and that a
# different claim does not aggregate into quorum. Signature crypto is the off-chain aggregator's (SQL has
# no ecrecover); this guard admits already-recovered observer identities (the documented rail diff).
set -euo pipefail
SQLDIR="${1:?usage: quorum_fail_closed_db_test.sh <dir with schema.sql + procedure.sql>}"
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
# Seed the bound observer set (N=3 authorized); M (threshold) is 2, baked into accept_.
psql -q >/dev/null <<'SQL'
INSERT INTO authorized_observer(observer_set, observer_id) VALUES
  ('delivery_oracles','obs-1'), ('delivery_oracles','obs-2'), ('delivery_oracles','obs-3');
SQL

expect_fail(){ if psql -tAq >/dev/null 2>&1; then echo "FAIL: $1 not refused"; exit 1; fi; }
postings_for(){ psql -tAq <<SQL
SELECT count(*) FROM postings WHERE idempotency_key='$1';
SQL
}

# 1. FEWER THAN M (1 of 2) -> refused.
expect_fail 'sub-quorum' <<'SQL'
SELECT accept_oracle_delivery('claim-sub', 'h', ARRAY['obs-1']);
SQL
echo '  [1] fewer than M refused: PASS'

# 2. DUPLICATE observer that would otherwise MEET quorum (obs-1, obs-2, obs-2): distinct count is 2
#    (>= M), but a padded batch must not manufacture quorum from fewer real signers -> refused by the
#    explicit distinctness check (parity with the Solidity strict-ascending-signer rule).
expect_fail 'duplicate observer' <<'SQL'
SELECT accept_oracle_delivery('claim-dup', 'h', ARRAY['obs-1','obs-2','obs-2']);
SQL
echo '  [2] duplicate observer (distinct>=M but padded) refused: PASS'

# 3. UNAUTHORIZED observer (obs-999 not in the bound set) -> refused.
expect_fail 'unauthorized observer' <<'SQL'
SELECT accept_oracle_delivery('claim-unauth', 'h', ARRAY['obs-1','obs-999']);
SQL
echo '  [3] unauthorized observer refused: PASS'

# 4. VALID QUORUM (2 distinct authorized) -> accepted; execute then fires.
psql -tAq >/dev/null <<'SQL'
SELECT accept_oracle_delivery('order-ok', 'h', ARRAY['obs-1','obs-2']);
SELECT execute_oracle_delivery('order-ok', 'buyer-001', 'seller-001', 500, 'USD', 'proof');
SQL
N=$(postings_for 'order-ok')
[ "$N" = "2" ] || { echo "FAIL: accepted quorum postings=$N (want 2)"; exit 1; }
echo '  [4] valid quorum admits + fires: PASS'

# 5. DIFFERENT CLAIM does not aggregate: execute a key that was never accepted -> refused (no value).
expect_fail 'unaccepted claim' <<'SQL'
SELECT execute_oracle_delivery('order-other', 'buyer-001', 'seller-001', 500, 'USD', 'proof');
SQL
N=$(postings_for 'order-other')
[ "$N" = "0" ] || { echo "FAIL: unaccepted claim postings=$N (want 0)"; exit 1; }
echo '  [5] different claim does not aggregate: PASS'

# 6. REPLAY: re-accepting an accepted claim -> refused.
expect_fail 'already accepted' <<'SQL'
SELECT accept_oracle_delivery('order-ok', 'h', ARRAY['obs-1','obs-2']);
SQL
echo '  [6] accept replay refused: PASS'

# 7. ACCESS CONTROL (review): accept_ is REVOKEd from PUBLIC, so a non-privileged role
#    (the default for any db user who is not explicitly granted) CANNOT call it — the admission guard is
#    no-access-by-default. A quorum can't be forged by a caller who merely knows the (non-secret)
#    observer ids. The container's 'test' user is a SUPERUSER (bypasses REVOKE), so we create an
#    unprivileged role and prove the denial as that role.
psql -q >/dev/null <<'SQL'
CREATE ROLE forger NOLOGIN;
SQL
expect_fail 'unprivileged accept denied' <<'SQL'
SET ROLE forger;
SELECT accept_oracle_delivery('order-forge', 'h', ARRAY['obs-1','obs-2']);
SQL
echo '  [7] unprivileged accept_ denied (REVOKE is load-bearing): PASS'

echo 'ALL POSTGRES QUORUM FAIL-CLOSED CHECKS PASSED'
