//===- SolidityTargetNodes.td - typed Solidity target-model node metadata -===//
//
// The single source of truth for the Solidity typed-target-model statement kinds
// and their node metadata. It LABELS already-legalized node shapes — it does NOT
// read capability-spec fields, select workflow keys, or discover
// policy/balance/lifecycle semantics; that all stays in the
// CoordinationPlan->SolidityModel legalization boundary (the anti-inference
// boundary is authoritative).
//
// scripts/generators/gen_target_node_registry.py runs the pinned
// `llvm-tblgen --dump-json` over this file and emits the committed, deterministic
// X-macro registry SolidityTargetNodes.inc, which SolidityTargetAdapter.h expands into
// (a) the SolStmt::Kind enum and (b) a node-metadata table consumed by the
// completeness self-test + the check_target_node_registry.py reconciliation gate.
// It is a standalone .td (no MLIR/ODS include) — the metadata-registry pilot
// proves the generation seam without touching the closed L1 dialect.
//
//===----------------------------------------------------------------------===//

include "TargetPrinter.td"

def SolStmtModel : TargetPrinterModel<"solidity", "SolStmt", "SOL", 1>;

// One typed target-model statement kind. `Ordinal` fixes the enum's integer
// identity (kept identical to the pre-pilot hand-written enum, so the Solidity
// byte-goldens are unchanged). `PrinterHandler` labels the printer handler that
// lowers this kind; `IsLeaf` marks a terminal (non-nesting) shape;
// `RequiredFeature` is the target-model capability the shape realizes. The def
// NAME is the Kind symbol. `GeneratedHandler=1` means this path has retired its
// handwritten factory/dispatch/template and is emitted by the shared generated
// printer driver.
class SolNode<int ord, string handler, bit leaf, string feature,
              string layout = "", string syntax = "",
              list<PrinterField> fields = [], bit generated = 0,
              string closeSyntax = "", string listField = "",
              string listInner = "", string listOuter = "",
              list<EnumField> enumFields = []>
    : TargetPrinterNode<"solidity", "SolStmt", ord, handler, leaf, feature,
                        layout, syntax, fields, generated, closeSyntax, "SOL",
                        listField, listInner, listOuter, enumFields> {
  // Package-owned typed-builder ABI.  BuilderOrder must be an exact
  // permutation of the node's scalar fields, enum fields, optional repeated
  // field, and (for nesting nodes) `body`, unless BuilderBodyOptional records
  // that the builder creates the empty shell consumed by a separate container.
  // The pinned dump-json consumer validates that totality before emitting any
  // C++ declaration or mapping.
  string BuilderName = "";
  list<string> BuilderOrder = [];
  bit BuilderBodyOptional = 0;
  // Optional INERT trailing line-comment carrier (): when non-empty, the
  // builder takes one extra `std::string <CommentField>` argument that is stored
  // on the node's `comment` field — NOT an operand, NOT projected by the printer
  // template. It is structurally inert layout metadata: the generic renderer
  // aligns a block's commented children into a shared trailing `// …` column via
  // codetext's `commentedLine` (which owns the `// ` framing and rejects a
  // newline, so a comment can annotate but never re-author grammar). This is how
  // the storage-slot trailing comment rides the typed node tree instead of being
  // composed by a handwritten renderer.
  string CommentField = "";
}

// Backend-package recipe-builder schema. Recipe rows name one of these exact
// builders; the generator mechanically maps declared recipe fields to the
// ordered arguments below. Fixed Solidity spelling lives here, beside the
// target-node ABI, rather than in generator control flow.
class SolRecipeBuilderArg<string kind, string fieldName = "",
                          string literalValue = "", string prefixValue = "",
                          string suffixValue = "",
                          string transformValue = "identity",
                          list<string> fieldNames = [],
                          list<string> transformValues = []> {
  string Kind = kind; // value | literal | template | params/nodes/model lists
  string Field = fieldName;
  string Literal = literalValue;
  string Prefix = prefixValue;
  string Suffix = suffixValue;
  string Transform = transformValue;
  list<string> Fields = fieldNames;
  list<string> Transforms = transformValues;
}

class SolRecipeBuilder<string name, string resultKind, string factory,
                       list<SolRecipeBuilderArg> args,
                       list<string> sourceRequirements = []> {
  string Name = name;
  string ResultKind = resultKind;
  string Factory = factory;
  list<SolRecipeBuilderArg> Args = args;
  list<string> SourceRequirements = sourceRequirements;
}
class SolRecipeClosedTransform<string name, list<string> spellings> {
  string Name = name;
  list<string> Spellings = spellings;
}

def PostingDirectionVerbTransform : SolRecipeClosedTransform<
    "direction-verb", ["Debited", "Credited"]>;
def PostingDirectionOperatorTransform : SolRecipeClosedTransform<
    "direction-op", ["-=", "+="]>;
def PostingDirectionTotalTransform : SolRecipeClosedTransform<
    "direction-total", ["debitTotal", "creditTotal"]>;

class SolValueArg<string fieldName, string prefixValue = "",
                  string suffixValue = "", string transformValue = "identity">
    : SolRecipeBuilderArg<"value", fieldName, "", prefixValue, suffixValue,
                          transformValue>;
class SolLiteralArg<string value>
    : SolRecipeBuilderArg<"literal", "", value>;
class SolTemplateArg<string value, list<string> fields,
                     list<string> transforms>
    : SolRecipeBuilderArg<"template", "", value, "", "", "identity",
                          fields, transforms>;
class SolParamsArg<string fieldName>
    : SolRecipeBuilderArg<"params", fieldName>;
