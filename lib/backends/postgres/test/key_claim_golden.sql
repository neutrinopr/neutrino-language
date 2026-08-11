--  byte-faithful fixture: the temporal execute_ body's claim-pin INSERT.
-- Pins the EXACT two production lines the generated KeyClaimInsert handler (a
-- `lines` LineGroup) must render — header, VALUES — for the ${proc}/${key}
-- operands the render harness feeds. `v_claim` is a literal PL/pgSQL variable
-- name owned by the .td template, not an operand. The operands here are fixture
-- values; only the LINE SHAPES are the byte anchor for the .td->generated->golden
-- render pair (mirroring posting_idempotency_golden.sql).
    INSERT INTO key_claim(procedure, idempotency_key, execution_claim)
    VALUES (p_proc, p_key, v_claim);
