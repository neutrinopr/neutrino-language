#!/usr/bin/env bash
# [] Executable migration-negative for the temporal upgrade preflight. The
# per-policy `quorum_acceptance` shape (policy + execution_claim columns, a
# (procedure, claim_id, policy) primary key) DIFFERS from the single-shot one. A
# bare `CREATE TABLE IF NOT EXISTS` over a pre-existing single-shot table is a
# silent no-op, so accept_/execute_ would later fail on the missing columns or
# admit only one policy under the old PK. The temporal schema's preflight must
# refuse that DETERMINISTICALLY, up front — a fresh-container-only test cannot
# catch this. This proves, on a REAL container:
#   REFUSAL: load the OLD single-shot schema, then the temporal schema — the
#     temporal load fails early with a clear "predates the  temporal
#     per-policy shape" message (the missing columns / wrong PK, not a late
#     failure inside accept_/execute_).
#   NON-VACUITY: the temporal schema loads cleanly on a FRESH database (the
#     preflight does not refuse a legitimate deployment), and is idempotent.
#
# Usage: old_schema_refused_db_test.sh <temporal_sqldir> <single_shot_sqldir>
set -euo pipefail
TDIR="${1:?usage: old_schema_refused_db_test.sh <temporal_sqldir> <single_shot_sqldir>}"
SDIR="${2:?usage: old_schema_refused_db_test.sh <temporal_sqldir> <single_shot_sqldir>}"
[ -f "$TDIR/schema.sql" ] || { echo "FAIL: $TDIR missing schema.sql"; exit 1; }
[ -f "$SDIR/schema.sql" ] || { echo "FAIL: $SDIR missing schema.sql"; exit 1; }

# Tie the proof to the GENERATED artifacts: the temporal schema must carry the
# per-policy shape + its preflight; the single-shot one must NOT have the policy
# column (it is the genuine pre-temporal shape).
grep -q "Temporal upgrade preflight ()" "$TDIR/schema.sql" ||
  { echo "FAIL: temporal schema.sql carries no  preflight"; exit 1; }
grep -qE "policy +text +NOT NULL" "$SDIR/schema.sql" &&
  { echo "FAIL: the 'single-shot' schema already has the policy column — not a pre-temporal shape"; exit 1; }

CID=$(docker run -d -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)
cleanup(){ docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT
psql(){ docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U test -d neutrino "$@"; }
echo '=== temporal upgrade preflight refuses a pre-existing single-shot schema ==='
echo 'waiting for postgres...'
ready=0
for _ in $(seq 1 60); do
  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'FAIL: postgres did not become ready'; exit 1; }

# 1. Load the OLD single-shot schema (creates the pre-temporal quorum_acceptance).
psql -q < "$SDIR/schema.sql" >/dev/null
echo '  [1] loaded the pre-temporal single-shot schema'

# 2. Load the temporal schema — the preflight MUST refuse it (missing columns).
if psql -q < "$TDIR/schema.sql" >/dev/null 2>/tmp/neu_mig_err; then
  echo "FAIL: temporal schema loaded over the single-shot table without refusal"; exit 1
fi
grep -q "predates the  temporal per-policy shape" /tmp/neu_mig_err ||
  { echo "FAIL: temporal load failed but not with the deterministic preflight refusal:"; cat /tmp/neu_mig_err; exit 1; }
echo "  [2] REFUSED with the deterministic temporal-shape preflight (missing columns / wrong PK)"

cleanup
# 3. NON-VACUITY: the temporal schema loads cleanly on a FRESH database, and is idempotent.
CID=$(docker run -d -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)
ready=0; for _ in $(seq 1 60); do if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi; sleep 1; done
[ "$ready" = 1 ] || { echo 'FAIL: fresh postgres did not become ready'; exit 1; }
psql -q < "$TDIR/schema.sql" >/dev/null ||
  { echo "FAIL: temporal schema was refused on a FRESH database (false positive)"; exit 1; }
psql -q < "$TDIR/schema.sql" >/dev/null ||
  { echo "FAIL: temporal schema is not idempotent on its own shape"; exit 1; }
echo '  [3] fresh load + idempotent re-load: OK'

echo 'PASS: the temporal upgrade preflight refuses a stale single-shot schema and admits a fresh one'
