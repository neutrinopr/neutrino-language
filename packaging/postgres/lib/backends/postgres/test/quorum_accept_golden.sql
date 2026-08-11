--  byte-faithful fixture: the quorum accept_ gate's quorum-acceptance INSERT.
-- Pins the EXACT two production lines the generated QuorumAcceptInsert handler
-- (a `lines` LineGroup) must render — header, VALUES (incl. the nested
-- observer-count subquery) — for the ${proc}/${key} operands the render harness
-- feeds. The operands here are fixture values; only the LINE SHAPES are the byte
-- anchor for the .td->generated->golden render pair (mirroring
-- committed_group_golden.sql).
    INSERT INTO quorum_acceptance(procedure, claim_id, canonical_claim_hash, observer_count)
    VALUES (p_proc, p_key, p_canonical_claim_hash, (SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id)));