class SolNodesArg<string fieldName>
    : SolRecipeBuilderArg<"nodes", fieldName>;
class SolFragmentsArg<string fieldName, string separator = "">
    : SolRecipeBuilderArg<"fragments", fieldName, separator>;
class SolFragmentListArg<string fieldName>
    : SolRecipeBuilderArg<"fragment-list", fieldName>;

//  /  R5b: the conditional-ordinal projection sub-read arg kind. A
// STRUCTURAL/TYPED accessor: it spells `uref(<member>)` iff the projected item's
// finalized ordinal equals the already-finalized instance-key-param ordinal
// (`sequence.values.instanceKeyParam`, minted above the provider waist), else
// the empty string. It dispatches PURELY on that typed ordinal identity — no
// plan/spec/domain read, no name comparison, no branch on backend meaning — and
// is consumed only by the solidity-projection profile's generated dispatch
// resolver (the evidence-param name projection). `Field` = the member to uref,
// `Fields` = [the finalized item container].
class SolConditionalOrdinalArg<string container, string member>
    : SolRecipeBuilderArg<"conditional-ordinal", member, "", "", "", "identity",
                          [container]>;

def SourceCanonicalizationRecipeBuilder : SolRecipeBuilder<
    "source-canonicalization", "fragment", "",
    [SolValueArg<"canonicalization">]>;

// : the contract-body status enum `enum Status { <initial>, <success> }`.
// Composed directly in the contract-body recipe sequence (no longer authored by
// the retired hand-written contract completer). The two lifecycle atoms are
// bound straight from the initial/success roles.
def SolStatusEnumRecipeBuilder : SolRecipeBuilder<
    "sol-status-enum", "statement", "enumDecl",
    [SolLiteralArg<"Status">,
     SolTemplateArg<"{}, {}", ["initial", "success"],
                    ["identity", "identity"]>]>;

def TemporalPolicyParamRecipeBuilder : SolRecipeBuilder<
    "temporal-policy-param", "param", "",
    [SolLiteralArg<"address">, SolLiteralArg<"">,
     SolValueArg<"policy", "acceptanceGuard_", "_">]>;
def TemporalPolicyStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-policy-storage", "statement", "storageDecl",
    [SolLiteralArg<"IThresholdQuorumAcceptance">,
     SolLiteralArg<"public immutable">,
     SolValueArg<"policy", "acceptanceGuard_">, SolLiteralArg<"">]>;
def TemporalExecuteParamRecipeBuilder : SolRecipeBuilder<
    "temporal-execute-param", "param", "",
    [SolValueArg<"type">, SolLiteralArg<"">,
     SolValueArg<"name", "", "", "ref">]>;
def TemporalStringKeyParamRecipeBuilder : SolRecipeBuilder<
    "temporal-string-key-param", "param", "",
    [SolLiteralArg<"string">, SolLiteralArg<"">,
     SolValueArg<"name">]>;
def TemporalUintValueParamRecipeBuilder : SolRecipeBuilder<
    "temporal-uint-value-param", "param", "",
    [SolLiteralArg<"uint256">, SolLiteralArg<"">, SolLiteralArg<"value">]>;
def TemporalPostingPartyParamRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-party-param", "param", "",
    [SolLiteralArg<"string">, SolLiteralArg<"">, SolLiteralArg<"party">]>;
def TemporalPostingAmountParamRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-amount-param", "param", "",
    [SolLiteralArg<"uint256">, SolLiteralArg<"">, SolLiteralArg<"amount">]>;
def TemporalPostingCurrencyParamRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-currency-param", "param", "",
    [SolLiteralArg<"string">, SolLiteralArg<"">, SolLiteralArg<"currency">]>;
def TemporalPostingMemoParamRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-memo-param", "param", "",
    [SolLiteralArg<"string">, SolLiteralArg<"">, SolLiteralArg<"memo">]>;
def TemporalTriggerEventRecipeBuilder : SolRecipeBuilder<
    "temporal-trigger-event", "statement", "eventDecl",
    [SolValueArg<"name", "", "", "pascal">, SolParamsArg<"params">]>;
def TemporalComputedEventRecipeBuilder : SolRecipeBuilder<
    "temporal-computed-event", "statement", "eventDecl",
    [SolValueArg<"name", "", "Computed", "pascal">,
     SolParamsArg<"params">]>;
def TemporalPostingEventRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-event", "statement", "eventDecl",
    [SolTemplateArg<"{}{}", ["name", "direction"],
                    ["pascal", "direction-verb"]>,
     SolParamsArg<"params">]>;
def TemporalReconciledEventRecipeBuilder : SolRecipeBuilder<
    "temporal-reconciled-event", "statement", "eventDecl",
    [SolValueArg<"name", "", "Reconciled", "pascal">,
     SolParamsArg<"params">]>;
def TemporalStatusStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-status-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => Status)">, SolLiteralArg<"public">,
     SolLiteralArg<"statusOf">, SolLiteralArg<"">]>;
def TemporalClaimStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => bytes32)">, SolLiteralArg<"public">,
     SolLiteralArg<"keyClaim">,
     SolLiteralArg<"key -> bound execution claim ()">]>;
def TemporalGroupStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-group-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => mapping(uint256 => bool))">,
     SolLiteralArg<"public">, SolLiteralArg<"committedGroup">,
     SolLiteralArg<"key -> group ordinal -> committed ()">]>;
def TemporalNetStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-net-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => mapping(string => int256))">,
     SolLiteralArg<"public">, SolLiteralArg<"net">,
     SolLiteralArg<"key -> ledger -> net">]>;
def TemporalDebitStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-debit-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => uint256)">, SolLiteralArg<"public">,
     SolLiteralArg<"debitTotal">, SolLiteralArg<"key -> total debited">]>;
def TemporalCreditStorageRecipeBuilder : SolRecipeBuilder<
    "temporal-credit-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => uint256)">, SolLiteralArg<"public">,
     SolLiteralArg<"creditTotal">, SolLiteralArg<"key -> total credited">]>;
def TemporalGuardRequireRecipeBuilder : SolRecipeBuilder<
    "temporal-guard-require", "statement", "require",
    [SolValueArg<"policy", "acceptanceGuard_", "_ != address(0)">,
     SolLiteralArg<"guard required">]>;
def TemporalGuardAssignRecipeBuilder : SolRecipeBuilder<
    "temporal-guard-assign", "statement", "assign",
    [SolValueArg<"policy", "acceptanceGuard_">,
     SolValueArg<"policy", "IThresholdQuorumAcceptance(acceptanceGuard_", "_)">]>;
def TemporalConstructorRecipeBuilder : SolRecipeBuilder<
    "temporal-constructor", "constructor", "functionSig",
    [SolParamsArg<"params">, SolNodesArg<"body">]>;
def TemporalSpdxRecipeBuilder : SolRecipeBuilder<
    "temporal-spdx", "statement", "spdxLicense",
    [SolLiteralArg<"MIT">]>;
def TemporalPragmaRecipeBuilder : SolRecipeBuilder<
    "temporal-pragma", "statement", "pragma",
    [SolLiteralArg<"^0.8.20">]>;
def TemporalBlankRecipeBuilder : SolRecipeBuilder<
    "temporal-blank", "statement", "blank", []>;
def TemporalEnvelopeImportRecipeBuilder : SolRecipeBuilder<
    "temporal-envelope-import", "statement", "importUnit",
    [SolLiteralArg<"./CoordinationEnvelope.sol">]>;
def TemporalContractRecipeBuilder : SolRecipeBuilder<
    "temporal-contract", "temporal-contract", "",
    [SolValueArg<"name", "", "", "pascal">,
     SolNodesArg<"header">, SolNodesArg<"body">,
     SolFragmentListArg<"sourceCanonicalizations">],
    ["ThresholdQuorumAcceptance", "CoordinationEnvelope"]>;
def TemporalReplayKeyRecipeBuilder : SolRecipeBuilder<
    "temporal-replay-key", "statement", "localDecl",
    [SolLiteralArg<"bytes32">, SolLiteralArg<"_k">,
     SolTemplateArg<"keccak256(bytes({}))", ["key"], ["ref"]>]>;
def TemporalReplayRequireRecipeBuilder : SolRecipeBuilder<
    "temporal-replay-require", "statement", "require",
    [SolTemplateArg<"statusOf[_k] != Status.{}", ["status"], ["identity"]>,
     SolLiteralArg<"replay">]>;
def TemporalClaimNamesRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-names", "statement", "localDecl",
    [SolLiteralArg<"string[] memory">, SolLiteralArg<"_n">,
     SolTemplateArg<"new string[]({})", ["count"], ["identity"]>]>;
def TemporalClaimCategoriesRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-categories", "statement", "localDecl",
    [SolLiteralArg<"string[] memory">, SolLiteralArg<"_c">,
     SolTemplateArg<"new string[]({})", ["count"], ["identity"]>]>;
def TemporalClaimValuesRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-values", "statement", "localDecl",
    [SolLiteralArg<"string[] memory">, SolLiteralArg<"_v">,
     SolTemplateArg<"new string[]({})", ["count"], ["identity"]>]>;
def TemporalClaimNameAssignRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-name-assign", "statement", "assign",
    [SolTemplateArg<"_n[{}]", ["ordinal"], ["identity"]>,
     SolValueArg<"name">]>;
def TemporalClaimCategoryAssignRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-category-assign", "statement", "assign",
    [SolTemplateArg<"_c[{}]", ["ordinal"], ["identity"]>,
     SolValueArg<"category">]>;
def TemporalClaimValueAssignRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-value-assign", "statement", "assign",
    [SolTemplateArg<"_v[{}]", ["ordinal"], ["identity"]>,
     SolValueArg<"value">]>;
def TemporalClaimRecipeBuilder : SolRecipeBuilder<
    "temporal-claim", "statement", "localDecl",
    [SolLiteralArg<"bytes32">, SolLiteralArg<"_claim">,
     SolTemplateArg<"CoordinationEnvelope.claim({}, {}, _n, _c, _v)",
                    ["identity", "key"], ["identity", "ref"]>]>;
def TemporalClaimRequireRecipeBuilder : SolRecipeBuilder<
    "temporal-claim-require", "statement", "require",
    [SolLiteralArg<"keyClaim[_k] == bytes32(0) || keyClaim[_k] == _claim">,
     SolLiteralArg<"claim mismatch">]>;
def TemporalTriggerEmitRecipeBuilder : SolRecipeBuilder<
    "temporal-trigger-emit", "statement", "emit",
    [SolValueArg<"event", "", "", "pascal">,
     SolValueArg<"key", "", "", "ref">]>;
def TemporalComputeDeclRecipeBuilder : SolRecipeBuilder<
    "temporal-compute-decl", "statement", "localDecl",
    [SolLiteralArg<"uint256">, SolValueArg<"name", "", "", "ref">,
     SolValueArg<"expression">]>;
