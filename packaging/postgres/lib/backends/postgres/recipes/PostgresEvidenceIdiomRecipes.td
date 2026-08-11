//===- PostgresEvidenceIdiomRecipes.td -  PG evidence recipe layer -----===//
//
// The declarative recipe layer for the PostgreSQL EVIDENCE idiom (the
// QuorumAcceptance.Single acceptance rail), replacing the handwritten
// `neutrino::postgres_model::materializeEvidenceIdiom`. Exact resolution key:
//   (postgres, QuorumAcceptance.Single, Evidence, NotApplicable)
//
// Mirrors Impl A's merged Solidity evidence extraction (): the recipe
// COMPOSES existing typed model factories declaratively; it authors no
// construction. Every target-facing value (the SQL-quoted procedure literal, the
// quorum/replay guard predicates, the reconciled status atom, the gate observer
// set / quorum threshold) is an already-lowered finalized VALUE synthesized at
// the finalized-value boundary by the provider-side `computeEvidenceInputs`
// (from the verified FinalizedProjectionSequence) and bound by `Direct` — no
// hook, no spec-contract change. The fixed diagnostics + status shape are
// `.td`-owned BuilderArgs. No new printer node (rendering stays the existing
// byte-identical model path). The security gate/revoke are the reviewed
// primitives invoked by the package-local security resolver during node
// construction, ordered declaratively: gate -> execute -> revoke.
//
// A stackable fragment `include`d by the package root (PostgresIdiomRecipes.td).
//
//===----------------------------------------------------------------------===//

// ---- finalized inputs (already-lowered VALUES from computeEvidenceInputs) ----

// The evidence procedure's decided target values. All synthesized at the
// finalized-value boundary (procedureNamespace/replayKey/quorum binding/status
// atom), never re-derived downstream.
def FinalizedEvidenceProcedure : FinalizedType<"FinalizedEvidenceProcedure", [
  FinalizedField<"name", "TargetIdentifierAtom">,          // raw procedureNamespace (gate/revoke)
  FinalizedField<"executeName", "TargetIdentifierAtom">,   // execute_<name>
  FinalizedField<"procLiteral", "TargetExpressionAtom">,   // sqlQuote(name)
  FinalizedField<"key", "TargetIdentifierAtom">,           // p_<replayKey>
  FinalizedField<"keyType", "FinalizedTargetType">,        // sqlType(keyType)
  FinalizedField<"observerSet", "TargetExpressionAtom">,   // sqlQuote(observerSet)
  FinalizedField<"quorumM", "TargetExpressionAtom">,       // to_string(quorumM)
  FinalizedField<"quorumPredicate", "TargetExpressionAtom">, // NOT EXISTS (...)
  FinalizedField<"replayPredicate", "TargetExpressionAtom">, // NOT FOUND
  FinalizedField<"statusAtom", "TargetExpressionAtom">     // reconciled
]>;

// One typed callable parameter, already lowered (`p_<name>`, sqlType).
def FinalizedEvidenceParam : FinalizedType<"FinalizedEvidenceParam", [
  FinalizedField<"name", "TargetIdentifierAtom">,
  FinalizedField<"type", "FinalizedTargetType">,
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// ---- evidence recipe target nodes (map to existing model factories) --------
//
// `builderKind` names an existing typed factory; `BuilderArgs` carries the fixed
// `.td`-owned lexical shape (diagnostics, the reconciled DO-NOTHING flag). The
// mechanical builder generator emits the plumbing; no per-construct branch.

// One typed callable parameter -> PgParam{name, type}.
def PgEvidenceParamNode : TargetNode<"PgEvidenceParam", "PgEvidenceParamCat", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"type", "value", "FinalizedTargetType">
], "param", []>;

// A guarded block -> PgStmt::ifThen(cond, body). `cond` is a synthesized
// predicate value; `body` is the nested then-branch (the RAISE).
def PgEvidenceGuardNode : TargetNode<"PgEvidenceGuard", "PgStatement", [
  TargetField<"cond", "value", "TargetExpressionAtom">,
  TargetField<"body", "nodes", "PgStatement", "many", 1, "1">
], "if-then", []>;

// A revert -> PgStmt::raise(message). The message is a fixed `.td`-owned
// BuilderArg (the diagnostic).
def PgQuorumNotAcceptedNode : TargetNode<"PgQuorumNotAccepted", "PgStatement", [],
                                         "raise", ["quorum not accepted"]>;
def PgReplayNode : TargetNode<"PgReplay", "PgStatement", [], "raise", ["replay"]>;

// A blank separator -> PgStmt::blank().
def PgEvidenceBlankNode : TargetNode<"PgEvidenceBlank", "PgStatement", [],
                                     "blank", []>;

// The evidence-only claim banner -> the  generated EvidenceClaimComment
// builder (the handwritten factory is retired).
def PgEvidenceClaimNode : TargetNode<"PgEvidenceClaim", "PgStatement", [],
                                     "evidence-claim", []>;

// The reconciled DO-NOTHING status write ->
// PgStmt::statusWrite(procLiteral, key, statusAtom, /*doUpdate=*/false).
def PgEvidenceStatusWriteNode
    : TargetNode<"PgEvidenceStatusWrite", "PgStatement", [
  TargetField<"proc", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"statusAtom", "value", "TargetExpressionAtom">
], "status-write", []>;

// Closed callable/procedure root composition. The recipe grammar, rather than a
// provider post-pass, emits these nodes in final render order.
def PgEvidenceCallableSigNode
    : TargetNode<"PgEvidenceCallableSig", "PgCallablePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"params", "nodes", "PgEvidenceParamCat", "many", 0, "unbounded">
], "callable-signature", []>;
def PgCallableBodyNode : TargetNode<"PgCallableBody", "PgCallablePart", [
  TargetField<"body", "nodes", "PgStatement", "many", 1, "unbounded">
], "callable-body", []>;
def PgCallableCloseNode
    : TargetNode<"PgCallableClose", "PgCallablePart", [],
                 "callable-close", []>;
