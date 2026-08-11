//===- SolidityProjectionSchema.td - Solidity finalized-view projection ---===//
//
//  R5b slice A.2: the Solidity-local, declarative description of the
// finalized-view TRIO — project() / slotExtent() / slotItemOrder() — that the
// provider used to carry as three handwritten cascades. Each row reduces one
// projected field, one slot extent, or one slot ordering to a finite STRUCTURAL
// accessor over projection::FinalizedProjectionSequence: a scalar member, a
// constant-empty leaf, a vector .size(), an indexed member (identity /
// to-string), a leaf transform (uint/string tab-prefix, direction enum-cast,
// memo value), an expression save, the  conditional-ordinal instance-key
// sub-read, or a posting navigation. It reads NO capability-spec / plan /
// domain field and makes NO decision on backend meaning — it only NAMES which
// already-finalized accessor the generic resolver applies. The ONLY leaf-hook it
// still CALLS is solidityStatusAtom (the  (mode,role) -> atom accessor).
//
// scripts/generators/backend_recipe_gen.py --profile solidity-projection runs
// the pinned llvm-tblgen --dump-json over this file and emits the committed
// generated/SolidityProjection.inc dispatch resolver (mirrors the
// SolidityRecipeBuilders.inc pattern). It is keyed on the symbolic
// solidity_Slot_* / solidity_Field_* / solidity_Value_* constants generated into
// solidity_recipes.inc; the .inc is included in the provider AFTER that module.
//
// This is a Solidity-LOCAL schema: it does NOT touch the PG-shared
// BackendIdiom.td, and is loaded only by the solidity-projection profile.
//
//===----------------------------------------------------------------------===//

include "solidity/model/SolidityTargetNodes.td"

// One projection accessor. Every kind is a subclass of the shared
// SolRecipeBuilderArg vocabulary so the schema carries a single accessor type;
// the generator dispatches on `Kind`. Field names are neutral (no semantic
// selection authority lives in the table).

// A scalar member of the finalized execution identity
// (`sequence.executionIdentity.<member>`).
class SolExecScalar<string member> : SolRecipeBuilderArg<"exec-scalar", member>;

// A constant-empty leaf (`save(<value>, "")`) — the typed `item` carrier that
// the recipe consumes structurally without a projected string. (A parameterless
// accessor: a shared def, referenced directly by the projection rows.)
def SolEmptyProj : SolRecipeBuilderArg<"proj-empty">;

// A vector cardinality (`std::to_string(sequence.<container>.size())`).
class SolSizeProj<string container> : SolRecipeBuilderArg<"proj-size", container>;

// The  lifecycle status atom leaf-hook
// (`solidityStatusAtom(sequence.<role>.mode, sequence.<role>.role)`).
class SolStatusAtomProj<string role> : SolRecipeBuilderArg<"status-atom", role>;

// An indexed member of a Many vector (`sequence.<container>.at(owner.index).
// <member>`), optionally to-string transformed for an ordinal.
class SolIndexedProj<string container, string member, string transform = "identity">
    : SolRecipeBuilderArg<"proj-indexed", container, "", "", "", transform,
                          [member]>;

// The claim-input operand leaf
// (`"claim\t" + item.type + "\t" + item.name`, item = claimInputs.at(index)).
def SolClaimOperandProj : SolRecipeBuilderArg<"claim-operand", "claimInputs">;

// An expression save of an indexed member pointer
// (`saveExpression(*sequence.<container>.at(owner.index).<member>)`).
class SolIndexedExprProj<string container, string member>
    : SolRecipeBuilderArg<"proj-indexed-expr", container, "", "", "", "identity",
                          [member]>;

// A posting navigation. `nav` is "flat" (sequence.postings.at(owner.index)) or
// "group" (effectGroups[ctx].finalizedPostings.at(owner.index)); `transform`
// selects the leaf shape: posting-id (LedgerPosting scalar), direction
// (enum-cast), string-operand / uint-operand (tab-prefixed operand), memo
// (FinalizedPostingProjection memo value).
class SolPostingProj<string nav, string member, string transform>
    : SolRecipeBuilderArg<"proj-posting", member, nav, "", "", transform>;

// The optional posting comparison-guard expression save (navigates the parent
// posting via ctx and saves its comparisonGuard).
def SolPostingGuardProj : SolRecipeBuilderArg<"proj-posting-guard">;