def TemporalComputeEmitRecipeBuilder : SolRecipeBuilder<
    "temporal-compute-emit", "statement", "emit",
    [SolValueArg<"name", "", "Computed", "pascal">,
     SolValueArg<"name", "", "", "ref">]>;
def TemporalProgressRecipeBuilder : SolRecipeBuilder<
    "temporal-progress", "statement", "localDecl",
    [SolLiteralArg<"bool">, SolLiteralArg<"_progress">,
     SolLiteralArg<"false">]>;
def TemporalNetUpdateRecipeBuilder : SolRecipeBuilder<
    "temporal-net-update", "statement", "compoundAssign",
    [SolTemplateArg<"net[_k][{}]", ["ledger"], ["identity"]>,
     SolValueArg<"direction", "", "", "direction-op">,
     SolValueArg<"amount", "int256(", ")">]>;
def TemporalTotalUpdateRecipeBuilder : SolRecipeBuilder<
    "temporal-total-update", "statement", "compoundAssign",
    [SolValueArg<"direction", "", "[_k]", "direction-total">,
     SolLiteralArg<"+=">,
     SolValueArg<"amount">]>;
def TemporalPostingEmitRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-emit", "statement", "emit",
    [SolTemplateArg<"{}{}", ["name", "direction"],
                    ["pascal", "direction-verb"]>,
     SolFragmentsArg<"args">]>;
def TemporalMemoArgRecipeBuilder : SolRecipeBuilder<
    "temporal-memo-arg", "fragment", "",
    [SolValueArg<"memo">]>;
def TemporalPostingArgsRecipeBuilder : SolRecipeBuilder<
    "temporal-posting-args", "fragment", ", ",
    [SolValueArg<"party">, SolValueArg<"amount">,
     SolValueArg<"currency">, SolFragmentsArg<"memo">]>;
def TemporalGroupFlagRecipeBuilder : SolRecipeBuilder<
    "temporal-group-flag", "statement", "assign",
    [SolTemplateArg<"committedGroup[_k][{}]", ["ordinal"], ["identity"]>,
     SolLiteralArg<"true">]>;
def TemporalProgressAssignRecipeBuilder : SolRecipeBuilder<
    "temporal-progress-assign", "statement", "assign",
    [SolLiteralArg<"_progress">, SolLiteralArg<"true">]>;
def TemporalGroupGuardRecipeBuilder : SolRecipeBuilder<
    "temporal-group-guard", "statement", "guarded",
    [SolTemplateArg<
        "(acceptanceGuard_{}.acceptedExecutionClaim(_k) == _claim) && !committedGroup[_k][{}]",
        ["policy", "ordinal"], ["identity", "identity"]>,
     SolNodesArg<"body">]>;
def TemporalPinClaimRecipeBuilder : SolRecipeBuilder<
    "temporal-pin-claim", "statement", "guarded",
    [SolLiteralArg<"_progress && keyClaim[_k] == bytes32(0)">,
     SolNodesArg<"body">]>;
def TemporalPinClaimAssignRecipeBuilder : SolRecipeBuilder<
    "temporal-pin-claim-assign", "statement", "assign",
    [SolLiteralArg<"keyClaim[_k]">, SolLiteralArg<"_claim">]>;
def TemporalDoneTermRecipeBuilder : SolRecipeBuilder<
    "temporal-done-term", "fragment", "",
    [SolTemplateArg<"committedGroup[_k][{}]", ["ordinal"], ["identity"]>]>;
def TemporalDoneRecipeBuilder : SolRecipeBuilder<
    "temporal-done", "statement-fragments", "localDecl",
    [SolLiteralArg<"bool">, SolLiteralArg<"_done">,
     SolFragmentsArg<"terms", " && ">]>;
def TemporalBalanceRecipeBuilder : SolRecipeBuilder<
    "temporal-balance", "statement", "require",
    [SolLiteralArg<"debitTotal[_k] == creditTotal[_k]">,
     SolLiteralArg<"not balanced">]>;
def TemporalTransitionRecipeBuilder : SolRecipeBuilder<
    "temporal-transition", "statement", "transition",
    [SolValueArg<"status">, SolLiteralArg<"statusOf[_k]">]>;
def TemporalReconciledEmitRecipeBuilder : SolRecipeBuilder<
    "temporal-reconciled-emit", "statement", "emit",
    [SolValueArg<"name", "", "Reconciled", "pascal">,
     SolValueArg<"key", "", "", "ref">]>;
def TemporalTerminalRecipeBuilder : SolRecipeBuilder<
    "temporal-terminal", "statement", "guarded",
    [SolLiteralArg<"_done">, SolNodesArg<"body">]>;
def TemporalExecuteRecipeBuilder : SolRecipeBuilder<
    "temporal-execute", "function", "",
    [SolLiteralArg<"execute">, SolParamsArg<"params">,
     SolNodesArg<"body">]>;
def EffectfulGuardParamRecipeBuilder : SolRecipeBuilder<
    "effectful-guard-param", "param", "",
    [SolLiteralArg<"address">, SolLiteralArg<"">,
     SolLiteralArg<"acceptanceGuard_">]>;
def EffectfulGuardRequireRecipeBuilder : SolRecipeBuilder<
    "effectful-guard-require", "statement", "require",
    [SolLiteralArg<"acceptanceGuard_ != address(0)">,
     SolLiteralArg<"guard required">]>;
def EffectfulGuardAssignRecipeBuilder : SolRecipeBuilder<
    "effectful-guard-assign", "statement", "assign",
    [SolLiteralArg<"acceptanceGuard">,
     SolLiteralArg<"IThresholdQuorumAcceptance(acceptanceGuard_)">]>;
