//===- PostgresTemporalIdiomRecipes.td -  PG temporal recipe layer -----===//
//
// The declarative recipe layer for the PostgreSQL TEMPORAL idiom (the
// per-policy quorum acceptance rail), replacing the handwritten
// `neutrino::postgres_model::materializeTemporalIdiom`. Exact resolution key:
//   (postgres, QuorumAcceptance.PerPolicy, Temporal, NotApplicable)
// mirroring the merged Solidity sibling `solidity.temporal.contract.v1`
// (SolidityTemporalIdiomRecipes.td) for cross-backend key consistency.
//
// Same discipline as the  evidence extraction: the recipe COMPOSES existing
// typed PgStmt/PgFunction/PgProcedure factories declaratively; it authors no
// construction and makes no semantic decision. Every target-facing value (the
// SQL-quoted procedure literal, the replay/claim/group/balance guard predicates,
// the compute expressions, each posting's already-lowered ledger/posting
// operands) is an already-lowered finalized VALUE synthesized at the
// finalized-value boundary by the provider-side `computeTemporalInputs` (from the
// verified FinalizedProjectionSequence — no CoordinationPlan read) and bound by
// `Direct`. The .td owns ORDER + the repeated-group composition (ForEach over
// computes/effectGroups/balanceAssertions, RelatedMany over each group's
// postings, OptionalOp over the optional posting memo). Fixed diagnostics + the
// procedure header/flags are `.td`-owned BuilderArgs. No new printer node
// (rendering stays the existing byte-identical model path). The per-policy
// security gate/revoke are the reviewed  primitives (buildTemporalAcceptGate
// / temporalAcceptRevoke) invoked by the package-local security resolver during
// node construction, ordered declaratively: gate -> execute -> revoke.
//
// A stackable fragment `include`d by the package root (PostgresIdiomRecipes.td).
//
//===----------------------------------------------------------------------===//

// ---- finalized inputs (already-lowered VALUES from computeTemporalInputs) ----

// The temporal procedure's decided per-procedure target values. All synthesized
// at the finalized-value boundary; never re-derived downstream.
def FinalizedTemporalProcedure : FinalizedType<"FinalizedTemporalProcedure", [
  FinalizedField<"name", "TargetIdentifierAtom">,            // raw procedureNamespace (gate/revoke)
  FinalizedField<"nameLit", "TypedStringLiteral">,           // : raw name as string literal (postingInsert proc hook input)
  FinalizedField<"executeName", "TargetIdentifierAtom">,     // execute_<name>
  FinalizedField<"proc", "TargetExpressionAtom">,            // sqlQuote(name)
  FinalizedField<"key", "TargetIdentifierAtom">,             // p_<replayKey> (pkey)
  FinalizedField<"rawKey", "TargetIdentifierAtom">,          // <replayKey> (postingInsert raw key)
  FinalizedField<"keyType", "FinalizedTargetType">,          // sqlType(keyType)
  FinalizedField<"statusSuccess", "TargetExpressionAtom">,   // projected success status atom
  FinalizedField<"replayPredicate", "TargetExpressionAtom">, // EXISTS coordination_status AND status
  FinalizedField<"claimVar", "TargetIdentifierAtom">,        // v_claim (fixed PL/pgSQL variable)
  FinalizedField<"claimExpr", "TargetExpressionAtom">,       // neu_execution_claim(...) assigned to v_claim
  FinalizedField<"claimMismatchPredicate", "TargetExpressionAtom">, // EXISTS key_claim ... execution_claim <> v_claim
  FinalizedField<"keyClaimPredicate", "TargetExpressionAtom">,      // v_progress AND NOT EXISTS key_claim
  FinalizedField<"donePredicate", "TargetExpressionAtom">,   // AND of the committed_group EXISTS terms
  FinalizedField<"balancePredicate", "TargetExpressionAtom"> // SUM(signed_amount) ... <> 0 (same per assertion)
]>;

