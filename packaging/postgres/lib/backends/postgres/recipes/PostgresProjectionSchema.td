//===- PostgresProjectionSchema.td - PostgreSQL finalized projection ------===//
//
// : declarative ownership of the PostgreSQL provider's finalized-view
// project / slotExtent / slotItemOrder mappings.  Rows name only structural
// accessors over the already-finalized PostgreSQL input carriers.  They do not
// read a plan/specification, select a recipe, infer a rail, or spell SQL.
//
// scripts/generators/backend_recipe_gen.py --profile postgres-projection
// lowers this closed vocabulary to generated/PostgresProjection.inc.
//
//===----------------------------------------------------------------------===//

// A projected field.  Kind is one of the closed structural accessors consumed
// by the postgres-projection generator:
//   fixed          eager evidence-pool ordinal
//   item           typed owner-index carrier
//   eager-indexed  evidence param pool (base + stride * index + offset)
//   scalar         finalized rail-input scalar member
//   indexed        finalized rail-input vector member
//   nested         temporal group-posting member
//   parent-indexed effectful posting member selected by a parent slot
//   attestation    exact finalized attestation binding member
class PgProjectField<string railName, string fieldId, string valueName,
                     string accessorKind, string containerName = "",
                     string memberName = "", int ordinalValue = -1,
                     int strideValue = 0, int offsetValue = 0,
                     string parentSlotName = "",
                     string transformName = "identity"> {
  string Rail = railName;
  string Field = fieldId;
  string Value = valueName;
  string Kind = accessorKind;
  string Container = containerName;
  string Member = memberName;
  int Ordinal = ordinalValue;
  int Stride = strideValue;
  int Offset = offsetValue;
  string ParentSlot = parentSlotName;
  string Transform = transformName;
}

// A slot extent.  Kind is fixed | size | nested-size | member |
// comparison-present | comparison-absent | schema-memo | schema-plain.
class PgSlotExtent<string railName, string slotId, string extentKind,
                   string containerName = "", string memberName = "",
                   string parentSlotName = "", int fixedValue = 0> {
  string Rail = railName;
  string Slot = slotId;
  string Kind = extentKind;
  string Container = containerName;
  string Member = memberName;
  string ParentSlot = parentSlotName;
  int Fixed = fixedValue;
}

// An ordered slot.  Kind is indexed-ordinal | nested-ordinal.
class PgSlotItemOrder<string railName, string slotId, string orderKind,
                      string containerName, string parentSlotName = ""> {
  string Rail = railName;
  string Slot = slotId;
  string Kind = orderKind;
  string Container = containerName;
  string ParentSlot = parentSlotName;
}

// Evidence field projection.  The first ten values are the legacy eager pool;
// params are a typed item carrier plus a dense two-value pool per item.
def : PgProjectField<"Evidence", "proc.name", "TargetIdentifierAtom",
                     "fixed", "", "", 0>;
def : PgProjectField<"Evidence", "proc.executeName", "TargetIdentifierAtom",
                     "fixed", "", "", 1>;
def : PgProjectField<"Evidence", "proc.procLiteral", "TargetExpressionAtom",
                     "fixed", "", "", 2>;
def : PgProjectField<"Evidence", "proc.key", "TargetIdentifierAtom",
                     "fixed", "", "", 3>;
def : PgProjectField<"Evidence", "proc.keyType", "FinalizedTargetType",
                     "fixed", "", "", 4>;
def : PgProjectField<"Evidence", "proc.observerSet", "TargetExpressionAtom",
                     "fixed", "", "", 5>;
def : PgProjectField<"Evidence", "proc.quorumM", "TargetExpressionAtom",
                     "fixed", "", "", 6>;
def : PgProjectField<"Evidence", "proc.quorumPredicate", "TargetExpressionAtom",
                     "fixed", "", "", 7>;
def : PgProjectField<"Evidence", "proc.replayPredicate", "TargetExpressionAtom",
                     "fixed", "", "", 8>;
