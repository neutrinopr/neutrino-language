//===- PostgresEffectfulIdiomRecipes.td -  PG effectful recipe layer ---===//
//
// The declarative recipe layer for the PostgreSQL EFFECTFUL idiom, replacing the
// handwritten `neutrino::postgres_model::materializeEffectfulIdiom` (+ the
// addEffectfulQuorumRequirement / addEffectfulRevoke / buildEffectfulAdmissionGate
// helpers). Two reachable variants, exact resolution keys:
//   gated   (postgres, QuorumAcceptance.Single, Effectful, NotApplicable)
//   ungated (postgres, QuorumAcceptance.None,   Effectful, NotApplicable)
// mirroring the merged Solidity sibling (SolidityEffectfulIdiomRecipes.td).
//
// The recipe COMPOSES existing typed PgStmt/PgFunction/PgProcedure factories
// declaratively; it authors no construction and makes no semantic decision.
// Every target-facing value (the
// SQL-quoted procedure literal, the replay/requirement/balance predicates, each
// posting's already-lowered ledger/posting operands + its already-finalized
// applicability guard) is an already-lowered finalized VALUE synthesized by
// `computeEffectfulInputs` (from the verified FinalizedProjectionSequence — no
// CoordinationPlan read) and bound by `Direct`. The .td owns ORDER; the two
// variants share ONE body, switched by the presence of the finalized
// WithAttestation / WithoutAttestation marker (OptionalOp — presence already
// finalized). The reviewed  quorum gate/revoke are the exact primitives
// invoked by the package-local security resolver (quorum-gate / quorum-revoke),
// ordered gate -> execute -> revoke; the ungated self-attestation gate is not a
// security primitive and is composed from ordinary typed nodes.
//
// A stackable fragment `include`d by the package root (PostgresIdiomRecipes.td).
//
//===----------------------------------------------------------------------===//

// ---- finalized inputs (already-lowered VALUES from computeEffectfulInputs) ---

def FinalizedEffectfulProcedure : FinalizedType<"FinalizedEffectfulProcedure", [
  FinalizedField<"name", "TargetIdentifierAtom">,            // raw procedureNamespace
  FinalizedField<"nameLit", "TypedStringLiteral">,           // : raw name as string literal (postingInsert proc hook input)
  FinalizedField<"executeName", "TargetIdentifierAtom">,     // execute_<name>
  FinalizedField<"attestName", "TargetIdentifierAtom">,      // attest_<name> (ungated gate)
  FinalizedField<"proc", "TargetExpressionAtom">,            // sqlQuote(name)
  FinalizedField<"key", "TargetIdentifierAtom">,             // p_<replayKey> (pkey)
  FinalizedField<"rawKey", "TargetIdentifierAtom">,          // <replayKey> (postingInsert raw key)
  FinalizedField<"keyType", "FinalizedTargetType">,          // sqlType(keyType)
  FinalizedField<"statusSuccess", "TargetExpressionAtom">,   // projected success status atom
  FinalizedField<"statusAttest", "TargetExpressionAtom">,    // projected attested status atom
  FinalizedField<"replayPredicate", "TargetExpressionAtom">, // EXISTS coordination_status AND success
  // Two precomposed requirement predicates; the WithAttestation /
  // WithoutAttestation arm each binds its own, so no backend Boolean picks one.
  FinalizedField<"quorumRequirementPredicate", "TargetExpressionAtom">, // NOT EXISTS quorum_acceptance
  FinalizedField<"selfRequirementPredicate", "TargetExpressionAtom">,   // NOT EXISTS coordination_status ... AND attested
  FinalizedField<"notFoundPredicate", "TargetExpressionAtom">,    // NOT FOUND
  FinalizedField<"idempotencyEntry", "TargetExpressionAtom">,     // sqlEsc(name)
  FinalizedField<"balancePredicate", "TargetExpressionAtom">,     // SUM(signed_amount) ... <> 0
  // Quorum gate operands — bound only inside OptionalOp<WithAttestation>; the
  // provider reads them from the finalized attestation policy on demand.
  FinalizedField<"observerSet", "TargetExpressionAtom">,     // quorum gate observer set id
  FinalizedField<"quorumM", "TargetExpressionAtom">          // quorum threshold (decimal)
]>;