// One typed callable parameter, already lowered (`p_<name>`, sqlType).
def FinalizedTemporalParam : FinalizedType<"FinalizedTemporalParam", [
  FinalizedField<"name", "TargetIdentifierAtom">,
  FinalizedField<"type", "FinalizedTargetType">,
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// One computed value: `v_<name> := <expr>;` plus its `v_<name> bigint` decl.
def FinalizedTemporalCompute : FinalizedType<"FinalizedTemporalCompute", [
  FinalizedField<"var", "TargetIdentifierAtom">,             // v_<name>
  FinalizedField<"expr", "TargetExpressionAtom">,            // already-lowered SQL expression
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// One effect group (repeated). `holdsPredicate` is the whole group guard cond
// `(EXISTS quorum_acceptance ... policy=...) AND NOT committed(gi)`;
// `committedOrdinal` is the per-group committed_group group_ordinal operand
// (proc/key are procedure-level).
def FinalizedTemporalGroup : FinalizedType<"FinalizedTemporalGroup", [
  FinalizedField<"holdsPredicate", "TargetExpressionAtom">,
  FinalizedField<"committedOrdinal", "TargetExpressionAtom">,
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// One ledger posting inside a group (related to its parent group). All operands
// already lowered. `negativeMessage` is the per-posting RAISE text
// (`negative money for <name>`). postingInsert proc/key are procedure-level.
def FinalizedTemporalPosting : FinalizedType<"FinalizedTemporalPosting", [
  FinalizedField<"negativePredicate", "TargetExpressionAtom">, // (amount) < 0
  FinalizedField<"negativeMessage", "TargetExpressionAtom">,   // negative money for <name>
  FinalizedField<"ledger", "TypedStringLiteral">,            // : Hook-escaped in ledger-upsert/posting-insert
  FinalizedField<"party", "TargetExpressionAtom">,
  FinalizedField<"currency", "TargetExpressionAtom">,
  FinalizedField<"signedAmount", "TargetExpressionAtom">,
  FinalizedField<"entry", "TypedStringLiteral">,             // : postingInsert entry (Hook-escaped)
  FinalizedField<"amount", "TargetExpressionAtom">,          // postingInsert amount
  FinalizedField<"memo", "TypedStringLiteral">,              // : postingInsert memo (Hook-escaped)
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// One balance assertion (repeated). Carries only the ordinal — the guard
// predicate is identical per assertion (procedure-level `balancePredicate`); the
// loop count drives one guard emission per assertion.
def FinalizedTemporalBalance : FinalizedType<"FinalizedTemporalBalance", [
  FinalizedField<"ordinal", "ParamOrdinal">
]>;
// : per-posting memo INSERT variant markers (RelatedOptional; exactly one
// present per posting, from the finalized FinalizedPostingMemo fact).
def FinalizedTemporalPostingMemo : FinalizedType<"FinalizedTemporalPostingMemo">;
def FinalizedTemporalPostingNoMemo : FinalizedType<"FinalizedTemporalPostingNoMemo">;

// ---- temporal recipe target nodes (map to existing model factories) --------
//
// `builderKind` names an existing (or newly-added-generic) typed factory;
// `BuilderArgs` carries the fixed `.td`-owned lexical shape (diagnostics, the
// status-write DO-UPDATE flag). The mechanical builder generator emits the
// plumbing; no per-construct branch.

// A guarded block -> PgStmt::ifThen(cond, body).
def PgTemporalGuardNode : TargetNode<"PgTemporalGuard", "PgStatement", [
  TargetField<"cond", "value", "TargetExpressionAtom">,
  TargetField<"body", "nodes", "PgStatement", "many", 1, "unbounded">
], "if-then", []>;

// A blank separator -> PgStmt::blank().
def PgTemporalBlankNode : TargetNode<"PgTemporalBlank", "PgStatement", [],
                                     "blank", []>;

// Fixed diagnostics -> PgStmt::raise(message).
def PgTemporalReplayRaiseNode : TargetNode<"PgTemporalReplayRaise", "PgStatement",
                                           [], "raise", ["replay"]>;
def PgTemporalClaimMismatchRaiseNode
    : TargetNode<"PgTemporalClaimMismatchRaise", "PgStatement", [], "raise",
                 ["claim mismatch"]>;
// `RAISE EXCEPTION '<msg>';` with a per-posting dynamic message -> raise(*msg).
def PgTemporalNegativeRaiseNode
    : TargetNode<"PgTemporalNegativeRaise", "PgStatement", [
  TargetField<"msg", "value", "TargetExpressionAtom">
], "raise-value", []>;
// `RAISE EXCEPTION 'not balanced for %', <arg>;` -> PgStmt::raise(msg, arg).
// The message is fixed `.td`-owned BuilderArg data; the interpolated arg (the
// idempotency key) is an already-lowered Direct value.
def PgTemporalUnbalancedRaiseNode
    : TargetNode<"PgTemporalUnbalancedRaise", "PgStatement", [
  TargetField<"arg", "value", "TargetIdentifierAtom">
], "raise-arg", ["not balanced for %"]>;

// A variable assignment `<var> := <expr>;` -> PgStmt::assign(var, expr).
def PgTemporalAssignNode : TargetNode<"PgTemporalAssign", "PgStatement", [
  TargetField<"var", "value", "TargetIdentifierAtom">,
  TargetField<"expr", "value", "TargetExpressionAtom">
], "assign", []>;

// The progress flag `v_progress := <bool>;` -> PgStmt::progressFlag(bool). The
// boolean literal is fixed `.td`-owned BuilderArg data.
def PgTemporalProgressFalseNode
    : TargetNode<"PgTemporalProgressFalse", "PgStatement", [], "progress-flag",
                 ["false"]>;
def PgTemporalProgressTrueNode
    : TargetNode<"PgTemporalProgressTrue", "PgStatement", [], "progress-flag",
                 ["true"]>;

// A ledger upsert -> PgStmt::ledgerUpsert(ledger, party, currency, signedAmount).
def PgTemporalLedgerUpsertNode : TargetNode<"PgTemporalLedgerUpsert", "PgStatement", [
  TargetField<"ledger", "leaf", "EscapedStringLiteral">,
  TargetField<"party", "value", "TargetExpressionAtom">,
  TargetField<"currency", "value", "TargetExpressionAtom">,
  TargetField<"signedAmount", "value", "TargetExpressionAtom">
], "ledger-upsert", []>;

// A posting insert. Two byte-distinct variants selected per-posting from the
// finalized FinalizedPostingMemo fact. proc/entry/ledger (and memo) are
// string.escape-hook-escaped leaves.
def PgTemporalPostingInsertNode : TargetNode<"PgTemporalPostingInsert", "PgStatement", [
  TargetField<"proc", "leaf", "EscapedStringLiteral">,
  TargetField<"entry", "leaf", "EscapedStringLiteral">,
  TargetField<"ledger", "leaf", "EscapedStringLiteral">,
  TargetField<"party", "value", "TargetExpressionAtom">,
  TargetField<"amount", "value", "TargetExpressionAtom">,
  TargetField<"currency", "value", "TargetExpressionAtom">,
  TargetField<"signedAmount", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">
], "posting-insert", []>;
def PgTemporalPostingInsertWithMemoNode
    : TargetNode<"PgTemporalPostingInsertWithMemo", "PgStatement", [
  TargetField<"proc", "leaf", "EscapedStringLiteral">,
  TargetField<"entry", "leaf", "EscapedStringLiteral">,
  TargetField<"ledger", "leaf", "EscapedStringLiteral">,
  TargetField<"party", "value", "TargetExpressionAtom">,
  TargetField<"amount", "value", "TargetExpressionAtom">,
  TargetField<"currency", "value", "TargetExpressionAtom">,
  TargetField<"signedAmount", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"memo", "leaf", "EscapedStringLiteral">
], "posting-insert-with-memo", []>;

// A committed_group insert -> PgStmt::committedGroupInsert(proc, key, ordinal).
def PgTemporalCommittedGroupInsertNode
    : TargetNode<"PgTemporalCommittedGroupInsert", "PgStatement", [
  TargetField<"proc", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"ordinal", "value", "TargetExpressionAtom">
], "committed-group-insert", []>;

// A key_claim insert -> PgStmt::keyClaimInsert(proc, key).
def PgTemporalKeyClaimInsertNode : TargetNode<"PgTemporalKeyClaimInsert", "PgStatement", [
  TargetField<"proc", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">
], "key-claim-insert", []>;

// The terminal reconciled status write -> PgStmt::statusWrite(proc, key,
// statusSuccess, /*doUpdate=*/true).
def PgTemporalStatusWriteNode : TargetNode<"PgTemporalStatusWrite", "PgStatement", [
  TargetField<"proc", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"statusAtom", "value", "TargetExpressionAtom">
], "status-write-update", []>;

// One typed callable parameter -> PgParam{name, type}.
def PgTemporalParamNode : TargetNode<"PgTemporalParam", "PgTemporalParamCat", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"type", "value", "FinalizedTargetType">
], "param", []>;

// The reviewed  per-policy quorum-accept gate ->
// buildTemporalAcceptGate(policyCarrier, name, key, keyType), invoked by the
// package-local security resolver during construction. A PgCallable.
def PgTemporalGateNode : TargetNode<"PgTemporalGate", "PgProcedurePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"keyType", "value", "FinalizedTargetType">
], "temporal-gate", []>;

// The reviewed  revoke trailer -> temporalAcceptRevoke(name, keyType),
// invoked by the package-local security resolver during construction. A PgRevoke.
def PgTemporalRevokeNode : TargetNode<"PgTemporalRevoke", "PgProcedurePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"keyType", "value", "FinalizedTargetType">
], "temporal-revoke", []>;

// One execute-function DECLARE entry -> PgDeclaration{name, type, ""}. The
// per-compute declaration takes its name from the finalized compute var (type is
// the fixed `.td`-owned `bigint`); the two fixed entries own both name + type.
def PgTemporalComputeDeclNode : TargetNode<"PgTemporalComputeDecl", "PgTemporalDeclCat", [
  TargetField<"name", "value", "TargetIdentifierAtom">
], "declaration", ["bigint"]>;
def PgTemporalClaimDeclNode : TargetNode<"PgTemporalClaimDecl", "PgTemporalDeclCat",
                                         [], "declaration-fixed",
                                         ["v_claim", "text"]>;
def PgTemporalProgressDeclNode
    : TargetNode<"PgTemporalProgressDecl", "PgTemporalDeclCat", [],
                 "declaration-fixed", ["v_progress", "boolean"]>;

// The temporal `execute_` callable -> PgFunction{name, params, declare=true,
// declarations, body}. The DECLARE block (one `v_<compute> bigint` per compute
// then `v_claim text` / `v_progress boolean`) is composed by the recipe (ForEach
// over the finalized computes + the two fixed entries) and fed through the shared
// PgFunction declaration carrier by the `temporal-callable` builder.
def PgTemporalCallableSigNode
    : TargetNode<"PgTemporalCallableSig", "PgCallablePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"params", "nodes", "PgTemporalParamCat", "many", 0, "unbounded">
], "callable-signature", []>;
def PgTemporalDeclareSectionNode
    : TargetNode<"PgTemporalDeclareSection", "PgCallablePart", [
  TargetField<"declarations", "nodes", "PgTemporalDeclCat", "many", 2,
              "unbounded">
], "callable-declaration", []>;
def PgTemporalExecuteCallableNode
    : TargetNode<"PgTemporalExecuteCallable", "PgProcedurePart", [
  TargetField<"callableParts", "nodes", "PgCallablePart", "many", 4, "4">
], "callable-root", []>;
def PgTemporalHeaderNode
    : TargetNode<"PgTemporalHeader", "PgProcedurePart", [],
                 "common-header", [
  "-- Generated by the Neutrino Translator from verified MLIR ( temporal).",
  "-- Idempotent + atomic (a function body runs in a single transaction)."
]>;

