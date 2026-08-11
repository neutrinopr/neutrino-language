-- Reconciliation: a balanced procedure nets to zero per workflow key.
-- Returns one row per key WITH DRIFT (empty result == reconciled).
SELECT idempotency_key, SUM(signed_amount) AS drift
  FROM postings
 GROUP BY idempotency_key
HAVING SUM(signed_amount) <> 0;
