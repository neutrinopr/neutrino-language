--  byte-faithful fixture: the temporal accept_ gate's per-policy resolver.
-- Pins the EXACT production lines the generated PolicyCaseSelect handler (a
-- `framed-lines` LineGroup) must render — a fixed `CASE p_policy` header, one
-- `WHEN … THEN v_set := …; v_m := …;` item line per declared attestation policy
-- (each projecting its [input, observerSet, quorum] tuple), and the fixed
-- `ELSE RAISE …` / `END CASE;` footer. The two policy tuples here are fixture
-- values; only the LINE SHAPES are the byte anchor for the
-- .td->generated->golden render pair.
    CASE p_policy
      WHEN 'attest_primary' THEN v_set := 'observers_primary'; v_m := 2;
      WHEN 'attest_backup' THEN v_set := 'observers_backup'; v_m := 3;
      ELSE RAISE EXCEPTION 'unknown attestation policy %', p_policy;
    END CASE;