// The temporal PgProcedure -> {evidenceOnly=false, gated, header, functions=[gate,
// execute], revoke}. The header banner is fixed `.td`-owned BuilderArg data (one
// arg per comment line); the evidenceOnly=false + gated flags are owned by the
// `temporal-procedure` builder kind.
def PgTemporalProcedureNode : TargetNode<"PgTemporalProcedure", "PgTemporalProc", [
  TargetField<"procedureParts", "nodes", "PgProcedurePart", "many", 5, "5">
], "temporal-procedure", []>;

// ---- recipes ---------------------------------------------------------------

// One typed callable parameter.
def PgTemporalParamRecipe : TargetIdiomRecipe<
  "postgres.temporal.param.v1", "postgres",
  "TemporalParam", "NotApplicable", "NotApplicable",
  [One<"tparam", "FinalizedTemporalParam">],
  "PgTemporalParamCat", CardinalityOne,
  Sequence<[
    Emit<"PgTemporalParam", [
      Direct<"name", "tparam.name">,
      Direct<"type", "tparam.type">
    ]>
  ]>
>;

// The temporal acceptance procedure — the exact-key entry for the temporal rail.
def PgTemporalProcedureRecipe : TargetIdiomRecipe<
  "postgres.temporal.procedure.v1", "postgres",
  "QuorumAcceptance.PerPolicy", "Temporal", "NotApplicable",
  [One<"tproc", "FinalizedTemporalProcedure">,
   Many<"tparams", "FinalizedTemporalParam", 0, "unbounded", "tparams.ordinal">,
   Many<"computes", "FinalizedTemporalCompute", 0, "unbounded", "computes.ordinal">,
   Many<"effectGroups", "FinalizedTemporalGroup", 1, "unbounded", "effectGroups.ordinal">,
   RelatedMany<"groupPostings", "FinalizedTemporalPosting", 1, "unbounded",
               "groupPostings.ordinal", "effectGroups">,
   RelatedOptional<"groupPostingsMemo", "FinalizedTemporalPostingMemo",
                   "groupPostings">,
   RelatedOptional<"groupPostingsNoMemo", "FinalizedTemporalPostingNoMemo",
                   "groupPostings">,
   Many<"balanceAssertions", "FinalizedTemporalBalance", 0, "unbounded",
        "balanceAssertions.ordinal">],
  "PgTemporalProc", CardinalityOne,
  Sequence<[
    Emit<"PgTemporalProcedure", [
      Nested<"procedureParts", Sequence<[
        Emit<"PgTemporalHeader", []>,
        Emit<"PgTemporalGate", [
          Direct<"name", "tproc.name">,
          Direct<"key", "tproc.key">,
          Direct<"keyType", "tproc.keyType">
        ]>,
        Emit<"PgProcedureSeparator", []>,
        Emit<"PgTemporalExecuteCallable", [
          Nested<"callableParts", Sequence<[
            Emit<"PgTemporalCallableSig", [
              Direct<"name", "tproc.executeName">,
              Nested<"params", Sequence<[
                ForEach<"tparams", Sequence<[
                  Call<"postgres.temporal.param.v1",
                       [Direct<"tparam", "tparams.item">]>
                ]>>
              ]>>
            ]>,
            Emit<"PgTemporalDeclareSection", [
              Nested<"declarations", Sequence<[
                ForEach<"computes", Sequence<[
                  Emit<"PgTemporalComputeDecl", [
                    Direct<"name", "computes.var">
                  ]>
                ]>>,
                Emit<"PgTemporalClaimDecl", []>,
                Emit<"PgTemporalProgressDecl", []>
              ]>>
            ]>,
            Emit<"PgCallableBody", [
              Nested<"body", Sequence<[
            // (1) replay guard
            Emit<"PgTemporalGuard", [
              Direct<"cond", "tproc.replayPredicate">,
              Nested<"body", Sequence<[Emit<"PgTemporalReplayRaise", []>]>>
            ]>,
            Emit<"PgTemporalBlank", []>,
            // (3) v_claim := neu_execution_claim(...)
            Emit<"PgTemporalAssign", [
              Direct<"var", "tproc.claimVar">,
              Direct<"expr", "tproc.claimExpr">
            ]>,
            // (4) claim-mismatch guard
            Emit<"PgTemporalGuard", [
              Direct<"cond", "tproc.claimMismatchPredicate">,
              Nested<"body", Sequence<[Emit<"PgTemporalClaimMismatchRaise", []>]>>
            ]>,
            Emit<"PgTemporalBlank", []>,
            // (6) compute assigns
            ForEach<"computes", Sequence<[
              Emit<"PgTemporalAssign", [
                Direct<"var", "computes.var">,
                Direct<"expr", "computes.expr">
              ]>
            ]>>,
            // (7) v_progress := false
            Emit<"PgTemporalProgressFalse", []>,
            Emit<"PgTemporalBlank", []>,
            // (9) per-group guarded legs
            ForEach<"effectGroups", Sequence<[
              Emit<"PgTemporalGuard", [
                Direct<"cond", "effectGroups.holdsPredicate">,
                Nested<"body", Sequence<[
                  ForEach<"groupPostings", Sequence<[
                    Emit<"PgTemporalGuard", [
                      Direct<"cond", "groupPostings.negativePredicate">,
                      Nested<"body", Sequence<[
                        Emit<"PgTemporalNegativeRaise", [
                          Direct<"msg", "groupPostings.negativeMessage">
                        ]>
                      ]>>
                    ]>,
                    Emit<"PgTemporalLedgerUpsert", [
                      Hook<"ledger", "postgres.string.escape", "groupPostings.ledger">,
                      Direct<"party", "groupPostings.party">,
                      Direct<"currency", "groupPostings.currency">,
                      Direct<"signedAmount", "groupPostings.signedAmount">
                    ]>,
                    OptionalOp<"groupPostingsMemo", Sequence<[
                      Emit<"PgTemporalPostingInsertWithMemo", [
                        Hook<"proc", "postgres.string.escape", "tproc.nameLit">,
                        Hook<"entry", "postgres.string.escape", "groupPostings.entry">,
                        Hook<"ledger", "postgres.string.escape", "groupPostings.ledger">,
                        Direct<"party", "groupPostings.party">,
                        Direct<"amount", "groupPostings.amount">,
                        Direct<"currency", "groupPostings.currency">,
                        Direct<"signedAmount", "groupPostings.signedAmount">,
                        Direct<"key", "tproc.rawKey">,
                        Hook<"memo", "postgres.string.escape", "groupPostings.memo">
                      ]>
                    ]>>,
                    OptionalOp<"groupPostingsNoMemo", Sequence<[
                      Emit<"PgTemporalPostingInsert", [
                        Hook<"proc", "postgres.string.escape", "tproc.nameLit">,
                        Hook<"entry", "postgres.string.escape", "groupPostings.entry">,
                        Hook<"ledger", "postgres.string.escape", "groupPostings.ledger">,
                        Direct<"party", "groupPostings.party">,
                        Direct<"amount", "groupPostings.amount">,
                        Direct<"currency", "groupPostings.currency">,
                        Direct<"signedAmount", "groupPostings.signedAmount">,
                        Direct<"key", "tproc.rawKey">
                      ]>
                    ]>>
                  ]>>,
                  Emit<"PgTemporalCommittedGroupInsert", [
                    Direct<"proc", "tproc.proc">,
                    Direct<"key", "tproc.key">,
                    Direct<"ordinal", "effectGroups.committedOrdinal">
                  ]>,
                  Emit<"PgTemporalProgressTrue", []>
                ]>>
              ]>,
              Emit<"PgTemporalBlank", []>
            ]>>,
            // (10) key_claim pin
            Emit<"PgTemporalGuard", [
              Direct<"cond", "tproc.keyClaimPredicate">,
              Nested<"body", Sequence<[
                Emit<"PgTemporalKeyClaimInsert", [
                  Direct<"proc", "tproc.proc">,
                  Direct<"key", "tproc.key">
                ]>
              ]>>
            ]>,
            Emit<"PgTemporalBlank", []>,
            // (12-14) terminal: done guard wrapping balance checks + status write
            Emit<"PgTemporalGuard", [
              Direct<"cond", "tproc.donePredicate">,
              Nested<"body", Sequence<[
                ForEach<"balanceAssertions", Sequence<[
                  Emit<"PgTemporalGuard", [
                    Direct<"cond", "tproc.balancePredicate">,
                    Nested<"body", Sequence<[
                      Emit<"PgTemporalUnbalancedRaise", [
                        Direct<"arg", "tproc.key">
                      ]>
                    ]>>
                  ]>
                ]>>,
                Emit<"PgTemporalStatusWrite", [
                  Direct<"proc", "tproc.proc">,
                  Direct<"key", "tproc.key">,
                  Direct<"statusAtom", "tproc.statusSuccess">
                ]>
              ]>>
            ]>
              ]>>
            ]>,
            Emit<"PgCallableClose", []>
          ]>>
        ]>,
        Emit<"PgTemporalRevoke", [
          Direct<"name", "tproc.name">,
          Direct<"keyType", "tproc.keyType">
        ]>
      ]>>
    ]>
  ]>
>;
