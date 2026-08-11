R"NEUSQL(
--  temporal per-policy quorum +  coordination-envelope. The claim digest is
-- reproduced byte-for-byte from the reference (lib/spec-contract/CoordinationEnvelope.cpp):
-- frame(x) = big-endian uint64(byteLength(x)) || x, then SHA-256.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE OR REPLACE FUNCTION neu_frame(x text) RETURNS bytea AS $$
  SELECT decode(lpad(to_hex(length(convert_to(x, 'UTF8'))), 16, '0'), 'hex') || convert_to(x, 'UTF8');
$$ LANGUAGE sql IMMUTABLE;
CREATE OR REPLACE FUNCTION neu_execution_claim(p_coord_id text, p_key text, p_names text[], p_cats text[], p_vals text[]) RETURNS text AS $$
DECLARE pre bytea; i int;
BEGIN
  pre := neu_frame('neutrino.coordination-envelope.v1') || neu_frame(p_coord_id) || neu_frame(p_key) || neu_frame(cardinality(p_names)::text);
  FOR i IN 1 .. cardinality(p_names) LOOP
    pre := pre || neu_frame(p_names[i]) || neu_frame(p_cats[i]) || neu_frame(p_vals[i]);
  END LOOP;
  RETURN encode(digest(pre, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;
)NEUSQL"
