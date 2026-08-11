--  byte-faithful fixture: the effectful NOT FOUND guard's idempotency early return.
-- Pins the EXACT single production line the generated IdempotentReturn handler
-- (a 0-operand constant `line`) must render — the replay-safe control-flow exit,
-- including the DOUBLE space after `RETURN;`. The node projects NO operands, so
-- the LINE SHAPE itself is the byte anchor for the .td->generated->golden render
-- pair (mirroring quorum_accept_golden.sql / temporal_accept_golden.sql).
    RETURN;  -- already processed; no double posting