def EffectfulKeyParamRecipeBuilder : SolRecipeBuilder<
    "effectful-key-param", "param", "",
    [SolLiteralArg<"string">, SolLiteralArg<"calldata">,
     SolValueArg<"name", "", "", "ref">]>;
def EffectfulReplayRequireRecipeBuilder : SolRecipeBuilder<
    "effectful-replay-require", "statement", "require",
    [SolTemplateArg<"statusOf[_k] == Status.{}", ["status"], ["identity"]>,
     SolLiteralArg<"bad transition">]>;
def EffectfulAttestedAssignRecipeBuilder : SolRecipeBuilder<
    "effectful-attested-assign", "statement", "assign",
    [SolLiteralArg<"attested[_k]">, SolLiteralArg<"true">]>;
def EffectfulAttestRecipeBuilder : SolRecipeBuilder<
    "effectful-attest", "function", "",
    [SolLiteralArg<"attest">, SolParamsArg<"params">,
     SolNodesArg<"body">]>;
def EffectfulAttestationCommentRecipeBuilder : SolRecipeBuilder<
    "effectful-attestation-comment", "statement", "docComment",
    [SolLiteralArg<"It records coordination checkpoints (status, attestations, net positions)">]>;
def EffectfulIsolationCommentRecipeBuilder : SolRecipeBuilder<
    "effectful-isolation-comment", "statement", "docComment",
    [SolLiteralArg<"so distinct workflow instances never share status, totals, or net positions.">]>;
def EffectfulAttestedStorageRecipeBuilder : SolRecipeBuilder<
    "effectful-attested-storage", "statement", "storageDecl",
    [SolLiteralArg<"mapping(bytes32 => bool)">, SolLiteralArg<"public">,
     SolLiteralArg<"attested">, SolLiteralArg<"">]>;
def EffectfulGuardStorageRecipeBuilder : SolRecipeBuilder<
    "effectful-guard-storage", "statement", "storageDecl",
    [SolLiteralArg<"IThresholdQuorumAcceptance">,
     SolLiteralArg<"public immutable">, SolLiteralArg<"acceptanceGuard">,
     SolLiteralArg<"">]>;
def EffectfulExecuteReplayRequireRecipeBuilder : SolRecipeBuilder<
    "effectful-execute-replay-require", "statement", "require",
    [SolTemplateArg<"statusOf[_k] == Status.{}", ["status"], ["identity"]>,
     SolLiteralArg<"replay">]>;
def EffectfulSelfAcceptanceRecipeBuilder : SolRecipeBuilder<
    "effectful-self-acceptance", "statement", "require",
    [SolLiteralArg<"attested[_k]">,
     SolLiteralArg<"missing attestation">]>;
def EffectfulGuardAcceptanceRecipeBuilder : SolRecipeBuilder<
    "effectful-guard-acceptance", "statement", "require",
    [SolLiteralArg<"acceptanceGuard.isAccepted(_k)">,
     SolLiteralArg<"quorum not accepted">]>;
def EffectfulPostingGuardRecipeBuilder : SolRecipeBuilder<
    "effectful-posting-guard", "statement", "guarded",
    [SolValueArg<"condition">, SolNodesArg<"body">]>;
def EffectfulUngatedContractRecipeBuilder : SolRecipeBuilder<
    "effectful-contract-ungated", "effectful-contract", "false",
    [SolValueArg<"name", "", "", "pascal">,
     SolNodesArg<"header">, SolNodesArg<"body">,
     SolFragmentListArg<"sourceCanonicalizations">]>;
def EffectfulGatedContractRecipeBuilder : SolRecipeBuilder<
    "effectful-contract-gated", "effectful-contract", "true",
    [SolValueArg<"name", "", "", "pascal">,
     SolNodesArg<"header">, SolNodesArg<"body">,
     SolFragmentListArg<"sourceCanonicalizations">],
    ["ThresholdQuorumAcceptance"]>;

//  evidence-rail builders. The `Accepted` event/emit suffix, the ordered
// accept-parameter list (the projected type token + the provider-decided name —
// `u_`-spelled for the  instance-key parameter, empty otherwise), the accept
// callable, and the evidenceOnly contract assembly. Every other evidence node
// reuses a temporal/effectful builder above.
def EvidenceAcceptedEventRecipeBuilder : SolRecipeBuilder<
    "evidence-accepted-event", "statement", "eventDecl",
    [SolValueArg<"name", "", "Accepted", "pascal">, SolParamsArg<"params">]>;
def EvidenceParamRecipeBuilder : SolRecipeBuilder<
    "evidence-param", "param", "",
    [SolValueArg<"type">, SolLiteralArg<"">, SolValueArg<"name">]>;
def EvidenceAcceptEmitRecipeBuilder : SolRecipeBuilder<
    "evidence-accept-emit", "statement", "emit",
    [SolValueArg<"name", "", "Accepted", "pascal">,
     SolValueArg<"key", "", "", "ref">]>;
def EvidenceAcceptRecipeBuilder : SolRecipeBuilder<
    "evidence-accept", "function", "",
    [SolLiteralArg<"accept">, SolParamsArg<"params">, SolNodesArg<"body">]>;
def EvidenceContractRecipeBuilder : SolRecipeBuilder<
    "evidence-contract", "evidence-contract", "true",
    [SolValueArg<"name", "", "", "pascal">,
     SolNodesArg<"header">, SolNodesArg<"body">,
     SolFragmentListArg<"sourceCanonicalizations">],
    ["ThresholdQuorumAcceptance"]>;