def : PgProjectField<"Evidence", "proc.statusAtom", "TargetExpressionAtom",
                     "fixed", "", "", 9>;
def : PgProjectField<"Evidence", "params.item", "FinalizedEvidenceParam",
                     "item", "params">;
def : PgProjectField<"Evidence", "param.name", "TargetIdentifierAtom",
                     "eager-indexed", "params", "", 10, 2, 0>;
def : PgProjectField<"Evidence", "param.type", "FinalizedTargetType",
                     "eager-indexed", "params", "", 10, 2, 1>;

// Temporal field projection.
def : PgProjectField<"Temporal", "tproc.name", "TargetIdentifierAtom",
                     "scalar", "", "name">;
// : raw procedure name as a string literal for the posting-insert `proc`
// string.escape hook input (the raw `name` stays TargetIdentifierAtom for ).
def : PgProjectField<"Temporal", "tproc.nameLit", "TypedStringLiteral",
                     "scalar", "", "name">;
def : PgProjectField<"Temporal", "tproc.executeName", "TargetIdentifierAtom",
                     "scalar", "", "executeName">;
def : PgProjectField<"Temporal", "tproc.proc", "TargetExpressionAtom",
                     "scalar", "", "proc">;
def : PgProjectField<"Temporal", "tproc.key", "TargetIdentifierAtom",
                     "scalar", "", "key">;
def : PgProjectField<"Temporal", "tproc.rawKey", "TargetIdentifierAtom",
                     "scalar", "", "rawKey">;
def : PgProjectField<"Temporal", "tproc.keyType", "FinalizedTargetType",
                     "scalar", "", "keyType">;
def : PgProjectField<"Temporal", "tproc.statusSuccess", "TargetExpressionAtom",
                     "scalar", "", "statusSuccess">;
def : PgProjectField<"Temporal", "tproc.replayPredicate",
                     "TargetExpressionAtom", "scalar", "", "replayPredicate">;
def : PgProjectField<"Temporal", "tproc.claimVar", "TargetIdentifierAtom",
                     "scalar", "", "claimVar">;
def : PgProjectField<"Temporal", "tproc.claimExpr", "TargetExpressionAtom",
                     "scalar", "", "claimExpr">;
def : PgProjectField<"Temporal", "tproc.claimMismatchPredicate",
                     "TargetExpressionAtom", "scalar", "",
                     "claimMismatchPredicate">;
def : PgProjectField<"Temporal", "tproc.keyClaimPredicate",
                     "TargetExpressionAtom", "scalar", "",
                     "keyClaimPredicate">;
def : PgProjectField<"Temporal", "tproc.donePredicate",
                     "TargetExpressionAtom", "scalar", "", "donePredicate">;
def : PgProjectField<"Temporal", "tproc.balancePredicate",
                     "TargetExpressionAtom", "scalar", "", "balancePredicate">;
def : PgProjectField<"Temporal", "tparams.item", "FinalizedTemporalParam",
                     "item", "params">;
def : PgProjectField<"Temporal", "tparam.name", "TargetIdentifierAtom",
                     "indexed", "params", "name">;
def : PgProjectField<"Temporal", "tparam.type", "FinalizedTargetType",
                     "indexed", "params", "type">;
def : PgProjectField<"Temporal", "computes.var", "TargetIdentifierAtom",
                     "indexed", "computes", "var">;
def : PgProjectField<"Temporal", "computes.expr", "TargetExpressionAtom",
                     "indexed", "computes", "expr">;
def : PgProjectField<"Temporal", "effectGroups.holdsPredicate",
                     "TargetExpressionAtom", "indexed", "groups",
                     "holdsPredicate">;
def : PgProjectField<"Temporal", "effectGroups.committedOrdinal",
                     "TargetExpressionAtom", "indexed", "groups",
                     "committedOrdinal">;
