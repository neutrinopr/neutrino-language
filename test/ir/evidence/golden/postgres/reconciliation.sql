-- Evidence-only coordination: no ledger value moves, so there is nothing
-- to reconcile to zero. This lists the accepted evidence instances.
SELECT idempotency_key AS instance_key
  FROM coordination_status
 WHERE reconciled
 ORDER BY idempotency_key;