// Fields project the model operand at the given ordinal (arity-generic).
def FCondition : PrinterField<"condition", 0>;
def FMessage   : PrinterField<"message",   1>;
def FState     : PrinterField<"state",     0>;
def FSlot      : PrinterField<"slot",      1>;
def FEvent     : PrinterField<"event",     0>;
def FArgs      : PrinterField<"args",      1>;
def FText      : PrinterField<"text",      0>;
def FClose     : PrinterField<"close",     1>;
def FType      : PrinterField<"type",      0>;
def FName      : PrinterField<"name",      1>;
def FRhs       : PrinterField<"rhs",       2>;
def FLhs       : PrinterField<"lhs",       0>;
def FAsgnRhs   : PrinterField<"rhs",       1>;
def FOp        : PrinterField<"op",        1>;
def FCmpRhs    : PrinterField<"rhs",       2>;
def FDocText   : PrinterField<"text",      0>;
def FLicense   : PrinterField<"license",   0>;
def FVersion   : PrinterField<"version",   0>;
def FPath      : PrinterField<"path",      0>;
def FEnumName  : PrinterField<"name",      0>;
def FModifiers : PrinterField<"modifiers", 1>;
def FStgName   : PrinterField<"name",      2>;
def FVariants  : PrinterField<"variants",  1>;
// : the callable-signature scalar field. `name` is the sole scalar operand
// (empty for a constructor) — an OPTIONAL-scalar whose leading space is emitted
// only when present (Prefix " "). The `keyword` and `modifiers` are ENUM fields
// (below), not free operands.
def FFnName : PrinterField<"name", 0, " ">;

//  slice 2: the contract-container name — the sole scalar operand of the
// ContractShell block (`contract ${name} {` … `}`).
def FContractName : PrinterField<"name", 0>;

//  slice 3: the interface method-signature scalar fields — the method name
// and its (single) return type in
// `function ${name}(${params}) external view returns (${returns});`. The
// parameters are the  §7 repeated-field projection; the `external view`
// framing is a fixed ABI shape (all IThresholdQuorumAcceptance methods are
// external view), not decided data.
def FISigName : PrinterField<"name", 0>;
def FISigReturns : PrinterField<"returns", 1>;

// : the CLOSED callable-kind + function-modifier enums. These are the SINGLE
// declarative source for BOTH the C++ CallableKind / CallableModifier enums (the
// generator emits `enum class … { <Symbols> = <ordinal>, …, Count }` from the
// Symbols list) AND the ordinal -> target spelling table — so the enum member set
// and the spellings cannot drift. Symbols and spellings are 1:1 and ordinal =
// position; the modifier order is visibility (external/public/internal/private)
// then mutability (view/pure/payable), matching the model's canonical order.
def CallableKindSpelling
    : EnumSpelling<"CallableKind", ["Function", "Constructor"],
                   ["function", "constructor"]>;
def CallableModifierSpelling
    : EnumSpelling<"CallableModifier",
                   ["External", "Public", "Internal", "Private", "View", "Pure",
                    "Payable"],
                   ["external", "public", "internal", "private", "view", "pure",
                    "payable"]>;

// The callable-kind scalar enum (`${keyword}` -> "function"/"constructor") and
// the compositional modifier list (`${modifiers}` -> the canonical, space-joined
// visibility/mutability spellings, with a leading space only when non-empty).
def FnKeywordEnum : EnumField<"keyword", CallableKindSpelling, /*repeated=*/0>;
def FnModifiersEnum : EnumField<"modifiers", CallableModifierSpelling,
                                /*repeated=*/1, /*inner=*/" ", /*prefix=*/" ">;

//  G1-S1: the Solidity status-machine spelling IDIOM, keyed by the projected
// (ExecutionMode, LifecycleRole). The 2-state lifecycle quotient's `Initial` role
// spells "None" in every mode; the `Success` role spells "Accepted" on the
// evidence-only rail and "Reconciled" on the coordination rails. Atoms only: the
// legalizer builds `Status.` + atom / `statusOf[_k] = Status.` + atom around
// them, and consumes the projected (mode, role) from the verified projection —
// the table maps that pair to an atom, never selecting a role. (Solidity does
// not spell the `AcceptedOrAttested` checkpoint, so it has no row for it.)
def : LifecycleAtom<"Evidence", "Initial", "None">;
def : LifecycleAtom<"Evidence", "Success", "Accepted">;
def : LifecycleAtom<"Effectful", "Initial", "None">;
def : LifecycleAtom<"Effectful", "Success", "Reconciled">;
def : LifecycleAtom<"Temporal", "Initial", "None">;
def : LifecycleAtom<"Temporal", "Success", "Reconciled">;

def Line       : SolNode<0, "line",       /*leaf=*/1, "framing", "line",
                         "${text}", [FText], /*generated=*/1>;