def : PgProjectField<"Temporal", "groupPostings.negativePredicate",
                     "TargetExpressionAtom", "nested", "groups",
                     "negativePredicate", -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.negativeMessage",
                     "TargetExpressionAtom", "nested", "groups",
                     "negativeMessage", -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.ledger",
                     "TypedStringLiteral", "nested", "groups", "ledger",
                     -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.party",
                     "TargetExpressionAtom", "nested", "groups", "party",
                     -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.currency",
                     "TargetExpressionAtom", "nested", "groups", "currency",
                     -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.signedAmount",
                     "TargetExpressionAtom", "nested", "groups",
                     "signedAmount", -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.entry",
                     "TypedStringLiteral", "nested", "groups", "entry",
                     -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.amount",
                     "TargetExpressionAtom", "nested", "groups", "amount",
                     -1, 0, 0, "effectGroups">;
def : PgProjectField<"Temporal", "groupPostings.memo",
                     "TypedStringLiteral", "nested", "groups", "memo",
                     -1, 0, 0, "effectGroups">;

// Effectful fields.  Gated and ungated recipe names are aliases over the same
// finalized values, so each pair names the same accessor.
multiclass PgEffectScalarPair<string suffix, string value, string member> {
  def : PgProjectField<"Effectful", "egatedProc." # suffix, value,
                       "scalar", "", member>;
  def : PgProjectField<"Effectful", "eungatedProc." # suffix, value,
                       "scalar", "", member>;
}
defm : PgEffectScalarPair<"name", "TargetIdentifierAtom", "name">;
// : the raw procedure name projected as a string literal for the
// posting-insert `proc` string.escape hook input (the reviewed  gate/revoke
// keep reading the raw `name` as TargetIdentifierAtom, unchanged).
defm : PgEffectScalarPair<"nameLit", "TypedStringLiteral", "name">;
defm : PgEffectScalarPair<"executeName", "TargetIdentifierAtom", "executeName">;
defm : PgEffectScalarPair<"attestName", "TargetIdentifierAtom", "attestName">;
defm : PgEffectScalarPair<"proc", "TargetExpressionAtom", "proc">;
defm : PgEffectScalarPair<"key", "TargetIdentifierAtom", "key">;
defm : PgEffectScalarPair<"rawKey", "TargetIdentifierAtom", "rawKey">;
defm : PgEffectScalarPair<"keyType", "FinalizedTargetType", "keyType">;
defm : PgEffectScalarPair<"statusSuccess", "TargetExpressionAtom",
                          "statusSuccess">;
defm : PgEffectScalarPair<"statusAttest", "TargetExpressionAtom",
                          "statusAttest">;
defm : PgEffectScalarPair<"replayPredicate", "TargetExpressionAtom",
                          "replayPredicate">;
defm : PgEffectScalarPair<"quorumRequirementPredicate", "TargetExpressionAtom",
                          "quorumRequirementPredicate">;
defm : PgEffectScalarPair<"selfRequirementPredicate", "TargetExpressionAtom",
                          "selfRequirementPredicate">;
defm : PgEffectScalarPair<"notFoundPredicate", "TargetExpressionAtom",
                          "notFoundPredicate">;
defm : PgEffectScalarPair<"idempotencyEntry", "TargetExpressionAtom",
                          "idempotencyEntry">;
defm : PgEffectScalarPair<"balancePredicate", "TargetExpressionAtom",
                          "balancePredicate">;

multiclass PgEffectAttestationPair<string suffix, string member,
                                   string transform = "identity"> {
  def : PgProjectField<"Effectful", "egatedProc." # suffix,
                       "TargetExpressionAtom", "attestation", "", member,
                       -1, 0, 0, "", transform>;
  def : PgProjectField<"Effectful", "eungatedProc." # suffix,
                       "TargetExpressionAtom", "attestation", "", member,
                       -1, 0, 0, "", transform>;
}
defm : PgEffectAttestationPair<"observerSet", "observerSetBinding">;
defm : PgEffectAttestationPair<"quorumM", "threshold", "to-string">;