// One projected field: the solidity_Field_<field> id, the solidity_Value_<value>
// leaf-type it saves (unused for expression kinds), and its accessor.
class SolProjectField<string fieldId, string valueName,
                      SolRecipeBuilderArg accessor> {
  string Field = fieldId;
  string Value = valueName;
  SolRecipeBuilderArg Accessor = accessor;
}

// One slot extent. `kind` is const-one | attest-single | attest-none |
// vector-size | group-postings-size; `container` names the sized vector for the
// vector-size kind. The optional posting-presence slots are resolved by the
// generated generic tail (SlotRow presence + solidityOptionalSlotExtent), not by
// a row here.
class SolSlotExtent<string slot, string kind, string container = ""> {
  string Slot = slot;
  string Kind = kind;
  string Container = container;
}

// One slot item ordering. `kind` is at-ordinal (sequence.<container>.at(index)
// .ordinal) | identity (return index) | group-postings-ordinal (two-level).
class SolSlotItemOrder<string slot, string kind, string container = ""> {
  string Slot = slot;
  string Kind = kind;
  string Container = container;
}

//===----------------------------------------------------------------------===//
// project() — one row per finalized field.
//===----------------------------------------------------------------------===//

def : SolProjectField<"execution.procedure", "TargetIdentifierAtom", SolExecScalar<"procedureNamespace">>;
def : SolProjectField<"initialRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"initialLifecycleRole">>;
def : SolProjectField<"successRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"successLifecycleRole">>;
def : SolProjectField<"execution.invokedEvent", "TargetIdentifierAtom", SolExecScalar<"invokedEvent">>;
def : SolProjectField<"execution.instanceKey", "TargetIdentifierAtom", SolExecScalar<"instanceKey">>;
def : SolProjectField<"computes.name", "TargetIdentifierAtom", SolIndexedProj<"values.computes", "name">>;
def : SolProjectField<"postings.name", "TargetIdentifierAtom", SolPostingProj<"flat", "name", "posting-id">>;
def : SolProjectField<"postings.direction", "PostingDirectionAtom", SolPostingProj<"flat", "direction", "direction">>;
def : SolProjectField<"temporalPolicies.name", "TargetIdentifierAtom", SolIndexedProj<"temporalPolicies", "targetIdentifier">>;
def : SolProjectField<"params.name", "TargetIdentifierAtom", SolIndexedProj<"values.params", "name">>;
def : SolProjectField<"params.type", "FinalizedTargetType", SolIndexedProj<"values.params", "type">>;
def : SolProjectField<"execution.replayKey", "TargetIdentifierAtom", SolExecScalar<"replayKey">>;
def : SolProjectField<"execution.claimInputCount", "CardinalityAtom", SolSizeProj<"claimInputs">>;
def : SolProjectField<"claimInputs.name", "TypedStringLiteral", SolIndexedProj<"claimInputs", "name">>;
def : SolProjectField<"claimInputs.ordinal", "SemanticOrdinal", SolIndexedProj<"claimInputs", "ordinal", "to-string">>;
def : SolProjectField<"claimInputs.category", "TypedStringLiteral", SolIndexedProj<"claimInputs", "category">>;
def : SolProjectField<"claimInputs.value", "FinalizedTypedOperand", SolClaimOperandProj>;
def : SolProjectField<"execution.coordinationIdentity", "TypedStringLiteral", SolExecScalar<"coordinationIdentity">>;
def : SolProjectField<"computes.expression", "FinalizedExpressionLeaf", SolIndexedExprProj<"values.computes", "expression">>;
def : SolProjectField<"effectGroups.policy", "TargetIdentifierAtom", SolIndexedProj<"effectGroups", "guard.policyInputBinding">>;
def : SolProjectField<"effectGroups.ordinal", "SemanticOrdinal", SolIndexedProj<"effectGroups", "ordinal", "to-string">>;
def : SolProjectField<"groupPostings.ledger", "TypedStringLiteral", SolPostingProj<"group", "ledger", "posting-id">>;
def : SolProjectField<"groupPostings.direction", "PostingDirectionAtom", SolPostingProj<"group", "direction", "direction">>;
def : SolProjectField<"groupPostings.amount", "FinalizedTypedOperand", SolPostingProj<"group", "amount", "uint-operand">>;
def : SolProjectField<"groupPostings.name", "TargetIdentifierAtom", SolPostingProj<"group", "name", "posting-id">>;
def : SolProjectField<"groupPostings.party", "FinalizedTypedOperand", SolPostingProj<"group", "party", "string-operand">>;
def : SolProjectField<"groupPostings.currency", "FinalizedTypedOperand", SolPostingProj<"group", "currency", "string-operand">>;
def : SolProjectField<"groupPostings.memo", "TypedStringLiteral", SolPostingProj<"group", "memo", "memo">>;
def : SolProjectField<"sourceCanonicalizations.canonicalization", "TypedStringLiteral", SolIndexedProj<"attestation.policies", "canonicalization">>;
def : SolProjectField<"effectExecution.instanceKey", "TargetIdentifierAtom", SolExecScalar<"instanceKey">>;
def : SolProjectField<"effectExecution.replayKey", "TargetIdentifierAtom", SolExecScalar<"replayKey">>;
def : SolProjectField<"effectInitialRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"initialLifecycleRole">>;
def : SolProjectField<"effectWithExecution.procedure", "TargetIdentifierAtom", SolExecScalar<"procedureNamespace">>;
def : SolProjectField<"effectWithInitialRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"initialLifecycleRole">>;
def : SolProjectField<"effectWithSuccessRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"successLifecycleRole">>;
def : SolProjectField<"effectWithExecution.invokedEvent", "TargetIdentifierAtom", SolExecScalar<"invokedEvent">>;
def : SolProjectField<"effectWithExecution.instanceKey", "TargetIdentifierAtom", SolExecScalar<"instanceKey">>;
def : SolProjectField<"effectWithComputes.name", "TargetIdentifierAtom", SolIndexedProj<"values.computes", "name">>;
def : SolProjectField<"effectWithPostings.name", "TargetIdentifierAtom", SolPostingProj<"flat", "name", "posting-id">>;
def : SolProjectField<"effectWithPostings.direction", "PostingDirectionAtom", SolPostingProj<"flat", "direction", "direction">>;
def : SolProjectField<"effectWithExecution.item", "FinalizedTemporalExecution", SolEmptyProj>;
def : SolProjectField<"effectWithInitialRole.item", "FinalizedTemporalRole", SolEmptyProj>;
def : SolProjectField<"effectWithParams.name", "TargetIdentifierAtom", SolIndexedProj<"values.params", "name">>;
def : SolProjectField<"effectWithParams.type", "FinalizedTargetType", SolIndexedProj<"values.params", "type">>;
def : SolProjectField<"effectWithExecution.replayKey", "TargetIdentifierAtom", SolExecScalar<"replayKey">>;
def : SolProjectField<"effectWithComputes.expression", "FinalizedExpressionLeaf", SolIndexedExprProj<"values.computes", "expression">>;
def : SolProjectField<"effectWithPostings.ledger", "TypedStringLiteral", SolPostingProj<"flat", "ledger", "posting-id">>;
def : SolProjectField<"effectWithPostings.amount", "FinalizedTypedOperand", SolPostingProj<"flat", "amount", "uint-operand">>;
def : SolProjectField<"effectWithPostings.party", "FinalizedTypedOperand", SolPostingProj<"flat", "party", "string-operand">>;
def : SolProjectField<"effectWithPostings.currency", "FinalizedTypedOperand", SolPostingProj<"flat", "currency", "string-operand">>;
def : SolProjectField<"effectWithPostings.memo", "TypedStringLiteral", SolPostingProj<"flat", "memo", "memo">>;
def : SolProjectField<"effectWithPostingGuard.expression", "FinalizedExpressionLeaf", SolPostingGuardProj>;
def : SolProjectField<"effectWithSourceCanonicalizations.canonicalization", "TypedStringLiteral", SolIndexedProj<"attestation.policies", "canonicalization">>;
def : SolProjectField<"effectWithoutExecution.procedure", "TargetIdentifierAtom", SolExecScalar<"procedureNamespace">>;
def : SolProjectField<"effectWithoutInitialRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"initialLifecycleRole">>;
def : SolProjectField<"effectWithoutSuccessRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"successLifecycleRole">>;
def : SolProjectField<"effectWithoutExecution.invokedEvent", "TargetIdentifierAtom", SolExecScalar<"invokedEvent">>;
def : SolProjectField<"effectWithoutExecution.instanceKey", "TargetIdentifierAtom", SolExecScalar<"instanceKey">>;
def : SolProjectField<"effectWithoutComputes.name", "TargetIdentifierAtom", SolIndexedProj<"values.computes", "name">>;
def : SolProjectField<"effectWithoutPostings.name", "TargetIdentifierAtom", SolPostingProj<"flat", "name", "posting-id">>;
def : SolProjectField<"effectWithoutPostings.direction", "PostingDirectionAtom", SolPostingProj<"flat", "direction", "direction">>;
def : SolProjectField<"effectWithoutExecution.item", "FinalizedTemporalExecution", SolEmptyProj>;
def : SolProjectField<"effectWithoutInitialRole.item", "FinalizedTemporalRole", SolEmptyProj>;
def : SolProjectField<"effectWithoutParams.name", "TargetIdentifierAtom", SolIndexedProj<"values.params", "name">>;
def : SolProjectField<"effectWithoutParams.type", "FinalizedTargetType", SolIndexedProj<"values.params", "type">>;
def : SolProjectField<"effectWithoutExecution.replayKey", "TargetIdentifierAtom", SolExecScalar<"replayKey">>;
def : SolProjectField<"effectWithoutComputes.expression", "FinalizedExpressionLeaf", SolIndexedExprProj<"values.computes", "expression">>;
def : SolProjectField<"effectWithoutPostings.ledger", "TypedStringLiteral", SolPostingProj<"flat", "ledger", "posting-id">>;
def : SolProjectField<"effectWithoutPostings.amount", "FinalizedTypedOperand", SolPostingProj<"flat", "amount", "uint-operand">>;
def : SolProjectField<"effectWithoutPostings.party", "FinalizedTypedOperand", SolPostingProj<"flat", "party", "string-operand">>;
def : SolProjectField<"effectWithoutPostings.currency", "FinalizedTypedOperand", SolPostingProj<"flat", "currency", "string-operand">>;
def : SolProjectField<"effectWithoutPostings.memo", "TypedStringLiteral", SolPostingProj<"flat", "memo", "memo">>;
def : SolProjectField<"effectWithoutPostingGuard.expression", "FinalizedExpressionLeaf", SolPostingGuardProj>;
def : SolProjectField<"effectWithoutSourceCanonicalizations.canonicalization", "TypedStringLiteral", SolIndexedProj<"attestation.policies", "canonicalization">>;
def : SolProjectField<"evidenceExecution.procedure", "TargetIdentifierAtom", SolExecScalar<"procedureNamespace">>;
def : SolProjectField<"evidenceInitialRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"initialLifecycleRole">>;
def : SolProjectField<"evidenceSuccessRole.status", "LifecycleStatusAtom", SolStatusAtomProj<"successLifecycleRole">>;
def : SolProjectField<"evidenceExecution.instanceKey", "TargetIdentifierAtom", SolExecScalar<"instanceKey">>;
def : SolProjectField<"evidenceParams.type", "FinalizedTargetType", SolIndexedProj<"values.params", "type">>;
def : SolProjectField<"evidenceParams.name", "TargetIdentifierAtom", SolConditionalOrdinalArg<"values.params", "name">>;
def : SolProjectField<"evidenceExecution.replayKey", "TargetIdentifierAtom", SolExecScalar<"replayKey">>;
def : SolProjectField<"evidenceSourceCanonicalizations.canonicalization", "TypedStringLiteral", SolIndexedProj<"attestation.policies", "canonicalization">>;

