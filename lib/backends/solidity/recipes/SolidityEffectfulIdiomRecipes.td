//===- SolidityEffectfulIdiomRecipes.td - effectful recipes --------------===//

def SolEffectfulGuardParamNode : TargetNode<
  "SolEffectfulGuardParam", "SolTemporalParam", [],
  "effectful-guard-param">;
def SolEffectfulGuardRequireNode : TargetNode<
  "SolEffectfulGuardRequire", "SolStatement", [],
  "effectful-guard-require">;
def SolEffectfulGuardAssignNode : TargetNode<
  "SolEffectfulGuardAssign", "SolStatement", [],
  "effectful-guard-assign">;
def SolEffectfulKeyParamNode : TargetNode<
  "SolEffectfulKeyParam", "SolTemporalParam", [
    TargetField<"name", "leaf", "EscapedIdentifier">
  ], "effectful-key-param">;
def SolEffectfulReplayRequireNode : TargetNode<
  "SolEffectfulReplayRequire", "SolStatement", [
    TargetField<"status", "value", "LifecycleStatusAtom">
  ], "effectful-replay-require">;
def SolEffectfulAttestedAssignNode : TargetNode<
  "SolEffectfulAttestedAssign", "SolStatement", [],
  "effectful-attested-assign">;
def SolEffectfulAttestNode : TargetNode<
  "SolEffectfulAttest", "SolStatement", [
    TargetField<"params", "nodes", "SolTemporalParam", "many", 1, "1">,
    TargetField<"body", "nodes", "SolStatement", "many", 3, "3">
  ], "effectful-attest">;
def SolEffectfulAttestationCommentNode : TargetNode<
  "SolEffectfulAttestationComment", "SolStatement", [],
  "effectful-attestation-comment">;
def SolEffectfulIsolationCommentNode : TargetNode<
  "SolEffectfulIsolationComment", "SolStatement", [],
  "effectful-isolation-comment">;
def SolEffectfulAttestedStorageNode : TargetNode<
  "SolEffectfulAttestedStorage", "SolStatement", [],
  "effectful-attested-storage">;
def SolEffectfulGuardStorageNode : TargetNode<
  "SolEffectfulGuardStorage", "SolStatement", [],
  "effectful-guard-storage">;
def SolEffectfulExecuteReplayRequireNode : TargetNode<
  "SolEffectfulExecuteReplayRequire", "SolStatement", [
    TargetField<"status", "value", "LifecycleStatusAtom">
  ], "effectful-execute-replay-require">;
def SolEffectfulSelfAcceptanceNode : TargetNode<
  "SolEffectfulSelfAcceptance", "SolStatement", [],
  "effectful-self-acceptance">;
def SolEffectfulGuardAcceptanceNode : TargetNode<
  "SolEffectfulGuardAcceptance", "SolStatement", [],
  "effectful-guard-acceptance">;
def SolEffectfulPostingGuardNode : TargetNode<
  "SolEffectfulPostingGuard", "SolStatement", [
    TargetField<"condition", "leaf", "TargetExpression">,
    TargetField<"body", "nodes", "SolStatement", "many", 3, "3">
  ], "effectful-posting-guard">;
def SolEffectfulExecuteNode : TargetNode<
  "SolEffectfulExecute", "SolStatement", [
    TargetField<"params", "nodes", "SolTemporalParam", "many", 1, "unbounded">,
    TargetField<"body", "nodes", "SolStatement", "many", 9, "unbounded">
  ], "temporal-execute">;
def SolEffectfulUngatedContractNode : TargetNode<
  "SolEffectfulUngatedContract", "SolTemporalContractModel", [
    TargetField<"name", "leaf", "EscapedIdentifier">,
    TargetField<"header", "nodes", "SolStatement", "many", 9, "15">,
    TargetField<"body", "nodes", "SolStatement", "many", 1, "unbounded">,
    TargetField<"sourceCanonicalizations", "nodes",
                "SolSourceCanonicalization", "many", 0, "unbounded">
  ], "effectful-contract-ungated">;
def SolEffectfulGatedContractNode : TargetNode<
  "SolEffectfulGatedContract", "SolTemporalContractModel", [
    TargetField<"name", "leaf", "EscapedIdentifier">,
    TargetField<"header", "nodes", "SolStatement", "many", 9, "15">,
    TargetField<"body", "nodes", "SolStatement", "many", 1, "unbounded">,
    TargetField<"sourceCanonicalizations", "nodes",
                "SolSourceCanonicalization", "many", 0, "unbounded">
  ], "effectful-contract-gated">;

def FinalizedEffectfulPostingGuard : FinalizedType<
  "FinalizedEffectfulPostingGuard", [
    FinalizedField<"expression", "FinalizedExpressionLeaf">
  ]>;
def FinalizedEffectfulDirectPosting : FinalizedType<
  "FinalizedEffectfulDirectPosting">;
def FinalizedEffectfulWithAttestation : FinalizedType<
  "FinalizedEffectfulWithAttestation">;
def FinalizedEffectfulWithoutAttestation : FinalizedType<
  "FinalizedEffectfulWithoutAttestation">;