def Blank      : SolNode<1, "blank",      /*leaf=*/1, "framing", "blank",
                         "", [], /*generated=*/1> {
  let BuilderName = "blank";
}
def Require    : SolNode<2, "require",    /*leaf=*/1, "revert", "line",
                         "require(${condition}, \"${message}\");",
                         [FCondition, FMessage], /*generated=*/1> {
  let BuilderName = "require";
  let BuilderOrder = ["condition", "message"];
}
def Guarded    : SolNode<3, "guarded",    /*leaf=*/0, "condition", "block",
                         "if (${condition}) {", [FCondition], /*generated=*/1,
                         /*closeSyntax=*/"}"> {
  let BuilderName = "guarded";
  let BuilderOrder = ["condition", "body"];
}
def Transition : SolNode<4, "transition", /*leaf=*/1, "state-transition", "line",
                         "${slot} = Status.${state};",
                         [FSlot, FState], /*generated=*/1> {
  let BuilderName = "transition";
  let BuilderOrder = ["state", "slot"];
}
def Emit       : SolNode<5, "emit",       /*leaf=*/1, "event", "line",
                         "emit ${event}(${args});",
                         [FEvent, FArgs], /*generated=*/1> {
  let BuilderName = "emit";
  let BuilderOrder = ["event", "args"];
}
def Block      : SolNode<6, "block",      /*leaf=*/0, "framing", "block",
                         "${text}", [FText, FClose], /*generated=*/1,
                         /*closeSyntax=*/"${close}">;
//  slice 2a: the local-declaration statement grammar `<type> <name> = <init>;`
// is owned here (ordering + punctuation); legalization supplies the typed values.
def LocalDecl  : SolNode<7, "local-decl",  /*leaf=*/1, "declaration", "line",
                         "${type} ${name} = ${rhs};",
                         [FType, FName, FRhs], /*generated=*/1> {
  let BuilderName = "localDecl";
  let BuilderOrder = ["type", "name", "rhs"];
}
//  slice 2b: the plain/indexed assignment statement shell `<lhs> = <rhs>;`
// (the `=`/`;` framing is owned here; both operands are already-lowered target
// text). Compound `+=`/`-=` updates stay a raw seam for the following slice.
def Assign     : SolNode<8, "assign",      /*leaf=*/1, "assignment", "line",
                         "${lhs} = ${rhs};",
                         [FLhs, FAsgnRhs], /*generated=*/1> {
  let BuilderName = "assign";
  let BuilderOrder = ["lhs", "rhs"];
}
//  slice 2c: the compound-update statement shell `<lhs> <op> <rhs>;`. The
// spacing + `;` framing is owned here; `op` is a CLOSED `{+=, -=}` operator
// vocabulary the factory validates (not free grammar), so one node covers both
// the credit (`+=`) and debit (`-=`) ledger updates. lhs/rhs are already-lowered
// target text.
def CompoundAssign : SolNode<9, "compound-assign", /*leaf=*/1, "assignment",
                             "line", "${lhs} ${op} ${rhs};",
                             [FLhs, FOp, FCmpRhs], /*generated=*/1> {
  let BuilderName = "compoundAssign";
  let BuilderOrder = ["lhs", "op", "rhs"];
}
//  slice 1 (T2-S1): the NatSpec doc-comment source-unit record `/// <text>`.
// The `///` marker + single space is owned here (literal target syntax, so this
// is NOT a bare pass-through); `text` is the already-decided comment content, a
// single line (the factory rejects an embedded newline). Line comments (`//`),
// pragma, and imports follow as their own slices.
def DocComment : SolNode<10, "doc-comment", /*leaf=*/1, "comment", "line",
                         "/// ${text}", [FDocText], /*generated=*/1> {
  let BuilderName = "docComment";
  let BuilderOrder = ["text"];
}
//  slice 2: the SPDX license source-unit record. The whole
// `// SPDX-License-Identifier: ` directive prefix is LITERAL here (owns the SPDX
// comment syntax — not a bare pass-through); `license` is the already-decided
// SPDX identifier/expression the factory validates (single line, non-empty).
def SpdxLicense : SolNode<11, "spdx-license", /*leaf=*/1, "comment", "line",
                          "// SPDX-License-Identifier: ${license}",
                          [FLicense], /*generated=*/1> {
  let BuilderName = "spdxLicense";
  let BuilderOrder = ["license"];
}
//  slice 3: the version-pragma source-unit record `pragma solidity
// <version>;`. The whole `pragma solidity ` directive prefix and the trailing
// `;` are LITERAL here (this owns the pragma statement syntax — not a bare
// pass-through); `version` is the already-decided version constraint (e.g.
// `^0.8.20`) the factory validates (non-empty, no statement separator). Imports
// follow as their own slice.
def Pragma     : SolNode<12, "pragma",       /*leaf=*/1, "pragma", "line",
                         "pragma solidity ${version};",
                         [FVersion], /*generated=*/1> {
  let BuilderName = "pragma";
  let BuilderOrder = ["version"];
}
//  slice 4: the import-directive source-unit record `import "<path>";`. The
// `import "` prefix (with its opening quote) and the closing `";` are LITERAL
// here (this owns the import statement syntax — not a bare pass-through); `path`
// is the already-decided import path the factory validates (non-empty, no double
// quote — the `"` framing is owned — and no statement separator).
def Import     : SolNode<13, "import",       /*leaf=*/1, "import", "line",
                         "import \"${path}\";",
                         [FPath], /*generated=*/1> {
  let BuilderName = "importUnit";
  let BuilderOrder = ["path"];
}
//  T2-S2: the status-enum type declaration `enum <name> { <variants> }`. The
// whole `enum … { … }` construct framing is LITERAL here (this owns the enum
// declaration syntax); `name` and `variants` are already-decided operands — the
// variant list is comma-joined during legalization (a formatting of the decided
// SolEnum, not a decision). The factory rejects the framing punctuation
// (`{`/`}`/`;`/newline) in either operand.
def EnumDecl   : SolNode<14, "enum-decl",    /*leaf=*/1, "enum", "line",
                         "enum ${name} { ${variants} }",
                         [FEnumName, FVariants], /*generated=*/1> {
  let BuilderName = "enumDecl";
  let BuilderOrder = ["name", "variants"];
}
// : the storage-slot / state-variable declaration `<type> <modifiers>
// <name>;` (a mapping leaf or immutable). The whole `<type> <modifiers> <name>;`
// framing is owned here; `type`, `modifiers`, `name` are already-decided
// operands the factory validates (no framing punctuation `;`/newline). The
// OPTIONAL trailing `// …` comment is NOT part of this node — its column
// alignment stays a generic printer concern (padded to max-decl-width).
def StorageDecl : SolNode<15, "storage-decl", /*leaf=*/1, "storage",
                          "commented-line",
                          "${type} ${modifiers} ${name};",
                          [FType, FModifiers, FStgName], /*generated=*/1> {
  let BuilderName = "storageDecl";
  let BuilderOrder = ["type", "modifiers", "name", "comment"];
  let CommentField = "comment";
}
//  §7: the event declaration `event ${name}(${params});`. The whole
// `event (...) ;` framing is owned here; `${name}` is a scalar operand and
// `${params}` is a REPEATED-field (list) projection — each parameter item is the
// space-join of its non-empty `[type, location, name]` values (so an absent data
// location leaves no double space), and the items are joined by `, `. Both the
// per-parameter shape and the separator are TableGen-owned; legalization decides
// the type/location/name values. This is the reusable repeated-field facility
// for the parameter list (shared with the function signature, item 12).
def EventDecl  : SolNode<16, "event-decl",   /*leaf=*/1, "event", "line",
                         "event ${name}(${params});",
                         [FEnumName], /*generated=*/1, /*closeSyntax=*/"",
                         /*listField=*/"params", /*listInner=*/" ",
                         /*listOuter=*/", "> {
  let BuilderName = "eventDecl";
  let BuilderOrder = ["name", "params"];
}
// : the callable signature + brace container `${keyword}${name}(${params})
// ${modifiers} {` … `}`. A BLOCK node: its children (the function body
// statements) nest between the generated braces. The callable GRAMMAR is a
// CLOSED TYPED model: `${keyword}` is a scalar ENUM (CallableKind) and
// `${modifiers}` a REPEATED ENUM (canonical CallableModifier list) — the
// vocabulary + spelling live HERE, the model carries only ordinals. `${name}` is
// the sole scalar operand (optional-scalar); `${params}` reuses the  §7
// repeated-field projection. Legalization supplies the decided enum values. This
// retires SolFunction::signature AND the last SolParam::render consumer.
def FunctionSig : SolNode<17, "function-sig", /*leaf=*/0, "callable", "block",
                          "${keyword}${name}(${params})${modifiers} {",
                          [FFnName], /*generated=*/1,
                          /*closeSyntax=*/"}", /*listField=*/"params",
                          /*listInner=*/" ", /*listOuter=*/", ",
                          /*enumFields=*/[FnKeywordEnum, FnModifiersEnum]> {
  let BuilderName = "functionSig";
  let BuilderOrder = ["keyword", "name", "modifiers", "params", "body"];
}