//===----------------------------------------------------------------------===//
// slotExtent() — one row per non-optional slot. Optional posting-presence slots
// resolve through the generated generic tail (SlotRow presence).
//===----------------------------------------------------------------------===//

def : SolSlotExtent<"execution", "const-one">;
def : SolSlotExtent<"initialRole", "const-one">;
def : SolSlotExtent<"successRole", "const-one">;
def : SolSlotExtent<"effectExecution", "const-one">;
def : SolSlotExtent<"effectInitialRole", "const-one">;
def : SolSlotExtent<"effectWithExecution", "const-one">;
def : SolSlotExtent<"effectWithInitialRole", "const-one">;
def : SolSlotExtent<"effectWithSuccessRole", "const-one">;
def : SolSlotExtent<"effectWithoutExecution", "const-one">;
def : SolSlotExtent<"effectWithoutInitialRole", "const-one">;
def : SolSlotExtent<"effectWithoutSuccessRole", "const-one">;
def : SolSlotExtent<"evidenceExecution", "const-one">;
def : SolSlotExtent<"evidenceInitialRole", "const-one">;
def : SolSlotExtent<"evidenceSuccessRole", "const-one">;
def : SolSlotExtent<"effectWithWithAttestation", "attest-single">;
def : SolSlotExtent<"effectWithoutWithAttestation", "attest-single">;
def : SolSlotExtent<"effectWithWithoutAttestation", "attest-none">;
def : SolSlotExtent<"effectWithoutWithoutAttestation", "attest-none">;
def : SolSlotExtent<"temporalPolicies", "vector-size", "temporalPolicies">;
def : SolSlotExtent<"params", "vector-size", "values.params">;
def : SolSlotExtent<"effectWithParams", "vector-size", "values.params">;
def : SolSlotExtent<"effectWithoutParams", "vector-size", "values.params">;
def : SolSlotExtent<"evidenceParams", "vector-size", "values.params">;
def : SolSlotExtent<"sourceCanonicalizations", "vector-size", "attestation.policies">;
def : SolSlotExtent<"effectWithSourceCanonicalizations", "vector-size", "attestation.policies">;
def : SolSlotExtent<"effectWithoutSourceCanonicalizations", "vector-size", "attestation.policies">;
def : SolSlotExtent<"evidenceSourceCanonicalizations", "vector-size", "attestation.policies">;
def : SolSlotExtent<"claimInputs", "vector-size", "claimInputs">;
def : SolSlotExtent<"computes", "vector-size", "values.computes">;
def : SolSlotExtent<"effectWithComputes", "vector-size", "values.computes">;
def : SolSlotExtent<"effectWithoutComputes", "vector-size", "values.computes">;
def : SolSlotExtent<"effectGroups", "vector-size", "effectGroups">;
def : SolSlotExtent<"postings", "vector-size", "postings">;
def : SolSlotExtent<"effectWithPostings", "vector-size", "postings">;
def : SolSlotExtent<"effectWithoutPostings", "vector-size", "postings">;
def : SolSlotExtent<"balanceAssertions", "vector-size", "balanceAssertions">;
def : SolSlotExtent<"effectWithBalanceAssertions", "vector-size", "balanceAssertions">;
def : SolSlotExtent<"effectWithoutBalanceAssertions", "vector-size", "balanceAssertions">;
def : SolSlotExtent<"groupPostings", "group-postings-size">;