def SolidityEffectfulPrimitiveWithAttestation : TargetIdiomRecipe<
  "solidity.effectful.primitive.with-attestation.v1", "solidity",
  "EffectfulPrimitive.WithAttestation", "Effectful", "NotApplicable", [],
  "SolStatement", CardinalityOne,
  Sequence<[
      Emit<"SolTemporalConstructor", [Nested<"params", Sequence<[Emit<"SolEffectfulGuardParam", []>]>>, Nested<"body", Sequence<[
      Emit<"SolEffectfulGuardRequire", []>,
      Emit<"SolEffectfulGuardAssign", []>
    ]>>]>
    ]>>;

def SolidityEffectfulPrimitiveWithoutAttestation : TargetIdiomRecipe<
  "solidity.effectful.primitive.without-attestation.v1", "solidity",
  "EffectfulPrimitive.WithoutAttestation", "Effectful", "NotApplicable", [
    One<"effectExecution", "FinalizedTemporalExecution">,
    One<"effectInitialRole", "FinalizedTemporalRole">
  ],
  "SolStatement", CardinalityOne,
  Sequence<[
      Emit<"SolEffectfulAttest", [Nested<"params", Sequence<[
      Emit<"SolEffectfulKeyParam", [Hook<"name", "solidity.identifier.escape", "effectExecution.instanceKey">]>
    ]>>, Nested<"body", Sequence<[
      Emit<"SolTemporalReplayKey", [Hook<"key", "solidity.identifier.escape", "effectExecution.replayKey">]>,
      Emit<"SolEffectfulReplayRequire", [Direct<"status", "effectInitialRole.status">]>,
      Emit<"SolEffectfulAttestedAssign", []>
    ]>>]>
    ]>>;

