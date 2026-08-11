--  byte-faithful fixture: the temporal execute_ body's progress-flag reset.
-- Pins the EXACT production line the generated ProgressFlag handler must render.
-- The temporal (multi-policy) PostgreSQL contract is oracle-generated on the fly,
-- so no committed sample .sql carries `v_progress := …;` — this fixture is the
-- byte anchor for the .td->generated->golden render pair (mirroring the Solidity
-- import_source_unit_golden.sol fixture for a line not in any committed src golden).
    v_progress := false;