//  slice 2: the contract CONTAINER `contract ${name} { … }`. A BLOCK node
// whose children — the contract body (type declarations, events, storage slots,
// functions) — nest between the generated braces. `${name}` is the sole scalar
// operand (the contract name). This retires the handwritten per-construct
// projection renderer's `contract <name> {` template.
def ContractShell : SolNode<18, "contract-shell", /*leaf=*/0, "container",
                            "block", "contract ${name} {", [FContractName],
                            /*generated=*/1, /*closeSyntax=*/"}"> {
  let BuilderName = "contractShell";
  // : the shell now CARRIES its full ordered body (type decls, events,
  // storage slots, functions, and the inert blank separators between sections)
  // as typed SolStmt children — so the whole contract renders through the
  // generic recursive renderNode, retiring the handwritten section renderer.
  let BuilderOrder = ["name", "body"];
}

//  slice 3a: the coordination contract's quorum-guard interface METHOD
// SIGNATURES. Each is a leaf `function ${name}(${params}) external view returns
// (${returns});` (parameters projected by the  §7 repeated field; the
// `external view` framing a fixed ABI shape). This is the consumer ABI the
// coordination binds to — NOT the security-reviewed M-of-N guard body, which
// stays the byte-golden-pinned ThresholdQuorumAcceptance.sol.inc. Typing the
// signatures retires the two rawLine seam sites ( 3 -> 1); the still-raw
// `interface … {` shell migrates in the follow-up slice.
def InterfaceSignature : SolNode<19, "interface-signature", /*leaf=*/1,
                                 "container", "line",
                                 "function ${name}(${params}) external view returns (${returns});",
                                 [FISigName, FISigReturns], /*generated=*/1,
                                 /*closeSyntax=*/"", /*listField=*/"params",
                                 /*listInner=*/" ", /*listOuter=*/", "> {
  let BuilderName = "interfaceSignature";
  let BuilderOrder = ["name", "params", "returns"];
}

//  slice 3b: the quorum-guard interface SHELL `interface ${name} { … }`. A
// BLOCK node whose children are the (already-typed,  slice 3a)
// InterfaceSignature methods. `${name}` is the sole scalar operand. Migrating the
// shell retires the LAST executable rawLine/rawBlock seam site —  reaches 0.
def InterfaceShell : SolNode<20, "interface-shell", /*leaf=*/0, "container",
                             "block", "interface ${name} {", [FContractName],
                             /*generated=*/1, /*closeSyntax=*/"}"> {
  let BuilderName = "interfaceShell";
  let BuilderOrder = ["name", "body"];
}
