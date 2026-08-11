--  byte-faithful fixture: the effectful execute_ body's replay-guard INSERT.
-- Pins the EXACT three production lines the generated PostingIdempotency handler
-- (a `lines` LineGroup) must render — header, VALUES, ON CONFLICT — for the
-- ${key}/${entry} operands the render harness feeds. The `${key}`/`${entry}`
-- VALUES here are fixture operands; only the LINE SHAPES are the byte anchor for
-- the .td->generated->golden render pair (mirroring progress_flag_golden.sql).
    INSERT INTO posting_idempotency(idempotency_key, entry)
    VALUES (p_workflow_key, 'demo_procedure')
    ON CONFLICT DO NOTHING;