class SolidityEffectfulContractRecipe<
    string recipeId, string finalizedKind, TargetNode contractNode,
    string prefix>
    : TargetIdiomRecipe<
        recipeId, "solidity", finalizedKind, "Effectful", "NotApplicable", [
          One<!strconcat(prefix, "Execution"), "FinalizedTemporalExecution">,
          One<!strconcat(prefix, "InitialRole"), "FinalizedTemporalRole">,
          One<!strconcat(prefix, "SuccessRole"), "FinalizedTemporalRole">,
          Many<!strconcat(prefix, "SourceCanonicalizations"),
               "FinalizedSourceCanonicalization", 0, "unbounded",
               !strconcat(prefix, "SourceCanonicalizations.ordinal")>,
          Optional<!strconcat(prefix, "WithAttestation"),
                   "FinalizedEffectfulWithAttestation">,
          Optional<!strconcat(prefix, "WithoutAttestation"),
                   "FinalizedEffectfulWithoutAttestation">,
          Many<!strconcat(prefix, "Params"), "FinalizedTemporalParam", 1, "unbounded",
               !strconcat(prefix, "Params.ordinal")>,
          Many<!strconcat(prefix, "Computes"), "FinalizedTemporalCompute", 0, "unbounded",
               !strconcat(prefix, "Computes.ordinal")>,
          Many<!strconcat(prefix, "Postings"), "FinalizedTemporalPosting", 1,
               "unbounded", !strconcat(prefix, "Postings.ordinal")>,
          RelatedOptional<!strconcat(prefix, "PostingMemo"), "FinalizedTemporalMemo",
                          !strconcat(prefix, "Postings"), PresenceMemo>,
          RelatedOptional<!strconcat(prefix, "PostingDirect"),
                          "FinalizedEffectfulDirectPosting",
                          !strconcat(prefix, "Postings"), PresenceDirect>,
          RelatedOptional<!strconcat(prefix, "PostingGuard"),
                          "FinalizedEffectfulPostingGuard",
                          !strconcat(prefix, "Postings"), PresenceGuard>,
          Many<!strconcat(prefix, "BalanceAssertions"), "FinalizedTemporalBalance", 1,
               "unbounded", !strconcat(prefix, "BalanceAssertions.ordinal")>
        ],
        "SolTemporalContractModel", CardinalityOne,
        Sequence<[
          Emit<contractNode.Name, [
            Hook<"name", "solidity.identifier.escape",
                 !strconcat(prefix, "Execution.procedure")>,
            Nested<"header", Sequence<[
              Emit<"SolTemporalSpdx", []>,
              Emit<"SolTemporalPragma", []>,
              Emit<"SolTemporalBlank", []>,
              OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
                Call<"solidity.guard-consumer.effectful.v1", []>,
                Emit<"SolTemporalBlank", []>
              ]>>,
              Emit<"SolTemporalGeneratedComment", []>,
              Emit<"SolTemporalCoordinationComment", []>,
              Emit<"SolEffectfulAttestationComment", []>,
              Emit<"SolTemporalAuthorityComment", []>,
              Emit<"SolTemporalKeyComment", []>,
              Emit<"SolEffectfulIsolationComment", []>
            ]>>,
            Nested<"body", Sequence<[
              Emit<"SolStatusEnum", [
                Direct<"initial", !strconcat(prefix, "InitialRole.status")>,
                Direct<"success", !strconcat(prefix, "SuccessRole.status")>]>,
              Emit<"SolTemporalBlank", []>,
              Emit<"SolTemporalTriggerEvent", [
                Hook<"name", "solidity.identifier.escape",
                     !strconcat(prefix, "Execution.invokedEvent")>,
                Nested<"params", Sequence<[
                  Emit<"SolTemporalStringKeyParam", [
                    Hook<"name", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.instanceKey")>
                  ]>
                ]>>
              ]>,
              ForEach<!strconcat(prefix, "Computes"), Sequence<[
                Emit<"SolTemporalComputedEvent", [
                  Hook<"name", "solidity.identifier.escape",
                       !strconcat(prefix, "Computes.name")>,
                  Nested<"params", Sequence<[
                    Emit<"SolTemporalUintValueParam", []>
                  ]>>
                ]>
              ]>>,
              ForEach<!strconcat(prefix, "Postings"), Sequence<[
                Emit<"SolTemporalPostingEvent", [
                  Hook<"name", "solidity.identifier.escape",
                       !strconcat(prefix, "Postings.name")>,
                  Direct<"direction", !strconcat(prefix, "Postings.direction")>,
                  Nested<"params", Sequence<[
                    Emit<"SolTemporalPostingPartyParam", []>,
                    Emit<"SolTemporalPostingAmountParam", []>,
                    Emit<"SolTemporalPostingCurrencyParam", []>,
                    OptionalOp<!strconcat(prefix, "PostingMemo"), Sequence<[
                      Emit<"SolTemporalPostingMemoParam", []>
                    ]>>
                  ]>>
                ]>
              ]>>,
              Emit<"SolTemporalReconciledEvent", [
                Hook<"name", "solidity.identifier.escape",
                     !strconcat(prefix, "Execution.procedure")>,
                Nested<"params", Sequence<[
                  Emit<"SolTemporalStringKeyParam", [
                    Hook<"name", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.instanceKey")>
                  ]>
                ]>>
              ]>,
              Emit<"SolTemporalBlank", []>,
              Emit<"SolTemporalStatusStorage", []>,
              OptionalOp<!strconcat(prefix, "WithoutAttestation"), Sequence<[
                Emit<"SolEffectfulAttestedStorage", []>
              ]>>,
              Emit<"SolTemporalNetStorage", []>,
              Emit<"SolTemporalDebitStorage", []>,
              Emit<"SolTemporalCreditStorage", []>,
              OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
                Emit<"SolEffectfulGuardStorage", []>
              ]>>,
              OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
                Emit<"SolTemporalBlank", []>,
                Call<"solidity.effectful.primitive.with-attestation.v1", []>
              ]>>,
              OptionalOp<!strconcat(prefix, "WithoutAttestation"), Sequence<[
                Emit<"SolTemporalBlank", []>,
                Call<"solidity.effectful.primitive.without-attestation.v1", [
                  Direct<"effectExecution", !strconcat(prefix, "Execution.item")>,
                  Direct<"effectInitialRole", !strconcat(prefix, "InitialRole.item")>
                ]>
              ]>>,
              Emit<"SolTemporalBlank", []>,
              Emit<"SolEffectfulExecute", [
                Nested<"params", Sequence<[
                  ForEach<!strconcat(prefix, "Params"), Sequence<[
                    Emit<"SolTemporalExecuteParam", [
                      Hook<"name", "solidity.identifier.escape",
                           !strconcat(prefix, "Params.name")>,
                      Hook<"type", "solidity.type.spell",
                           !strconcat(prefix, "Params.type")>
                    ]>
                  ]>>
                ]>>,
                Nested<"body", Sequence<[
                  Emit<"SolTemporalReplayKey", [
                    Hook<"key", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.replayKey")>
                  ]>,
                  Emit<"SolEffectfulExecuteReplayRequire", [
                    Direct<"status", !strconcat(prefix, "InitialRole.status")>
                  ]>,
                  OptionalOp<!strconcat(prefix, "WithAttestation"), Sequence<[
                    Emit<"SolEffectfulGuardAcceptance", []>
                  ]>>,
                  OptionalOp<!strconcat(prefix, "WithoutAttestation"), Sequence<[
                    Emit<"SolEffectfulSelfAcceptance", []>
                  ]>>,
                  Emit<"SolTemporalTriggerEmit", [
                    Hook<"event", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.invokedEvent")>,
                    Hook<"key", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.instanceKey")>
                  ]>,
                  Emit<"SolTemporalBlank", []>,
                  ForEach<!strconcat(prefix, "Computes"), Sequence<[
                    Emit<"SolTemporalComputeDecl", [
                      Hook<"name", "solidity.identifier.escape",
                           !strconcat(prefix, "Computes.name")>,
                      Hook<"expression", "solidity.expression.leaf",
                           !strconcat(prefix, "Computes.expression")>
                    ]>,
                    Emit<"SolTemporalComputeEmit", [
                      Hook<"name", "solidity.identifier.escape",
                           !strconcat(prefix, "Computes.name")>
                    ]>
                  ]>>,
                  Emit<"SolTemporalBlank", []>,
                  ForEach<!strconcat(prefix, "Postings"), Sequence<[
                    OptionalOp<!strconcat(prefix, "PostingDirect"), Sequence<[
                      Emit<"SolTemporalNetUpdate", [
                        Hook<"ledger", "solidity.string.escape",
                             !strconcat(prefix, "Postings.ledger")>,
                        Direct<"direction",
                               !strconcat(prefix, "Postings.direction")>,
                        Hook<"amount", "solidity.operand.format",
                             !strconcat(prefix, "Postings.amount")>
                      ]>,
                      Emit<"SolTemporalTotalUpdate", [
                        Direct<"direction",
                               !strconcat(prefix, "Postings.direction")>,
                        Hook<"amount", "solidity.operand.format",
                             !strconcat(prefix, "Postings.amount")>
                      ]>,
                      Emit<"SolTemporalPostingEmit", [
                        Hook<"name", "solidity.identifier.escape",
                             !strconcat(prefix, "Postings.name")>,
                        Direct<"direction",
                               !strconcat(prefix, "Postings.direction")>,
                        Nested<"args", Sequence<[
                          Emit<"SolTemporalPostingArgs", [
                            Hook<"party", "solidity.operand.format",
                                 !strconcat(prefix, "Postings.party")>,
                            Hook<"amount", "solidity.operand.format",
                                 !strconcat(prefix, "Postings.amount")>,
                            Hook<"currency", "solidity.operand.format",
                                 !strconcat(prefix, "Postings.currency")>,
                            Nested<"memo", Sequence<[
                              OptionalOp<!strconcat(prefix, "PostingMemo"), Sequence<[
                                Emit<"SolTemporalMemoArg", [
                                  Hook<"memo", "solidity.string.escape",
                                       !strconcat(prefix, "Postings.memo")>
                                ]>
                              ]>>
                            ]>>
                          ]>
                        ]>>
                      ]>
                    ]>>,
                    OptionalOp<!strconcat(prefix, "PostingGuard"), Sequence<[
                      Emit<"SolEffectfulPostingGuard", [
                        Hook<"condition", "solidity.expression.leaf",
                             !strconcat(prefix, "PostingGuard.expression")>,
                        Nested<"body", Sequence<[
                          Emit<"SolTemporalNetUpdate", [
                            Hook<"ledger", "solidity.string.escape",
                                 !strconcat(prefix, "Postings.ledger")>,
                            Direct<"direction",
                                   !strconcat(prefix, "Postings.direction")>,
                            Hook<"amount", "solidity.operand.format",
                                 !strconcat(prefix, "Postings.amount")>
                          ]>,
                          Emit<"SolTemporalTotalUpdate", [
                            Direct<"direction",
                                   !strconcat(prefix, "Postings.direction")>,
                            Hook<"amount", "solidity.operand.format",
                                 !strconcat(prefix, "Postings.amount")>
                          ]>,
                          Emit<"SolTemporalPostingEmit", [
                            Hook<"name", "solidity.identifier.escape",
                                 !strconcat(prefix, "Postings.name")>,
                            Direct<"direction",
                                   !strconcat(prefix, "Postings.direction")>,
                            Nested<"args", Sequence<[
                              Emit<"SolTemporalPostingArgs", [
                                Hook<"party", "solidity.operand.format",
                                     !strconcat(prefix, "Postings.party")>,
                                Hook<"amount", "solidity.operand.format",
                                     !strconcat(prefix, "Postings.amount")>,
                                Hook<"currency", "solidity.operand.format",
                                     !strconcat(prefix, "Postings.currency")>,
                                Nested<"memo", Sequence<[
                                  OptionalOp<!strconcat(prefix, "PostingMemo"),
                                             Sequence<[
                                    Emit<"SolTemporalMemoArg", [
                                      Hook<"memo", "solidity.string.escape",
                                           !strconcat(prefix, "Postings.memo")>
                                    ]>
                                  ]>>
                                ]>>
                              ]>
                            ]>>
                          ]>
                        ]>>
                      ]>
                    ]>>
                  ]>>,
                  Emit<"SolTemporalBlank", []>,
                  ForEach<!strconcat(prefix, "BalanceAssertions"), Sequence<[
                    Emit<"SolTemporalBalance", []>
                  ]>>,
                  Emit<"SolTemporalTransition", [
                    Direct<"status", !strconcat(prefix, "SuccessRole.status")>
                  ]>,
                  Emit<"SolTemporalReconciledEmit", [
                    Hook<"name", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.procedure")>,
                    Hook<"key", "solidity.identifier.escape",
                         !strconcat(prefix, "Execution.instanceKey")>
                  ]>
                ]>>
              ]>
            ]>>,
            Nested<"sourceCanonicalizations", Sequence<[
              ForEach<!strconcat(prefix, "SourceCanonicalizations"),
                      Sequence<[
                Emit<"SolSourceCanonicalization", [
                  Direct<"canonicalization",
                         !strconcat(prefix,
                                    "SourceCanonicalizations.canonicalization")>
                ]>
              ]>>
            ]>>
          ]>
        ]>
      >;

