//===- PostgresDdlCarrier.td - closed DDL-carrier construction schema -----===//
//
//  (Group C): the closed typed schema for the PostgreSQL raw-DDL carrier
// (`pgddl::RawSql`,  slice 2). scripts/generators/backend_recipe_gen.py
// --profile postgres-ddl-builders lowers this single closed descriptor to the
// authenticated generated construction `generated/PgDdlBuilders.inc`: the
// capability mint, the cap-gated minter, and the carrier combiner.
//
// The carrier type, its capability, its private already-lowered byte field, and
// the  friend seals are OWNED by Neutrino/PgDdl.h and preserved verbatim;
// this schema owns only the fixed-shape construction the generator emits, so no
// handwritten construction survives in the leaf. The reviewed  REVOKE bodies
// call the generated minter/combiner unchanged (their regionSha256 is intact).
//
//===----------------------------------------------------------------------===//

// One closed DDL carrier. `ByteField` is the carrier's private already-lowered
// SQL bytes (reachable from the minter/combiner via the  friendship);
// `Minter` is the cap-gated `std::string -> carrier`; `Forge` is the
// capability's static mint.
class DdlCarrier<string carrier, string cap, string byteField,
                 string minter, string forge> {
  string Carrier = carrier;
  string Cap = cap;
  string ByteField = byteField;
  string Minter = minter;
  string Forge = forge;
}

def : DdlCarrier<"RawSql", "DdlCap", "sql_", "rawSql", "forge">;
