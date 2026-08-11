--  byte-faithful fixture: the temporal execute_ body's committed-group INSERT.
-- Pins the EXACT two production lines the generated CommittedGroupInsert handler
-- (a `lines` LineGroup) must render — header, VALUES — for the
-- ${proc}/${key}/${ordinal} operands the render harness feeds. The operands here
-- are fixture values; only the LINE SHAPES are the byte anchor for the
-- .td->generated->golden render pair (mirroring key_claim_golden.sql).
    INSERT INTO committed_group(procedure, idempotency_key, group_ordinal)
    VALUES (p_proc, p_key, 0);