def PgProcedureSeparatorNode
    : TargetNode<"PgProcedureSeparator", "PgProcedurePart", [],
                 "procedure-separator", []>;
def PgEvidenceHeaderNode
    : TargetNode<"PgEvidenceHeader", "PgProcedurePart", [],
                 "evidence-header", [
  "-- Generated by the Neutrino Translator from verified MLIR.",
  "-- EVIDENCE-ONLY coordination: records accepted attested evidence by instance",
  "-- key and moves NO ledger value. Idempotent + atomic (single transaction)."
]>;

// The reviewed  quorum-accept gate -> buildQuorumAcceptGate(name, key,
// keyType, observerSet, quorumM), invoked by the package-local security resolver
// during construction. A PgCallable.
def PgQuorumGateNode : TargetNode<"PgQuorumGate", "PgProcedurePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"keyType", "value", "FinalizedTargetType">,
  TargetField<"observerSet", "value", "TargetExpressionAtom">,
  TargetField<"quorumM", "value", "TargetExpressionAtom">
], "quorum-gate", []>;

// The reviewed  revoke trailer -> quorumAcceptRevoke(name, keyType), invoked
// by the package-local security resolver during construction. A PgRevoke.
def PgQuorumRevokeNode : TargetNode<"PgQuorumRevoke", "PgProcedurePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"keyType", "value", "FinalizedTargetType">
], "quorum-revoke", []>;

// The evidence `execute_` callable -> PgFunction{name, params, body}.
def PgExecuteCallableNode : TargetNode<"PgExecuteCallable", "PgProcedurePart", [
  TargetField<"callableParts", "nodes", "PgCallablePart", "many", 3, "3">
], "callable-root", []>;

// The evidence PgProcedure -> {evidenceOnly, gated, header, functions=[gate,
// execute], revoke}. Assembles the security gate, the execute callable, and the
// revoke in that declared order. The evidence-only banner header is fixed
// `.td`-owned data (one BuilderArg per comment line); the evidence-only + gated
// semantic flags are owned by the `evidence-procedure` builder kind itself.
def PgEvidenceProcedureNode : TargetNode<"PgEvidenceProcedure", "PgEvidenceProc", [
  TargetField<"procedureParts", "nodes", "PgProcedurePart", "many", 5, "5">
], "evidence-procedure", []>;

// ---- recipes ---------------------------------------------------------------

// One typed callable parameter.
def PgEvidenceParamRecipe : TargetIdiomRecipe<
  "postgres.evidence.param.v1", "postgres",
  "EvidenceParam", "NotApplicable", "NotApplicable",
  [One<"param", "FinalizedEvidenceParam">],
  "PgEvidenceParamCat", CardinalityOne,
  Sequence<[
    Emit<"PgEvidenceParam", [
      Direct<"name", "param.name">,
      Direct<"type", "param.type">
    ]>
  ]>
>;

// The evidence acceptance procedure — the exact-key entry for the evidence rail.
def PgEvidenceProcedureRecipe : TargetIdiomRecipe<
  "postgres.evidence.procedure.v1", "postgres",
  "QuorumAcceptance.Single", "Evidence", "NotApplicable",
  [One<"proc", "FinalizedEvidenceProcedure">,
   Many<"params", "FinalizedEvidenceParam", 0, "unbounded", "params.ordinal">],
  "PgEvidenceProc", CardinalityOne,
  Sequence<[
    Emit<"PgEvidenceProcedure", [
      Nested<"procedureParts", Sequence<[
        Emit<"PgEvidenceHeader", []>,
        Emit<"PgQuorumGate", [
          Direct<"name", "proc.name">,
          Direct<"key", "proc.key">,
          Direct<"keyType", "proc.keyType">,
          Direct<"observerSet", "proc.observerSet">,
          Direct<"quorumM", "proc.quorumM">
        ]>,
        Emit<"PgProcedureSeparator", []>,
        Emit<"PgExecuteCallable", [
          Nested<"callableParts", Sequence<[
            Emit<"PgEvidenceCallableSig", [
              Direct<"name", "proc.executeName">,
              Nested<"params", Sequence<[
                ForEach<"params", Sequence<[
                  Call<"postgres.evidence.param.v1",
                       [Direct<"param", "params.item">]>
                ]>>
              ]>>
            ]>,
            Emit<"PgCallableBody", [
              Nested<"body", Sequence<[
                Emit<"PgEvidenceGuard", [
                  Direct<"cond", "proc.quorumPredicate">,
                  Nested<"body", Sequence<[Emit<"PgQuorumNotAccepted", []>]>>
                ]>,
                Emit<"PgEvidenceBlank", []>,
                Emit<"PgEvidenceClaim", []>,
                Emit<"PgEvidenceStatusWrite", [
                  Direct<"proc", "proc.procLiteral">,
                  Direct<"key", "proc.key">,
                  Direct<"statusAtom", "proc.statusAtom">
                ]>,
                Emit<"PgEvidenceGuard", [
                  Direct<"cond", "proc.replayPredicate">,
                  Nested<"body", Sequence<[Emit<"PgReplay", []>]>>
                ]>
              ]>>
            ]>,
            Emit<"PgCallableClose", []>
          ]>>
        ]>,
        Emit<"PgQuorumRevoke", [
          Direct<"name", "proc.name">,
          Direct<"keyType", "proc.keyType">
        ]>
      ]>>
    ]>
  ]>
>;