def FinalizedEffectfulParam : FinalizedType<"FinalizedEffectfulParam", [
  FinalizedField<"name", "TargetIdentifierAtom">,
  FinalizedField<"type", "FinalizedTargetType">,
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

def FinalizedEffectfulCompute : FinalizedType<"FinalizedEffectfulCompute", [
  FinalizedField<"var", "TargetIdentifierAtom">,             // v_<name>
  FinalizedField<"expr", "TargetExpressionAtom">,            // already-lowered SQL expression
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// One flat ledger posting. All operands already lowered. `commentSuffix` is
// "" for a direct leg or " when <guard>" for a guarded one; the applicability is
// carried by the related PostingGuard / PostingDirect markers (exactly one
// present per posting).
def FinalizedEffectfulPosting : FinalizedType<"FinalizedEffectfulPosting", [
  FinalizedField<"negativePredicate", "TargetExpressionAtom">, // (amount) < 0
  FinalizedField<"negativeMessage", "TargetExpressionAtom">,   // negative money for <name>
  FinalizedField<"ledger", "TypedStringLiteral">,            // : raw; comment Direct, insert Hook-escaped
  FinalizedField<"party", "TargetExpressionAtom">,
  FinalizedField<"currency", "TargetExpressionAtom">,
  FinalizedField<"signedAmount", "TargetExpressionAtom">,
  FinalizedField<"entry", "TypedStringLiteral">,             // : posting name (comment Direct, insert Hook-escaped)
  FinalizedField<"amount", "TargetExpressionAtom">,
  FinalizedField<"memo", "TypedStringLiteral">,              // : Hook-escaped in the with-memo insert
  FinalizedField<"direction", "TargetExpressionAtom">,        // effectLedgerComment kind
  FinalizedField<"commentSuffix", "TargetExpressionAtom">,    // "" or " when <guard>"
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// A comparison-guarded posting's applicability (RelatedOptional; present iff the
// leg is flat-IF wrapped). Carries the already-lowered guard predicate.
def FinalizedEffectfulPostingGuard : FinalizedType<"FinalizedEffectfulPostingGuard", [
  FinalizedField<"guard", "TargetExpressionAtom">
]>;
// A direct (unguarded / attested) posting (RelatedOptional marker; present iff
// the leg is emitted without a flat IF).
def FinalizedEffectfulPostingDirect : FinalizedType<"FinalizedEffectfulPostingDirect">;
// : per-posting memo INSERT variant markers (RelatedOptional; exactly one
// present per posting, from the finalized FinalizedPostingMemo fact).
def FinalizedEffectfulPostingMemo : FinalizedType<"FinalizedEffectfulPostingMemo">;
def FinalizedEffectfulPostingNoMemo : FinalizedType<"FinalizedEffectfulPostingNoMemo">;

def FinalizedEffectfulBalance : FinalizedType<"FinalizedEffectfulBalance", [
  FinalizedField<"ordinal", "ParamOrdinal">
]>;

// Attestation-variant markers (presence already finalized; the recipe switches
// the gate / requirement / revoke on these via OptionalOp).
def FinalizedEffectfulWithAttestation : FinalizedType<"FinalizedEffectfulWithAttestation">;
def FinalizedEffectfulWithoutAttestation : FinalizedType<"FinalizedEffectfulWithoutAttestation">;

// ---- effectful recipe target nodes (map to existing model factories) -------

// Guarded blocks -> PgStmt::ifThen(cond, body) / PgStmt::flatIf(cond, body).
def PgEffectfulGuardNode : TargetNode<"PgEffectfulGuard", "PgStatement", [
  TargetField<"cond", "value", "TargetExpressionAtom">,
  TargetField<"body", "nodes", "PgStatement", "many", 1, "unbounded">
], "if-then", []>;
def PgEffectfulFlatIfNode : TargetNode<"PgEffectfulFlatIf", "PgStatement", [
  TargetField<"cond", "value", "TargetExpressionAtom">,
  TargetField<"body", "nodes", "PgStatement", "many", 1, "unbounded">
], "flat-if", []>;

def PgEffectfulBlankNode : TargetNode<"PgEffectfulBlank", "PgStatement", [],
                                     "blank", []>;

// Fixed diagnostics -> PgStmt::raise(message).
def PgEffectfulReplayRaiseNode : TargetNode<"PgEffectfulReplayRaise", "PgStatement",
                                           [], "raise", ["replay"]>;
def PgEffectfulQuorumRaiseNode : TargetNode<"PgEffectfulQuorumRaise", "PgStatement",
                                           [], "raise", ["quorum not accepted"]>;
def PgEffectfulAttestationRaiseNode
    : TargetNode<"PgEffectfulAttestationRaise", "PgStatement", [], "raise",
                 ["missing attestation"]>;
def PgEffectfulBadTransitionRaiseNode
    : TargetNode<"PgEffectfulBadTransitionRaise", "PgStatement", [], "raise",
                 ["bad transition"]>;
// Per-posting dynamic message -> PgStmt::raise(*msg).
def PgEffectfulNegativeRaiseNode : TargetNode<"PgEffectfulNegativeRaise", "PgStatement", [
  TargetField<"msg", "value", "TargetExpressionAtom">
], "raise-value", []>;
// `RAISE EXCEPTION 'not balanced for %', <arg>;` -> PgStmt::raise(msg, arg).
def PgEffectfulUnbalancedRaiseNode : TargetNode<"PgEffectfulUnbalancedRaise", "PgStatement", [
  TargetField<"arg", "value", "TargetIdentifierAtom">
], "raise-arg", ["not balanced for %"]>;

// A variable assignment `<var> := <expr>;` -> PgStmt::assign(var, expr).
def PgEffectfulAssignNode : TargetNode<"PgEffectfulAssign", "PgStatement", [
  TargetField<"var", "value", "TargetIdentifierAtom">,
  TargetField<"expr", "value", "TargetExpressionAtom">
], "assign", []>;

// Idempotency machinery comments + statements.
def PgEffectfulIdempotencyGuardCommentNode
    : TargetNode<"PgEffectfulIdempotencyGuardComment", "PgStatement", [],
                 "idempotency-guard-comment", []>;
def PgEffectfulPostingIdempotencyNode
    : TargetNode<"PgEffectfulPostingIdempotency", "PgStatement", [
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"entry", "value", "TargetExpressionAtom">
], "posting-idempotency", []>;
def PgEffectfulIdempotentReturnNode
    : TargetNode<"PgEffectfulIdempotentReturn", "PgStatement", [],
                 "idempotent-return", []>;

// A per-posting effect ledger comment -> PgStmt::effectLedgerComment(kind, name,
// ledger, suffix).
def PgEffectfulLedgerCommentNode : TargetNode<"PgEffectfulLedgerComment", "PgStatement", [
  TargetField<"direction", "value", "TargetExpressionAtom">,
  // : name/ledger read the raw TypedStringLiteral posting fields Direct
  // (the decorative comment is unescaped).
  TargetField<"name", "value", "TypedStringLiteral">,
  TargetField<"ledger", "value", "TypedStringLiteral">,
  TargetField<"suffix", "value", "TargetExpressionAtom">
], "effect-ledger-comment", []>;

// A ledger upsert -> PgStmt::ledgerUpsert(ledger, party, currency, signedAmount).
def PgEffectfulLedgerUpsertNode : TargetNode<"PgEffectfulLedgerUpsert", "PgStatement", [
  TargetField<"ledger", "leaf", "EscapedStringLiteral">,
  TargetField<"party", "value", "TargetExpressionAtom">,
  TargetField<"currency", "value", "TargetExpressionAtom">,
  TargetField<"signedAmount", "value", "TargetExpressionAtom">
], "ledger-upsert", []>;

// A posting insert. Two byte-distinct variants selected per-posting from the
// finalized FinalizedPostingMemo fact: no-memo and with-memo. proc/entry/ledger
// (and memo) are string.escape-hook-escaped leaves.
def PgEffectfulPostingInsertNode : TargetNode<"PgEffectfulPostingInsert", "PgStatement", [
  TargetField<"proc", "leaf", "EscapedStringLiteral">,
  TargetField<"entry", "leaf", "EscapedStringLiteral">,
  TargetField<"ledger", "leaf", "EscapedStringLiteral">,
  TargetField<"party", "value", "TargetExpressionAtom">,
  TargetField<"amount", "value", "TargetExpressionAtom">,
  TargetField<"currency", "value", "TargetExpressionAtom">,
  TargetField<"signedAmount", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">
], "posting-insert", []>;
def PgEffectfulPostingInsertWithMemoNode
    : TargetNode<"PgEffectfulPostingInsertWithMemo", "PgStatement", [
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

def PgEffectfulBalancedInvariantCommentNode
    : TargetNode<"PgEffectfulBalancedInvariantComment", "PgStatement", [],
                 "balanced-invariant-comment", []>;

// The terminal reconciled status write -> PgStmt::statusWrite(proc, key, status,
// /*doUpdate=*/true).
def PgEffectfulStatusWriteNode : TargetNode<"PgEffectfulStatusWrite", "PgStatement", [
  TargetField<"proc", "value", "TargetExpressionAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"statusAtom", "value", "TargetExpressionAtom">
], "status-write-update", []>;

// One typed callable parameter -> PgParam{name, type}.
def PgEffectfulParamNode : TargetNode<"PgEffectfulParam", "PgEffectfulParamCat", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"type", "value", "FinalizedTargetType">
], "param", []>;

// One execute-function DECLARE entry `v_<compute> bigint` -> PgDeclaration.
def PgEffectfulComputeDeclNode : TargetNode<"PgEffectfulComputeDecl", "PgEffectfulDeclCat", [
  TargetField<"name", "value", "TargetIdentifierAtom">
], "declaration", ["bigint"]>;

// The reviewed  quorum-accept gate -> resolveQuorumGate(name, key, keyType,
// observerSet, quorumM) (accept_<name>), invoked by the package-local security
// resolver during construction. A PgFunction.
def PgEffectfulQuorumGateNode : TargetNode<"PgEffectfulQuorumGate", "PgProcedurePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"key", "value", "TargetIdentifierAtom">,
  TargetField<"keyType", "value", "FinalizedTargetType">,
  TargetField<"observerSet", "value", "TargetExpressionAtom">,
  TargetField<"quorumM", "value", "TargetExpressionAtom">
], "quorum-gate", []>;

// The reviewed  revoke trailer -> resolveQuorumRevoke(name, keyType). RawSql.
def PgEffectfulRevokeNode : TargetNode<"PgEffectfulRevoke", "PgProcedurePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"keyType", "value", "FinalizedTargetType">
], "quorum-revoke", []>;

// The ungated self-attestation gate `attest_<name>` -> PgFunction{name, params,
// declare=false, body=[bad-transition guard, statusWrite]}. NOT a  primitive
// (no quorum); composed from ordinary typed nodes.
def PgEffectfulCallableSigNode
    : TargetNode<"PgEffectfulCallableSig", "PgCallablePart", [
  TargetField<"name", "value", "TargetIdentifierAtom">,
  TargetField<"params", "nodes", "PgEffectfulParamCat", "many", 0, "unbounded">
], "callable-signature", []>;
def PgEffectfulDeclareSectionNode
    : TargetNode<"PgEffectfulDeclareSection", "PgCallablePart", [
  TargetField<"declarations", "nodes", "PgEffectfulDeclCat", "many", 0,
              "unbounded">
], "callable-declaration", []>;
def PgEffectfulAttestGateNode
    : TargetNode<"PgEffectfulAttestGate", "PgProcedurePart", [
  TargetField<"callableParts", "nodes", "PgCallablePart", "many", 3, "3">
], "callable-root", []>;

// The effectful `execute_` callable -> PgFunction{name, params, declare=true,
// declarations (v_<compute> bigint per compute), body}.
def PgEffectfulExecuteCallableNode
    : TargetNode<"PgEffectfulExecuteCallable", "PgProcedurePart", [
  TargetField<"callableParts", "nodes", "PgCallablePart", "many", 4, "4">
], "callable-root", []>;
def PgEffectfulHeaderNode
    : TargetNode<"PgEffectfulHeader", "PgProcedurePart", [],
                 "common-header", [
  "-- Generated by the Neutrino Translator from verified MLIR.",
  "-- Idempotent + atomic (a function body runs in a single transaction)."
]>;

// The effectful PgProcedure -> {evidenceOnly=false, gated, header, functions=
// [gate, execute], revoke?}. The header banner is fixed .td-owned BuilderArg data
// (one arg per comment line); the gated flag is owned by the builder kind. The
// revoke field is optional (present only for the gated quorum variant).
def PgEffectfulGatedProcedureNode : TargetNode<"PgEffectfulGatedProcedure", "PgEffectfulProc", [
  TargetField<"procedureParts", "nodes", "PgProcedurePart", "many", 3, "6">
], "effectful-gated-procedure", []>;
def PgEffectfulUngatedProcedureNode : TargetNode<"PgEffectfulUngatedProcedure", "PgEffectfulProc", [
  TargetField<"procedureParts", "nodes", "PgProcedurePart", "many", 3, "6">
], "effectful-ungated-procedure", []>;

// ---- recipes ---------------------------------------------------------------

// The shared effectful procedure recipe. `prefix` disambiguates the two
// variants' input slots (the generator emits global slot ids per name); `procNode`
// carries the gated flag; the WithAttestation / WithoutAttestation markers switch
// the gate, the requirement raise, and the revoke.
class PgEffectfulRecipe<string recipeId, string finalizedKind, string prefix,
                        TargetNode procNode>
  : TargetIdiomRecipe<recipeId, "postgres", finalizedKind, "Effectful",
      "NotApplicable", [
        One<!strconcat(prefix, "Proc"), "FinalizedEffectfulProcedure">,
        Optional<!strconcat(prefix, "WithAttestation"),
                 "FinalizedEffectfulWithAttestation">,
        Optional<!strconcat(prefix, "WithoutAttestation"),
                 "FinalizedEffectfulWithoutAttestation">,
        Many<!strconcat(prefix, "Params"), "FinalizedEffectfulParam", 0,
             "unbounded", !strconcat(prefix, "Params.ordinal")>,
        Many<!strconcat(prefix, "Computes"), "FinalizedEffectfulCompute", 0,
             "unbounded", !strconcat(prefix, "Computes.ordinal")>,
        Many<!strconcat(prefix, "Postings"), "FinalizedEffectfulPosting", 0,
             "unbounded", !strconcat(prefix, "Postings.ordinal")>,
        RelatedOptional<!strconcat(prefix, "PostingGuard"),
                        "FinalizedEffectfulPostingGuard",
                        !strconcat(prefix, "Postings")>,
        RelatedOptional<!strconcat(prefix, "PostingDirect"),
                        "FinalizedEffectfulPostingDirect",
                        !strconcat(prefix, "Postings")>,
        RelatedOptional<!strconcat(prefix, "PostingMemo"),
                        "FinalizedEffectfulPostingMemo",
                        !strconcat(prefix, "Postings")>,
        RelatedOptional<!strconcat(prefix, "PostingNoMemo"),
                        "FinalizedEffectfulPostingNoMemo",
                        !strconcat(prefix, "Postings")>,
        Many<!strconcat(prefix, "Balances"), "FinalizedEffectfulBalance", 0,
             "unbounded", !strconcat(prefix, "Balances.ordinal")>
      ],
      "PgEffectfulProc", CardinalityOne,
      Sequence<[
        Emit<procNode.Name, [
          Nested<"procedureParts", Sequence<[
            Emit<"PgEffectfulHeader", []>,
            // The admission gate (exactly one variant present).
            OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
              Emit<"PgEffectfulQuorumGate", [
                Direct<"name", !strconcat(prefix, "Proc.name")>,
                Direct<"key", !strconcat(prefix, "Proc.key")>,
                Direct<"keyType", !strconcat(prefix, "Proc.keyType")>,
                Direct<"observerSet", !strconcat(prefix, "Proc.observerSet")>,
                Direct<"quorumM", !strconcat(prefix, "Proc.quorumM")>
              ]>
            ]>>,
            OptionalOp<!strconcat(prefix, "WithoutAttestation"), Sequence<[
              Emit<"PgEffectfulAttestGate", [
                Nested<"callableParts", Sequence<[
                  Emit<"PgEffectfulCallableSig", [
                    Direct<"name", !strconcat(prefix, "Proc.attestName")>,
                    Nested<"params", Sequence<[
                      Emit<"PgEffectfulParam", [
                        Direct<"name", !strconcat(prefix, "Proc.key")>,
                        Direct<"type", !strconcat(prefix, "Proc.keyType")>
                      ]>
                    ]>>
                  ]>,
                  Emit<"PgCallableBody", [
                    Nested<"body", Sequence<[
                      Emit<"PgEffectfulGuard", [
                        Direct<"cond", !strconcat(prefix, "Proc.replayPredicate")>,
                        Nested<"body", Sequence<[
                          Emit<"PgEffectfulBadTransitionRaise", []>
                        ]>>
                      ]>,
                      Emit<"PgEffectfulStatusWrite", [
                        Direct<"proc", !strconcat(prefix, "Proc.proc")>,
                        Direct<"key", !strconcat(prefix, "Proc.key")>,
                        Direct<"statusAtom", !strconcat(prefix, "Proc.statusAttest")>
                      ]>
                    ]>>
                  ]>,
                  Emit<"PgCallableClose", []>
                ]>>
              ]>
            ]>>,
            Emit<"PgProcedureSeparator", []>,
            // The execute callable (shared).
            Emit<"PgEffectfulExecuteCallable", [
              Nested<"callableParts", Sequence<[
                Emit<"PgEffectfulCallableSig", [
                  Direct<"name", !strconcat(prefix, "Proc.executeName")>,
                  Nested<"params", Sequence<[
                    ForEach<!strconcat(prefix, "Params"), Sequence<[
                      Emit<"PgEffectfulParam", [
                        Direct<"name", !strconcat(prefix, "Params.name")>,
                        Direct<"type", !strconcat(prefix, "Params.type")>
                      ]>
                    ]>>
                  ]>>
                ]>,
                Emit<"PgEffectfulDeclareSection", [
                  Nested<"declarations", Sequence<[
                    ForEach<!strconcat(prefix, "Computes"), Sequence<[
                      Emit<"PgEffectfulComputeDecl", [
                        Direct<"name", !strconcat(prefix, "Computes.var")>
                      ]>
                    ]>>
                  ]>>
                ]>,
                Emit<"PgCallableBody", [
                  Nested<"body", Sequence<[
                // (1) replay guard
                Emit<"PgEffectfulGuard", [
                  Direct<"cond", !strconcat(prefix, "Proc.replayPredicate")>,
                  Nested<"body", Sequence<[Emit<"PgEffectfulReplayRaise", []>]>>
                ]>,
                // (2) admission requirement (exactly one variant present)
                OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
                  Emit<"PgEffectfulGuard", [
                    Direct<"cond", !strconcat(prefix, "Proc.quorumRequirementPredicate")>,
                    Nested<"body", Sequence<[Emit<"PgEffectfulQuorumRaise", []>]>>
                  ]>
                ]>>,
                OptionalOp<!strconcat(prefix, "WithoutAttestation"), Sequence<[
                  Emit<"PgEffectfulGuard", [
                    Direct<"cond", !strconcat(prefix, "Proc.selfRequirementPredicate")>,
                    Nested<"body", Sequence<[Emit<"PgEffectfulAttestationRaise", []>]>>
                  ]>
                ]>>,
                Emit<"PgEffectfulBlank", []>,
                // (3) idempotency machinery
                Emit<"PgEffectfulIdempotencyGuardComment", []>,
                Emit<"PgEffectfulPostingIdempotency", [
                  Direct<"key", !strconcat(prefix, "Proc.key")>,
                  Direct<"entry", !strconcat(prefix, "Proc.idempotencyEntry")>
                ]>,
                Emit<"PgEffectfulGuard", [
                  Direct<"cond", !strconcat(prefix, "Proc.notFoundPredicate")>,
                  Nested<"body", Sequence<[Emit<"PgEffectfulIdempotentReturn", []>]>>
                ]>,
                Emit<"PgEffectfulBlank", []>,
                // (4) compute assigns
                ForEach<!strconcat(prefix, "Computes"), Sequence<[
                  Emit<"PgEffectfulAssign", [
                    Direct<"var", !strconcat(prefix, "Computes.var")>,
                    Direct<"expr", !strconcat(prefix, "Computes.expr")>
                  ]>
                ]>>,
                Emit<"PgEffectfulBlank", []>,
                // (5) per-posting legs (direct or flat-IF guarded)
                ForEach<!strconcat(prefix, "Postings"), Sequence<[
                  Emit<"PgEffectfulLedgerComment", [
                    Direct<"direction", !strconcat(prefix, "Postings.direction")>,
                    Direct<"name", !strconcat(prefix, "Postings.entry")>,
                    Direct<"ledger", !strconcat(prefix, "Postings.ledger")>,
                    Direct<"suffix", !strconcat(prefix, "Postings.commentSuffix")>
                  ]>,
                  OptionalOp<!strconcat(prefix, "PostingDirect"), Sequence<[
                    Emit<"PgEffectfulGuard", [
                      Direct<"cond", !strconcat(prefix, "Postings.negativePredicate")>,
                      Nested<"body", Sequence<[
                        Emit<"PgEffectfulNegativeRaise", [
                          Direct<"msg", !strconcat(prefix, "Postings.negativeMessage")>
                        ]>
                      ]>>
                    ]>,
                    Emit<"PgEffectfulLedgerUpsert", [
                      Hook<"ledger", "postgres.string.escape", !strconcat(prefix, "Postings.ledger")>,
                      Direct<"party", !strconcat(prefix, "Postings.party")>,
                      Direct<"currency", !strconcat(prefix, "Postings.currency")>,
                      Direct<"signedAmount", !strconcat(prefix, "Postings.signedAmount")>
                    ]>,
                    OptionalOp<!strconcat(prefix, "PostingMemo"), Sequence<[
                      Emit<"PgEffectfulPostingInsertWithMemo", [
                        Hook<"proc", "postgres.string.escape", !strconcat(prefix, "Proc.nameLit")>,
                        Hook<"entry", "postgres.string.escape", !strconcat(prefix, "Postings.entry")>,
                        Hook<"ledger", "postgres.string.escape", !strconcat(prefix, "Postings.ledger")>,
                        Direct<"party", !strconcat(prefix, "Postings.party")>,
                        Direct<"amount", !strconcat(prefix, "Postings.amount")>,
                        Direct<"currency", !strconcat(prefix, "Postings.currency")>,
                        Direct<"signedAmount", !strconcat(prefix, "Postings.signedAmount")>,
                        Direct<"key", !strconcat(prefix, "Proc.rawKey")>,
                        Hook<"memo", "postgres.string.escape", !strconcat(prefix, "Postings.memo")>
                      ]>
                    ]>>,
                    OptionalOp<!strconcat(prefix, "PostingNoMemo"), Sequence<[
                      Emit<"PgEffectfulPostingInsert", [
                        Hook<"proc", "postgres.string.escape", !strconcat(prefix, "Proc.nameLit")>,
                        Hook<"entry", "postgres.string.escape", !strconcat(prefix, "Postings.entry")>,
                        Hook<"ledger", "postgres.string.escape", !strconcat(prefix, "Postings.ledger")>,
                        Direct<"party", !strconcat(prefix, "Postings.party")>,
                        Direct<"amount", !strconcat(prefix, "Postings.amount")>,
                        Direct<"currency", !strconcat(prefix, "Postings.currency")>,
                        Direct<"signedAmount", !strconcat(prefix, "Postings.signedAmount")>,
                        Direct<"key", !strconcat(prefix, "Proc.rawKey")>
                      ]>
                    ]>>
                  ]>>,
                  OptionalOp<!strconcat(prefix, "PostingGuard"), Sequence<[
                    Emit<"PgEffectfulFlatIf", [
                      Direct<"cond", !strconcat(prefix, "PostingGuard.guard")>,
                      Nested<"body", Sequence<[
                        Emit<"PgEffectfulGuard", [
                          Direct<"cond", !strconcat(prefix, "Postings.negativePredicate")>,
                          Nested<"body", Sequence<[
                            Emit<"PgEffectfulNegativeRaise", [
                              Direct<"msg", !strconcat(prefix, "Postings.negativeMessage")>
                            ]>
                          ]>>
                        ]>,
                        Emit<"PgEffectfulLedgerUpsert", [
                          Hook<"ledger", "postgres.string.escape", !strconcat(prefix, "Postings.ledger")>,
                          Direct<"party", !strconcat(prefix, "Postings.party")>,
                          Direct<"currency", !strconcat(prefix, "Postings.currency")>,
                          Direct<"signedAmount", !strconcat(prefix, "Postings.signedAmount")>
                        ]>,
                        OptionalOp<!strconcat(prefix, "PostingMemo"), Sequence<[
                          Emit<"PgEffectfulPostingInsertWithMemo", [
                            Hook<"proc", "postgres.string.escape", !strconcat(prefix, "Proc.nameLit")>,
                            Hook<"entry", "postgres.string.escape", !strconcat(prefix, "Postings.entry")>,
                            Hook<"ledger", "postgres.string.escape", !strconcat(prefix, "Postings.ledger")>,
                            Direct<"party", !strconcat(prefix, "Postings.party")>,
                            Direct<"amount", !strconcat(prefix, "Postings.amount")>,
                            Direct<"currency", !strconcat(prefix, "Postings.currency")>,
                            Direct<"signedAmount", !strconcat(prefix, "Postings.signedAmount")>,
                            Direct<"key", !strconcat(prefix, "Proc.rawKey")>,
                            Hook<"memo", "postgres.string.escape", !strconcat(prefix, "Postings.memo")>
                          ]>
                        ]>>,
                        OptionalOp<!strconcat(prefix, "PostingNoMemo"), Sequence<[
                          Emit<"PgEffectfulPostingInsert", [
                            Hook<"proc", "postgres.string.escape", !strconcat(prefix, "Proc.nameLit")>,
                            Hook<"entry", "postgres.string.escape", !strconcat(prefix, "Postings.entry")>,
                            Hook<"ledger", "postgres.string.escape", !strconcat(prefix, "Postings.ledger")>,
                            Direct<"party", !strconcat(prefix, "Postings.party")>,
                            Direct<"amount", !strconcat(prefix, "Postings.amount")>,
                            Direct<"currency", !strconcat(prefix, "Postings.currency")>,
                            Direct<"signedAmount", !strconcat(prefix, "Postings.signedAmount")>,
                            Direct<"key", !strconcat(prefix, "Proc.rawKey")>
                          ]>
                        ]>>
                      ]>>
                    ]>
                  ]>>,
                  Emit<"PgEffectfulBlank", []>
                ]>>,
                // (6) balance invariants
                ForEach<!strconcat(prefix, "Balances"), Sequence<[
                  Emit<"PgEffectfulBalancedInvariantComment", []>,
                  Emit<"PgEffectfulGuard", [
                    Direct<"cond", !strconcat(prefix, "Proc.balancePredicate")>,
                    Nested<"body", Sequence<[
                      Emit<"PgEffectfulUnbalancedRaise", [
                        Direct<"arg", !strconcat(prefix, "Proc.key")>
                      ]>
                    ]>>
                  ]>
                ]>>,
                Emit<"PgEffectfulBlank", []>,
                // (7) terminal reconciled status write
                Emit<"PgEffectfulStatusWrite", [
                  Direct<"proc", !strconcat(prefix, "Proc.proc")>,
                  Direct<"key", !strconcat(prefix, "Proc.key")>,
                  Direct<"statusAtom", !strconcat(prefix, "Proc.statusSuccess")>
                ]>
              ]>>
            ]>,
            Emit<"PgCallableClose", []>
          ]>>
        ]>,
        OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
          Emit<"PgEffectfulRevoke", [
            Direct<"name", !strconcat(prefix, "Proc.name")>,
            Direct<"keyType", !strconcat(prefix, "Proc.keyType")>
          ]>
        ]>>
      ]>>
    ]>
  ]>
>;

def PgEffectfulGatedRecipe : PgEffectfulRecipe<
  "postgres.effectful.with-attestation.v1", "QuorumAcceptance.Single",
  "egated", PgEffectfulGatedProcedureNode>;
def PgEffectfulUngatedRecipe : PgEffectfulRecipe<
  "postgres.effectful.without-attestation.v1", "QuorumAcceptance.None",
  "eungated", PgEffectfulUngatedProcedureNode>;