def SolidityEffectfulWithoutAttestationContract : TargetIdiomRecipe<
  "solidity.effectful.contract.without-attestation.v1", "solidity",
  "QuorumAcceptance.None", "Effectful", "NotApplicable", [
    One<"effectWithoutExecution", "FinalizedTemporalExecution">,
    One<"effectWithoutInitialRole", "FinalizedTemporalRole">,
    One<"effectWithoutSuccessRole", "FinalizedTemporalRole">,
    Many<"effectWithoutSourceCanonicalizations", "FinalizedSourceCanonicalization", 0, "unbounded", "effectWithoutSourceCanonicalizations.ordinal">,
    Optional<"effectWithoutWithAttestation", "FinalizedEffectfulWithAttestation">,
    Optional<"effectWithoutWithoutAttestation", "FinalizedEffectfulWithoutAttestation">,
    Many<"effectWithoutParams", "FinalizedTemporalParam", 1, "unbounded", "effectWithoutParams.ordinal">,
    Many<"effectWithoutComputes", "FinalizedTemporalCompute", 0, "unbounded", "effectWithoutComputes.ordinal">,
    Many<"effectWithoutPostings", "FinalizedTemporalPosting", 1, "unbounded", "effectWithoutPostings.ordinal">,
    RelatedOptional<"effectWithoutPostingMemo", "FinalizedTemporalMemo", "effectWithoutPostings", PresenceMemo>,
    RelatedOptional<"effectWithoutPostingDirect", "FinalizedEffectfulDirectPosting", "effectWithoutPostings", PresenceDirect>,
    RelatedOptional<"effectWithoutPostingGuard", "FinalizedEffectfulPostingGuard", "effectWithoutPostings", PresenceGuard>,
    Many<"effectWithoutBalanceAssertions", "FinalizedTemporalBalance", 1, "unbounded", "effectWithoutBalanceAssertions.ordinal">
  ],
  "SolTemporalContractModel", CardinalityOne,
  Sequence<[
      Emit<"SolEffectfulUngatedContract", [Hook<"name", "solidity.identifier.escape", "effectWithoutExecution.procedure">, Nested<"header", Sequence<[
      Emit<"SolTemporalSpdx", []>,
      Emit<"SolTemporalPragma", []>,
      Emit<"SolTemporalBlank", []>,
      OptionalOp<"effectWithoutWithAttestation", Sequence<[
      Call<"solidity.guard-consumer.effectful.v1", []>,
      Emit<"SolTemporalBlank", []>
    ]>>,
      Emit<"SolTemporalGeneratedComment", []>,
      Emit<"SolTemporalCoordinationComment", []>,
      Emit<"SolEffectfulAttestationComment", []>,
      Emit<"SolTemporalAuthorityComment", []>,
      Emit<"SolTemporalKeyComment", []>,
      Emit<"SolEffectfulIsolationComment", []>
    ]>>, Nested<"body", Sequence<[
      Emit<"SolStatusEnum", [Direct<"initial", "effectWithoutInitialRole.status">, Direct<"success", "effectWithoutSuccessRole.status">]>,
      Emit<"SolTemporalBlank", []>,
      Emit<"SolTemporalTriggerEvent", [Hook<"name", "solidity.identifier.escape", "effectWithoutExecution.invokedEvent">, Nested<"params", Sequence<[
      Emit<"SolTemporalStringKeyParam", [Hook<"name", "solidity.identifier.escape", "effectWithoutExecution.instanceKey">]>
    ]>>]>,
      ForEach<"effectWithoutComputes", Sequence<[
      Emit<"SolTemporalComputedEvent", [Hook<"name", "solidity.identifier.escape", "effectWithoutComputes.name">, Nested<"params", Sequence<[Emit<"SolTemporalUintValueParam", []>]>>]>
    ]>>,
      ForEach<"effectWithoutPostings", Sequence<[
      Emit<"SolTemporalPostingEvent", [Hook<"name", "solidity.identifier.escape", "effectWithoutPostings.name">, Direct<"direction", "effectWithoutPostings.direction">, Nested<"params", Sequence<[
      Emit<"SolTemporalPostingPartyParam", []>,
      Emit<"SolTemporalPostingAmountParam", []>,
      Emit<"SolTemporalPostingCurrencyParam", []>,
      OptionalOp<"effectWithoutPostingMemo", Sequence<[Emit<"SolTemporalPostingMemoParam", []>]>>
    ]>>]>
    ]>>,
      Emit<"SolTemporalReconciledEvent", [Hook<"name", "solidity.identifier.escape", "effectWithoutExecution.procedure">, Nested<"params", Sequence<[
      Emit<"SolTemporalStringKeyParam", [Hook<"name", "solidity.identifier.escape", "effectWithoutExecution.instanceKey">]>
    ]>>]>,
      Emit<"SolTemporalBlank", []>,
      Emit<"SolTemporalStatusStorage", []>,
      OptionalOp<"effectWithoutWithoutAttestation", Sequence<[Emit<"SolEffectfulAttestedStorage", []>]>>,
      Emit<"SolTemporalNetStorage", []>,
      Emit<"SolTemporalDebitStorage", []>,
      Emit<"SolTemporalCreditStorage", []>,
      OptionalOp<"effectWithoutWithAttestation", Sequence<[Emit<"SolEffectfulGuardStorage", []>]>>,
      OptionalOp<"effectWithoutWithAttestation", Sequence<[
      Emit<"SolTemporalBlank", []>,
      Call<"solidity.effectful.primitive.with-attestation.v1", []>
    ]>>,
      OptionalOp<"effectWithoutWithoutAttestation", Sequence<[
      Emit<"SolTemporalBlank", []>,
      Call<"solidity.effectful.primitive.without-attestation.v1", [Direct<"effectExecution", "effectWithoutExecution.item">, Direct<"effectInitialRole", "effectWithoutInitialRole.item">]>
    ]>>,
      Emit<"SolTemporalBlank", []>,
      Emit<"SolEffectfulExecute", [Nested<"params", Sequence<[
      ForEach<"effectWithoutParams", Sequence<[
      Emit<"SolTemporalExecuteParam", [Hook<"name", "solidity.identifier.escape", "effectWithoutParams.name">, Hook<"type", "solidity.type.spell", "effectWithoutParams.type">]>
    ]>>
    ]>>, Nested<"body", Sequence<[
      Emit<"SolTemporalReplayKey", [Hook<"key", "solidity.identifier.escape", "effectWithoutExecution.replayKey">]>,
      Emit<"SolEffectfulExecuteReplayRequire", [Direct<"status", "effectWithoutInitialRole.status">]>,
      OptionalOp<"effectWithoutWithAttestation", Sequence<[Emit<"SolEffectfulGuardAcceptance", []>]>>,
      OptionalOp<"effectWithoutWithoutAttestation", Sequence<[Emit<"SolEffectfulSelfAcceptance", []>]>>,
      Emit<"SolTemporalTriggerEmit", [Hook<"event", "solidity.identifier.escape", "effectWithoutExecution.invokedEvent">, Hook<"key", "solidity.identifier.escape", "effectWithoutExecution.instanceKey">]>,
      Emit<"SolTemporalBlank", []>,
      ForEach<"effectWithoutComputes", Sequence<[
      Emit<"SolTemporalComputeDecl", [Hook<"name", "solidity.identifier.escape", "effectWithoutComputes.name">, Hook<"expression", "solidity.expression.leaf", "effectWithoutComputes.expression">]>,
      Emit<"SolTemporalComputeEmit", [Hook<"name", "solidity.identifier.escape", "effectWithoutComputes.name">]>
    ]>>,
      Emit<"SolTemporalBlank", []>,
      ForEach<"effectWithoutPostings", Sequence<[
      OptionalOp<"effectWithoutPostingDirect", Sequence<[
      Emit<"SolTemporalNetUpdate", [Hook<"ledger", "solidity.string.escape", "effectWithoutPostings.ledger">, Direct<"direction", "effectWithoutPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithoutPostings.amount">]>,
      Emit<"SolTemporalTotalUpdate", [Direct<"direction", "effectWithoutPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithoutPostings.amount">]>,
      Emit<"SolTemporalPostingEmit", [Hook<"name", "solidity.identifier.escape", "effectWithoutPostings.name">, Direct<"direction", "effectWithoutPostings.direction">, Nested<"args", Sequence<[
      Emit<"SolTemporalPostingArgs", [Hook<"party", "solidity.operand.format", "effectWithoutPostings.party">, Hook<"amount", "solidity.operand.format", "effectWithoutPostings.amount">, Hook<"currency", "solidity.operand.format", "effectWithoutPostings.currency">, Nested<"memo", Sequence<[
      OptionalOp<"effectWithoutPostingMemo", Sequence<[
      Emit<"SolTemporalMemoArg", [Hook<"memo", "solidity.string.escape", "effectWithoutPostings.memo">]>
    ]>>
    ]>>]>
    ]>>]>
    ]>>,
      OptionalOp<"effectWithoutPostingGuard", Sequence<[
      Emit<"SolEffectfulPostingGuard", [Hook<"condition", "solidity.expression.leaf", "effectWithoutPostingGuard.expression">, Nested<"body", Sequence<[
      Emit<"SolTemporalNetUpdate", [Hook<"ledger", "solidity.string.escape", "effectWithoutPostings.ledger">, Direct<"direction", "effectWithoutPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithoutPostings.amount">]>,
      Emit<"SolTemporalTotalUpdate", [Direct<"direction", "effectWithoutPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithoutPostings.amount">]>,
      Emit<"SolTemporalPostingEmit", [Hook<"name", "solidity.identifier.escape", "effectWithoutPostings.name">, Direct<"direction", "effectWithoutPostings.direction">, Nested<"args", Sequence<[
      Emit<"SolTemporalPostingArgs", [Hook<"party", "solidity.operand.format", "effectWithoutPostings.party">, Hook<"amount", "solidity.operand.format", "effectWithoutPostings.amount">, Hook<"currency", "solidity.operand.format", "effectWithoutPostings.currency">, Nested<"memo", Sequence<[
      OptionalOp<"effectWithoutPostingMemo", Sequence<[
      Emit<"SolTemporalMemoArg", [Hook<"memo", "solidity.string.escape", "effectWithoutPostings.memo">]>
    ]>>
    ]>>]>
    ]>>]>
    ]>>]>
    ]>>
    ]>>,
      Emit<"SolTemporalBlank", []>,
      ForEach<"effectWithoutBalanceAssertions", Sequence<[Emit<"SolTemporalBalance", []>]>>,
      Emit<"SolTemporalTransition", [Direct<"status", "effectWithoutSuccessRole.status">]>,
      Emit<"SolTemporalReconciledEmit", [Hook<"name", "solidity.identifier.escape", "effectWithoutExecution.procedure">, Hook<"key", "solidity.identifier.escape", "effectWithoutExecution.instanceKey">]>
    ]>>]>
    ]>>, Nested<"sourceCanonicalizations", Sequence<[
      ForEach<"effectWithoutSourceCanonicalizations", Sequence<[
      Emit<"SolSourceCanonicalization", [Direct<"canonicalization", "effectWithoutSourceCanonicalizations.canonicalization">]>
    ]>>
    ]>>]>
    ]>>;