multiclass PgEffectIndexedPair<string slot, string suffix, string value,
                               string container, string member> {
  def : PgProjectField<"Effectful", "egated" # slot # "." # suffix, value,
                       "indexed", container, member>;
  def : PgProjectField<"Effectful", "eungated" # slot # "." # suffix, value,
                       "indexed", container, member>;
}
defm : PgEffectIndexedPair<"Params", "name", "TargetIdentifierAtom",
                           "params", "name">;
defm : PgEffectIndexedPair<"Params", "type", "FinalizedTargetType",
                           "params", "type">;
defm : PgEffectIndexedPair<"Computes", "var", "TargetIdentifierAtom",
                           "computes", "var">;
defm : PgEffectIndexedPair<"Computes", "expr", "TargetExpressionAtom",
                           "computes", "expr">;
defm : PgEffectIndexedPair<"Postings", "negativePredicate",
                           "TargetExpressionAtom", "postings",
                           "negativePredicate">;
defm : PgEffectIndexedPair<"Postings", "negativeMessage",
                           "TargetExpressionAtom", "postings",
                           "negativeMessage">;
// : ledger/entry/memo are the raw spellings the executable INSERTs escape
// through the postgres.string.escape hook (Hook input type TypedStringLiteral);
// the decorative effect-ledger comment reads the same raw field Direct.
defm : PgEffectIndexedPair<"Postings", "ledger", "TypedStringLiteral",
                           "postings", "ledger">;
defm : PgEffectIndexedPair<"Postings", "party", "TargetExpressionAtom",
                           "postings", "party">;
defm : PgEffectIndexedPair<"Postings", "currency", "TargetExpressionAtom",
                           "postings", "currency">;
defm : PgEffectIndexedPair<"Postings", "signedAmount",
                           "TargetExpressionAtom", "postings", "signedAmount">;
defm : PgEffectIndexedPair<"Postings", "entry", "TypedStringLiteral",
                           "postings", "entry">;
defm : PgEffectIndexedPair<"Postings", "amount", "TargetExpressionAtom",
                           "postings", "amount">;
defm : PgEffectIndexedPair<"Postings", "memo", "TypedStringLiteral",
                           "postings", "memo">;
defm : PgEffectIndexedPair<"Postings", "direction", "TargetExpressionAtom",
                           "postings", "direction">;
defm : PgEffectIndexedPair<"Postings", "commentSuffix",
                           "TargetExpressionAtom", "postings", "commentSuffix">;
def : PgProjectField<"Effectful", "egatedPostingGuard.guard",
                     "TargetExpressionAtom", "parent-indexed", "postings",
                     "guard", -1, 0, 0, "egatedPostings">;
def : PgProjectField<"Effectful", "eungatedPostingGuard.guard",
                     "TargetExpressionAtom", "parent-indexed", "postings",
                     "guard", -1, 0, 0, "eungatedPostings">;

// Slot extents.
def : PgSlotExtent<"Evidence", "proc", "fixed", "", "", "", 1>;
def : PgSlotExtent<"Evidence", "param", "fixed", "", "", "", 1>;
def : PgSlotExtent<"Evidence", "params", "size", "params">;

def : PgSlotExtent<"Temporal", "tproc", "fixed", "", "", "", 1>;
def : PgSlotExtent<"Temporal", "tparam", "fixed", "", "", "", 1>;
def : PgSlotExtent<"Temporal", "tparams", "size", "params">;
def : PgSlotExtent<"Temporal", "computes", "size", "computes">;
def : PgSlotExtent<"Temporal", "effectGroups", "size", "groups">;
def : PgSlotExtent<"Temporal", "balanceAssertions", "size", "balances">;
def : PgSlotExtent<"Temporal", "groupPostings", "nested-size", "groups",
                   "postings", "effectGroups">;
//  (Path A): per-nested-posting memo INSERT variant, selected from the
// finalized FinalizedPostingMemo fact (effectGroups[g].finalizedPostings[p]
// .memoPresence). The generator's memo-present/absent temporal dispatch walks
// the effectGroups+groupPostings ctx indices.
def : PgSlotExtent<"Temporal", "groupPostingsMemo", "memo-present", "groups",
                   "memo", "effectGroups">;
