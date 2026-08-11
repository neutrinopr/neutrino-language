//===- SolidityIdiomRecipes.td - generated Solidity idiom recipes ---------===//
//
// The initial  package slice: the closed quorum-acceptance consumer
// interface shared by Evidence, Temporal, and Effectful coordinations.  The
// three rows differ only in their exact finalized resolution keys.  Their
// target shape is identical except for the already-selected key-noun comment.
//
//===----------------------------------------------------------------------===//

include "BackendIdiom.td"

def FinalizedSourceCanonicalization
    : FinalizedType<"FinalizedSourceCanonicalization", [
        FinalizedField<"canonicalization", "TypedStringLiteral">,
        FinalizedField<"ordinal", "SemanticOrdinal">
      ]>;

def SolSourceCanonicalizationNode
    : TargetNode<"SolSourceCanonicalization",
                 "SolSourceCanonicalization", [
        TargetField<"canonicalization", "value", "TypedStringLiteral">
      ], "source-canonicalization">;

// : the full evidence-contract recipe (owns the reachable
// (QuorumAcceptance.Single, Evidence) key; Calls the internal guard consumer).
include "solidity/recipes/SolidityTemporalIdiomRecipes.td"
include "solidity/recipes/SolidityEffectfulIdiomRecipes.td"
include "solidity/recipes/SolidityEvidenceIdiomRecipes.td"

def GuardIntroComment : TargetNode<
    "GuardIntroComment", "SolStatement", [], "doc-comment",
    ["The on-chain M-of-N quorum acceptance guard (/) this coordination is gated by."]>;
def GuardObserversComment
    : TargetNode<"GuardObserversComment", "SolStatement", [], "doc-comment",
                 ["A claimId is accepted only after >= M distinct authorized observers signed the canonical"]>;
def GuardClaimComment : TargetNode<
    "GuardClaimComment", "SolStatement", [], "doc-comment",
    ["claim (verified in ThresholdQuorumAcceptance). The coordination keys acceptance by its"]>;
def GuardEvidenceKeyComment
    : TargetNode<"GuardEvidenceKeyComment", "SolStatement", [], "doc-comment",
                 ["instance key, so it can never proceed on unattested evidence."]>;
def GuardWorkflowKeyComment
    : TargetNode<"GuardWorkflowKeyComment", "SolStatement", [], "doc-comment",
                 ["workflow key, so it can never proceed on unattested evidence."]>;

def GuardIsAcceptedSignature
    : TargetNode<"GuardIsAcceptedSignature", "SolInterfaceSignature", [],
                 "interface-signature",
                 ["isAccepted", "bytes32", "claimId", "bool"]>;
def GuardAcceptedExecutionClaimSignature
    : TargetNode<"GuardAcceptedExecutionClaimSignature",
                 "SolInterfaceSignature", [], "interface-signature",
                 ["acceptedExecutionClaim", "bytes32", "claimId", "bytes32"]>;
def GuardInterfaceShell : TargetNode<"GuardInterfaceShell", "SolStatement", [
  TargetField<"signatures", "nodes", "SolInterfaceSignature",
              "many", 2, "2">
], "interface-shell", ["IThresholdQuorumAcceptance"]>;

class GuardConsumerRecipe<string recipeId, string finalizedKind, string mode,
                          TargetNode keyComment>
    : TargetIdiomRecipe<
        recipeId, "solidity", finalizedKind, mode, "NotApplicable", [],
        "SolStatement", CardinalityMany<5, "5">,
        Sequence<[
          Emit<"GuardIntroComment", []>,
          Emit<"GuardObserversComment", []>,
          Emit<"GuardClaimComment", []>,
          Emit<keyComment.Name, []>,
          Emit<"GuardInterfaceShell", [
            Nested<"signatures", Sequence<[
              Emit<"GuardIsAcceptedSignature", []>,
              Emit<"GuardAcceptedExecutionClaimSignature", []>
            ]>>
          ]>
        ]>
      >;

def SolidityGuardConsumerEvidence : TargetIdiomRecipe<
  "solidity.guard-consumer.evidence.v1", "solidity",
  "GuardConsumer", "Evidence", "NotApplicable", [],
  "SolStatement", CardinalityMany<5, "5">,
  Sequence<[
      Emit<"GuardIntroComment", []>,
      Emit<"GuardObserversComment", []>,
      Emit<"GuardClaimComment", []>,
      Emit<"GuardEvidenceKeyComment", []>,
      Emit<"GuardInterfaceShell", [Nested<"signatures", Sequence<[
      Emit<"GuardIsAcceptedSignature", []>,
      Emit<"GuardAcceptedExecutionClaimSignature", []>
    ]>>]>
    ]>>;
def SolidityGuardConsumerTemporal : TargetIdiomRecipe<
  "solidity.guard-consumer.temporal.v1", "solidity",
  "GuardConsumer", "Temporal", "NotApplicable", [],
  "SolStatement", CardinalityMany<5, "5">,
  Sequence<[
      Emit<"GuardIntroComment", []>,
      Emit<"GuardObserversComment", []>,
      Emit<"GuardClaimComment", []>,
      Emit<"GuardWorkflowKeyComment", []>,
      Emit<"GuardInterfaceShell", [Nested<"signatures", Sequence<[
      Emit<"GuardIsAcceptedSignature", []>,
      Emit<"GuardAcceptedExecutionClaimSignature", []>
    ]>>]>
    ]>>;
def SolidityGuardConsumerEffectful : TargetIdiomRecipe<
  "solidity.guard-consumer.effectful.v1", "solidity",
  "GuardConsumer", "Effectful", "NotApplicable", [],
  "SolStatement", CardinalityMany<5, "5">,
  Sequence<[
      Emit<"GuardIntroComment", []>,
      Emit<"GuardObserversComment", []>,
      Emit<"GuardClaimComment", []>,
      Emit<"GuardWorkflowKeyComment", []>,
      Emit<"GuardInterfaceShell", [Nested<"signatures", Sequence<[
      Emit<"GuardIsAcceptedSignature", []>,
      Emit<"GuardAcceptedExecutionClaimSignature", []>
    ]>>]>
    ]>>;