def SolidityEffectfulWithAttestationContract : TargetIdiomRecipe<
  "solidity.effectful.contract.with-attestation.v1", "solidity",
  "QuorumAcceptance.Single", "Effectful", "NotApplicable", [
    One<"effectWithExecution", "FinalizedTemporalExecution">,
    One<"effectWithInitialRole", "FinalizedTemporalRole">,
    One<"effectWithSuccessRole", "FinalizedTemporalRole">,
    Many<"effectWithSourceCanonicalizations", "FinalizedSourceCanonicalization", 0, "unbounded", "effectWithSourceCanonicalizations.ordinal">,
    Optional<"effectWithWithAttestation", "FinalizedEffectfulWithAttestation">,
    Optional<"effectWithWithoutAttestation", "FinalizedEffectfulWithoutAttestation">,
    Many<"effectWithParams", "FinalizedTemporalParam", 1, "unbounded", "effectWithParams.ordinal">,
    Many<"effectWithComputes", "FinalizedTemporalCompute", 0, "unbounded", "effectWithComputes.ordinal">,
    Many<"effectWithPostings", "FinalizedTemporalPosting", 1, "unbounded", "effectWithPostings.ordinal">,
    RelatedOptional<"effectWithPostingMemo", "FinalizedTemporalMemo", "effectWithPostings", PresenceMemo>,
    RelatedOptional<"effectWithPostingDirect", "FinalizedEffectfulDirectPosting", "effectWithPostings", PresenceDirect>,
    RelatedOptional<"effectWithPostingGuard", "FinalizedEffectfulPostingGuard", "effectWithPostings", PresenceGuard>,
    Many<"effectWithBalanceAssertions", "FinalizedTemporalBalance", 1, "unbounded", "effectWithBalanceAssertions.ordinal">
  ],
  "SolTemporalContractModel", CardinalityOne,
  Sequence<[
      Emit<"SolEffectfulGatedContract", [Hook<"name", "solidity.identifier.escape", "effectWithExecution.procedure">, Nested<"header", Sequence<[
      Emit<"SolTemporalSpdx", []>,
      Emit<"SolTemporalPragma", []>,
      Emit<"SolTemporalBlank", []>,
      OptionalOp<"effectWithWithAttestation", Sequence<[
      Call<"solidity.guard-consumer.effectful.v1", []>,
      Emit<"SolTemporalBlank", []>
    ]>>,
      Emit<"SolTemporalGeneratedComment", []>,
      Emit<"SolTemporalCoordinationComment", []>,
      Emit<"SolEffectfulAttestationComment", []>,
      Emit<"SolTemporalAuthorityComment", []>,
      Emit<"SolTemporalKeyComment", []>,
      Emit<"SolEffectfulIsolationComment", []>
    ]>>, Nested<"body", Sequence<[
      Emit<"SolStatusEnum", [Direct<"initial", "effectWithInitialRole.status">, Direct<"success", "effectWithSuccessRole.status">]>,
      Emit<"SolTemporalBlank", []>,
      Emit<"SolTemporalTriggerEvent", [Hook<"name", "solidity.identifier.escape", "effectWithExecution.invokedEvent">, Nested<"params", Sequence<[
      Emit<"SolTemporalStringKeyParam", [Hook<"name", "solidity.identifier.escape", "effectWithExecution.instanceKey">]>
    ]>>]>,
      ForEach<"effectWithComputes", Sequence<[
      Emit<"SolTemporalComputedEvent", [Hook<"name", "solidity.identifier.escape", "effectWithComputes.name">, Nested<"params", Sequence<[Emit<"SolTemporalUintValueParam", []>]>>]>
    ]>>,
      ForEach<"effectWithPostings", Sequence<[
      Emit<"SolTemporalPostingEvent", [Hook<"name", "solidity.identifier.escape", "effectWithPostings.name">, Direct<"direction", "effectWithPostings.direction">, Nested<"params", Sequence<[
      Emit<"SolTemporalPostingPartyParam", []>,
      Emit<"SolTemporalPostingAmountParam", []>,
      Emit<"SolTemporalPostingCurrencyParam", []>,
      OptionalOp<"effectWithPostingMemo", Sequence<[Emit<"SolTemporalPostingMemoParam", []>]>>
    ]>>]>
    ]>>,
      Emit<"SolTemporalReconciledEvent", [Hook<"name", "solidity.identifier.escape", "effectWithExecution.procedure">, Nested<"params", Sequence<[
      Emit<"SolTemporalStringKeyParam", [Hook<"name", "solidity.identifier.escape", "effectWithExecution.instanceKey">]>
    ]>>]>,
      Emit<"SolTemporalBlank", []>,
      Emit<"SolTemporalStatusStorage", []>,
      OptionalOp<"effectWithWithoutAttestation", Sequence<[Emit<"SolEffectfulAttestedStorage", []>]>>,
      Emit<"SolTemporalNetStorage", []>,
      Emit<"SolTemporalDebitStorage", []>,
      Emit<"SolTemporalCreditStorage", []>,
      OptionalOp<"effectWithWithAttestation", Sequence<[Emit<"SolEffectfulGuardStorage", []>]>>,
      OptionalOp<"effectWithWithAttestation", Sequence<[
      Emit<"SolTemporalBlank", []>,
      Call<"solidity.effectful.primitive.with-attestation.v1", []>
    ]>>,
      OptionalOp<"effectWithWithoutAttestation", Sequence<[
      Emit<"SolTemporalBlank", []>,
      Call<"solidity.effectful.primitive.without-attestation.v1", [Direct<"effectExecution", "effectWithExecution.item">, Direct<"effectInitialRole", "effectWithInitialRole.item">]>
    ]>>,
      Emit<"SolTemporalBlank", []>,
      Emit<"SolEffectfulExecute", [Nested<"params", Sequence<[
      ForEach<"effectWithParams", Sequence<[
      Emit<"SolTemporalExecuteParam", [Hook<"name", "solidity.identifier.escape", "effectWithParams.name">, Hook<"type", "solidity.type.spell", "effectWithParams.type">]>
    ]>>
    ]>>, Nested<"body", Sequence<[
      Emit<"SolTemporalReplayKey", [Hook<"key", "solidity.identifier.escape", "effectWithExecution.replayKey">]>,
      Emit<"SolEffectfulExecuteReplayRequire", [Direct<"status", "effectWithInitialRole.status">]>,
      OptionalOp<"effectWithWithAttestation", Sequence<[Emit<"SolEffectfulGuardAcceptance", []>]>>,
      OptionalOp<"effectWithWithoutAttestation", Sequence<[Emit<"SolEffectfulSelfAcceptance", []>]>>,
      Emit<"SolTemporalTriggerEmit", [Hook<"event", "solidity.identifier.escape", "effectWithExecution.invokedEvent">, Hook<"key", "solidity.identifier.escape", "effectWithExecution.instanceKey">]>,
      Emit<"SolTemporalBlank", []>,
      ForEach<"effectWithComputes", Sequence<[
      Emit<"SolTemporalComputeDecl", [Hook<"name", "solidity.identifier.escape", "effectWithComputes.name">, Hook<"expression", "solidity.expression.leaf", "effectWithComputes.expression">]>,
      Emit<"SolTemporalComputeEmit", [Hook<"name", "solidity.identifier.escape", "effectWithComputes.name">]>
    ]>>,
      Emit<"SolTemporalBlank", []>,
      ForEach<"effectWithPostings", Sequence<[
      OptionalOp<"effectWithPostingDirect", Sequence<[
      Emit<"SolTemporalNetUpdate", [Hook<"ledger", "solidity.string.escape", "effectWithPostings.ledger">, Direct<"direction", "effectWithPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithPostings.amount">]>,
      Emit<"SolTemporalTotalUpdate", [Direct<"direction", "effectWithPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithPostings.amount">]>,
      Emit<"SolTemporalPostingEmit", [Hook<"name", "solidity.identifier.escape", "effectWithPostings.name">, Direct<"direction", "effectWithPostings.direction">, Nested<"args", Sequence<[
      Emit<"SolTemporalPostingArgs", [Hook<"party", "solidity.operand.format", "effectWithPostings.party">, Hook<"amount", "solidity.operand.format", "effectWithPostings.amount">, Hook<"currency", "solidity.operand.format", "effectWithPostings.currency">, Nested<"memo", Sequence<[
      OptionalOp<"effectWithPostingMemo", Sequence<[
      Emit<"SolTemporalMemoArg", [Hook<"memo", "solidity.string.escape", "effectWithPostings.memo">]>
    ]>>
    ]>>]>
    ]>>]>
    ]>>,
      OptionalOp<"effectWithPostingGuard", Sequence<[
      Emit<"SolEffectfulPostingGuard", [Hook<"condition", "solidity.expression.leaf", "effectWithPostingGuard.expression">, Nested<"body", Sequence<[
      Emit<"SolTemporalNetUpdate", [Hook<"ledger", "solidity.string.escape", "effectWithPostings.ledger">, Direct<"direction", "effectWithPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithPostings.amount">]>,
      Emit<"SolTemporalTotalUpdate", [Direct<"direction", "effectWithPostings.direction">, Hook<"amount", "solidity.operand.format", "effectWithPostings.amount">]>,
      Emit<"SolTemporalPostingEmit", [Hook<"name", "solidity.identifier.escape", "effectWithPostings.name">, Direct<"direction", "effectWithPostings.direction">, Nested<"args", Sequence<[
      Emit<"SolTemporalPostingArgs", [Hook<"party", "solidity.operand.format", "effectWithPostings.party">, Hook<"amount", "solidity.operand.format", "effectWithPostings.amount">, Hook<"currency", "solidity.operand.format", "effectWithPostings.currency">, Nested<"memo", Sequence<[
      OptionalOp<"effectWithPostingMemo", Sequence<[
      Emit<"SolTemporalMemoArg", [Hook<"memo", "solidity.string.escape", "effectWithPostings.memo">]>
    ]>>
    ]>>]>
    ]>>]>
    ]>>]>
    ]>>
    ]>>,
      Emit<"SolTemporalBlank", []>,
      ForEach<"effectWithBalanceAssertions", Sequence<[Emit<"SolTemporalBalance", []>]>>,
      Emit<"SolTemporalTransition", [Direct<"status", "effectWithSuccessRole.status">]>,
      Emit<"SolTemporalReconciledEmit", [Hook<"name", "solidity.identifier.escape", "effectWithExecution.procedure">, Hook<"key", "solidity.identifier.escape", "effectWithExecution.instanceKey">]>
    ]>>]>
    ]>>, Nested<"sourceCanonicalizations", Sequence<[
      ForEach<"effectWithSourceCanonicalizations", Sequence<[
      Emit<"SolSourceCanonicalization", [Direct<"canonicalization", "effectWithSourceCanonicalizations.canonicalization">]>
    ]>>
    ]>>]>
    ]>>;