//===----------------------------------------------------------------------===//
// slotItemOrder() — one row per repeated (ordered) slot. All other slots fall
// through to the closed error.
//===----------------------------------------------------------------------===//

def : SolSlotItemOrder<"temporalPolicies", "at-ordinal", "temporalPolicies">;
def : SolSlotItemOrder<"params", "at-ordinal", "values.params">;
def : SolSlotItemOrder<"effectWithParams", "at-ordinal", "values.params">;
def : SolSlotItemOrder<"effectWithoutParams", "at-ordinal", "values.params">;
def : SolSlotItemOrder<"evidenceParams", "at-ordinal", "values.params">;
def : SolSlotItemOrder<"claimInputs", "at-ordinal", "claimInputs">;
def : SolSlotItemOrder<"computes", "at-ordinal", "values.computes">;
def : SolSlotItemOrder<"effectWithComputes", "at-ordinal", "values.computes">;
def : SolSlotItemOrder<"effectWithoutComputes", "at-ordinal", "values.computes">;
def : SolSlotItemOrder<"effectGroups", "at-ordinal", "effectGroups">;
def : SolSlotItemOrder<"postings", "at-ordinal", "postings">;
def : SolSlotItemOrder<"effectWithPostings", "at-ordinal", "postings">;
def : SolSlotItemOrder<"effectWithoutPostings", "at-ordinal", "postings">;
def : SolSlotItemOrder<"sourceCanonicalizations", "identity">;
def : SolSlotItemOrder<"effectWithSourceCanonicalizations", "identity">;
def : SolSlotItemOrder<"effectWithoutSourceCanonicalizations", "identity">;
def : SolSlotItemOrder<"evidenceSourceCanonicalizations", "identity">;
def : SolSlotItemOrder<"balanceAssertions", "identity">;
def : SolSlotItemOrder<"effectWithBalanceAssertions", "identity">;
def : SolSlotItemOrder<"effectWithoutBalanceAssertions", "identity">;
def : SolSlotItemOrder<"groupPostings", "group-postings-ordinal">;