def : PgSlotExtent<"Temporal", "groupPostingsNoMemo", "memo-absent", "groups",
                   "memo", "effectGroups">;

multiclass PgEffectExtentPair<string suffix, string kind,
                              string container = "", string member = "",
                              string parent = "", int fixed = 0> {
  def : PgSlotExtent<"Effectful", "egated" # suffix, kind, container, member,
                     "egated" # parent, fixed>;
  def : PgSlotExtent<"Effectful", "eungated" # suffix, kind, container, member,
                     "eungated" # parent, fixed>;
}
defm : PgEffectExtentPair<"Proc", "fixed", "", "", "", 1>;
defm : PgEffectExtentPair<"WithAttestation", "member", "",
                          "withAttestationExtent">;
defm : PgEffectExtentPair<"WithoutAttestation", "member", "",
                          "withoutAttestationExtent">;
defm : PgEffectExtentPair<"Params", "size", "params">;
defm : PgEffectExtentPair<"Computes", "size", "computes">;
defm : PgEffectExtentPair<"Postings", "size", "postings">;
defm : PgEffectExtentPair<"Balances", "size", "balances">;
defm : PgEffectExtentPair<"PostingGuard", "comparison-present", "", "",
                          "Postings">;
defm : PgEffectExtentPair<"PostingDirect", "comparison-absent", "", "",
                          "Postings">;
//  (Path A): the per-posting memo INSERT variant, selected from the
// finalized FinalizedPostingMemo::{Present,Absent} fact (posting[i].memoPresence)
// — NOT a below-waist memo string test. Mirrors PostingGuard/PostingDirect.
defm : PgEffectExtentPair<"PostingMemo", "memo-present", "", "",
                          "Postings">;
defm : PgEffectExtentPair<"PostingNoMemo", "memo-absent", "", "",
                          "Postings">;

def : PgSlotExtent<"Schema", "tschPostingsMemo", "schema-memo">;
def : PgSlotExtent<"Schema", "eqschPostingsMemo", "schema-memo">;
def : PgSlotExtent<"Schema", "esschPostingsMemo", "schema-memo">;
def : PgSlotExtent<"Schema", "tschPostingsPlain", "schema-plain">;
def : PgSlotExtent<"Schema", "eqschPostingsPlain", "schema-plain">;
def : PgSlotExtent<"Schema", "esschPostingsPlain", "schema-plain">;

// Ordered slots.
def : PgSlotItemOrder<"Evidence", "params", "indexed-ordinal", "params">;
def : PgSlotItemOrder<"Temporal", "tparams", "indexed-ordinal", "params">;
def : PgSlotItemOrder<"Temporal", "computes", "indexed-ordinal", "computes">;
def : PgSlotItemOrder<"Temporal", "effectGroups", "indexed-ordinal", "groups">;
def : PgSlotItemOrder<"Temporal", "balanceAssertions", "indexed-ordinal",
                      "balances">;
def : PgSlotItemOrder<"Temporal", "groupPostings", "nested-ordinal", "groups",
                      "effectGroups">;
def : PgSlotItemOrder<"Effectful", "egatedParams", "indexed-ordinal", "params">;
def : PgSlotItemOrder<"Effectful", "eungatedParams", "indexed-ordinal",
                      "params">;
def : PgSlotItemOrder<"Effectful", "egatedComputes", "indexed-ordinal",
                      "computes">;
def : PgSlotItemOrder<"Effectful", "eungatedComputes", "indexed-ordinal",
                      "computes">;
def : PgSlotItemOrder<"Effectful", "egatedPostings", "indexed-ordinal",
                      "postings">;
def : PgSlotItemOrder<"Effectful", "eungatedPostings", "indexed-ordinal",
                      "postings">;
def : PgSlotItemOrder<"Effectful", "egatedBalances", "indexed-ordinal",
                      "balances">;
def : PgSlotItemOrder<"Effectful", "eungatedBalances", "indexed-ordinal",
                      "balances">;
