//===- BackendProjection.h - shared domain-blind backend projection graph -===//
//
// The  backend projection model, realized in C++ (, Tier-3 slice 1).
//
// This is a SEPARATE below-waist boundary from the capability-spec waist: a
// deterministic, domain-blind projection of the verified `CoordinationPlan`
// into a closed, versioned graph of already-decided obligation nodes. Both
// backend legalizers consume the SAME graph; they differ only by idiom tables.
// The graph is NEVER serialized into the capability-spec and is NEVER an input
// to itself.
//
// `projectBackendGraph(coordinationPlan)` is a deterministic total function of
// the verified `CoordinationPlan` (Property P1): it reads only that compiler
// datum — never the capability-spec, target identities, domain names, or
// runtime bindings — and is invariant under the waist round-trip. Design +
// normative contract: docs/process/M6_BACKEND_PROJECTION_MODEL.md. Every
// node/field/edge here mirrors that document's §2 node schema and §3 typed-edge
// cardinalities, and is reconciled against the two legalizers by
// scripts/gates/check_backend_projection_bijection.py.
//
// `projectBackendGraph` builds the COMPLETE closed graph in one pass (the
// contract, per the  P1-A ruling): every §2 node family — §2.1 identity /
// replay / lifecycle, §2.2 attestation / guard / evidence, §2.3 effect /
// balance / ledger, §2.4 typed value / reference / compute — and every §3
// cross-family typed edge, with exact §3 cardinalities. The graph is never
// partial: association is carried by typed edges (`scopeRef`, `inputRef`,
// `observerSetRef`, `guardRef`, `groupRef`, `effectRefs`, `assertsRefs`, the
// posting operand refs, `compensates`, …), NEVER re-inferred by name / order.
// The four families map to the Tier-3 backend-consumer migration slices
// (–); those slices switch the legalizers over family-by-family, but
// this shared graph is complete from the start.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDPROJECTION_H
#define NEUTRINO_BACKENDPROJECTION_H

#include "Neutrino/Expr.h"
#include "Neutrino/ProjectionGateMode.h"
#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY
#include "Neutrino/CoordinationPlan.h"
#endif

#include "llvm/Support/Error.h"

#include <cstddef>
#include <optional>
#include <string>
#include <vector>

namespace neutrino {

struct CoordinationPlan;

namespace projection {

// The projection representation version (§7). Bumps on a node-kind/edge
// representation change; INDEPENDENT of agreement identity (`agreementHash`
// stays at the waist and is never recomputed here). A projection is never an
// input to agreement identity, so reorganizing this representation never
// changes the waist hash.
// v2 (): the projected lifecycle-role family (ExecutionMode/LifecycleRole).
// v3 ( S0.1): the additive `Reference.bindingValue` operand.
// v4: lossless evidence-input binding plus the
// per-group guard application mode required to consume the attestation family
// without consulting the CoordinationPlan again.
// v5 (): lossless ordered parameter bindings and typed compute ASTs.
inline constexpr int kProjectionSchemaVersion = 5;

// The CLOSED node-kind set (§2), grouped by the four Tier-3 families. Ordinals
// fix the deterministic emission order (§4: by family, node-kind ordinal,
// stable ID). A new kind is a change to the projection model document and bumps
// `kProjectionSchemaVersion`. Kinds beyond §2.1 are declared here (closed set)
// but only populated by their own slices (-).
enum class ProjectionNodeKind {
  // §2.1 identity / replay / lifecycle ()
  ExecutionIdentity = 0,
  CommitState = 1,
  LifecycleState = 2,
  Transition = 3,
  // §2.2 attestation / guard / evidence ()
  QuorumPolicy = 4,
  GuardObligation = 5,
  EvidenceAcceptance = 6,
  PrimitiveObligation = 7,
  // §2.3 effect / balance / ledger ()
  BalancedEffectGroup = 8,
  LedgerPosting = 9,
  BalanceAssertion = 10,
  CompensationObligation = 11,
  // §2.4 typed value / reference / compute ()
  TypedOperand = 12,
  TypedParam = 13,
  Reference = 14,
  ComputeNode = 15,
  // §2.1 projected lifecycle role ( G1-S1) — a per-(mode, role) lowering
  // obligation, appended (ordinal is part of every stable id; never renumber).
  ProjectedLifecycleRole = 16,
};

// The CLOSED terminal-kind vocabulary a terminal `LifecycleState` carries. A
// non-terminal state carries `None`. `terminal ⇒ terminalKind != None` is a
// verifier obligation (§3).
enum class TerminalKind { None, Success, Aborted, Contested };

// The CLOSED execution-mode vocabulary a `ProjectedLifecycleRole` carries
// (§2.1,  G1-S1). It is the backend-blind lowering axis the target
// legalizers already dispatch on: `Evidence` (evidence-only), `Temporal` (any
// temporally suppressed effect), else `Effectful`. Derived in the projector
// from exactly two `CoordinationPlan` facts (`evidenceOnly`,
// `coordinationIsTemporal`) — no target identity or domain name.
enum class ExecutionMode { Evidence, Effectful, Temporal };

// The CLOSED lifecycle-role vocabulary a `ProjectedLifecycleRole` carries. The
// role is the ALREADY-DECIDED lowering stage a target status-authority site
// spells; the target NEVER selects it. `Initial` — the pre-success region;
// `AcceptedOrAttested` — the intermediate accepted/attested checkpoint (present
// only when the coordination has an attestation stage); `Success` — the
// projected success terminal.
enum class LifecycleRole { Initial, AcceptedOrAttested, Success };

// ---- §2.1 node structs (identity / replay / lifecycle, ) --------------
//
// Every node carries a collision-proof stable `id` (§2.5 — a canonical
// length-prefixed encoding of the `CoordinationPlan` requirement it projects,
// NEVER a display name), the ALREADY-DECIDED typed fields for its kind (the
// node makes no decision), and a diagnostic-only `sourceRef` back to its
// originating `CoordinationPlan` construct (§8; not part of any identity
// payload).

// The per-coordination execution identity (§2.1). `instanceKey` and `replayKey`
// are distinct fields but today project the SAME value — the
// `CoordinationPlan`'s single `workflowKey` (there is no separate
// instance/replay key);
// `replayKey` is a reserved slot for future divergence.
struct ExecutionClaimInput {
  std::string name;
  std::string type;
};

struct ExecutionIdentity {
  std::string id;
  std::string procedureNamespace; // from CoordinationPlan.procedure
  std::string instanceKey;        // from CoordinationPlan.workflowKey
  std::string replayKey;          // from CoordinationPlan.workflowKey
  std::string invokedEvent;
  std::string coordinationIdentity;
  std::vector<ExecutionClaimInput> claimInputs;
  std::string sourceRef;
};

// The commit / idempotency state for a policy scope (§2.1). Owns its policy by
// the typed `scopeRef` edge (never by id/name). `execRef` -> its
// `ExecutionIdentity` (1); `scopeRef` -> its `QuorumPolicy` (1, a  node).
struct CommitState {
  std::string id;
  std::string idempotencyKey; // from CoordinationPlan.workflowKey
  std::string commitScope;    // the policy-scope key this commit is bound to
  std::string sourceRef;
};

// A lifecycle state (§2.1). A terminal state's `name` is the
// `CoordinationPlan`'s `terminal.success` (the projected success terminal),
// with `terminalKind` set; non-terminal states come from
// `lifecycleTransitions`. A terminal state's `requiredCommitRefs` must EXACTLY
// cover the required policies' `CommitState`s (§3).
struct LifecycleState {
  std::string id;
  std::string name;
  bool terminal = false;
  TerminalKind terminalKind = TerminalKind::None;
  std::string sourceRef;
};

// A lifecycle transition (§2.1) projected from `lifecycleTransitions`.
// `fromRef`/`toRef` -> `LifecycleState` (1/1); `effectGroupRefs` ->
// `BalancedEffectGroup` (0..n,  nodes).
struct Transition {
  std::string id;
  std::string name;
  std::string sourceRef;
};

// A projected lifecycle role (§2.1,  G1-S1). ONE record per (mode, role)
// the coordination requires a target to spell — a lowering obligation for a
// particular execution mode, NOT an intrinsic property of the source state (so
// it is a distinct node, not a field on `LifecycleState`). `mode`/`role` are
// closed enums decided by the projector; a typed `stateRef` edge -> the
// `LifecycleState` the role denotes (1). The target legalizer CONSUMES the
// projected (mode, role) via its idiom table and never names a backend status
// enum. The verifier (§3) enforces exactly one `Success` role, no duplicate
// (mode, role), and that every `stateRef` resolves.
struct ProjectedLifecycleRole {
  std::string id;
  ExecutionMode mode = ExecutionMode::Effectful;
  LifecycleRole role = LifecycleRole::Initial;
  std::string state; // the LifecycleState.name this role denotes
  std::string sourceRef;
};

// ---- §2.2 node structs (attestation / guard / evidence, ) --------------

// A per-policy quorum acceptance policy (§2.2). `threshold` is M (> 0); the
// concrete observer-set size N is bound at admission and is NOT read here (§3 —
// `M <= N` is a binding/admission check). `inputRef` -> its
// `EvidenceAcceptance` (1); `observerSetRef` -> a `Reference`
// (role=observerSet, 1).
struct QuorumPolicy {
  std::string id;
  int threshold = 0;            // M — the attestation policy's quorum
  std::string canonicalization; // "exact" | "median"
  std::string timeout;          // "" = none
  std::string fallback;         // "abort" | "escalate"
  std::string sourceRef;
};

// The guard obligation partitioning a gated group / evidence acceptance (§2.2).
// An `attested` guard carries exactly one `policyRef` (its `QuorumPolicy`); a
// `comparison` guard carries none (§3, F12).
struct GuardObligation {
  std::string id;
  std::string guardKind;     // "attested" | "comparison"
  std::string conditionKind; // "quorum" | "comparison"
  // The already-decided application of the guard. This stays independent of
  // the coordination-wide ExecutionMode: a temporal coordination is rejected
  // if even one group is atomic/comparison/unconditional.
  std::string applicationMode; // "atomic-refuse" | "temporal-suppress" |
                               // "comparison"
  std::string sourceRef;
};

// The evidence acceptance contract a `QuorumPolicy` consumes (§2.2). `chained`
// is an INDEPENDENT continuity obligation and is never inferred from `style`.
struct EvidenceAcceptance {
  std::string id;
  // Lossless accepted-input spelling used by target policy bindings. The
  // inputRef edge remains the sole policy->acceptance association; this is an
  // opaque materialization operand, not a second association.
  std::string bindingValue;
  std::string style; // "evidence-only" | "attested"
  bool chained = false;
  std::string admissibility; // closed set (e.g. "exact")
  std::string sourceRef;
};

// The finalized acceptance primitive (§2.2 / §5). `finalizedKind` is the
// closed, backend-neutral semantic SHAPE decided here (never re-derived by a
// downstream operand predicate); `typedOperands` are the policy node ids it
// ranges over. `policyRef` -> `QuorumPolicy` (`.Single`: 1;
// `.PerPolicy`: 1..n).
struct PrimitiveObligation {
  std::string id;
  std::string
      finalizedKind; // "QuorumAcceptance.Single" | "QuorumAcceptance.PerPolicy"
  std::vector<std::string> typedOperands; // policy node ids
  std::string sourceRef;
};

// ---- §2.3 node structs (effect / balance / ledger, ) -------------------

// A balanced effect group (§2.3, B1): it owns guard/balance membership and the
// group's semantic ordinal (`firstIndex`), NEVER byte order. `effectRefs` <->
// `groupRef` is inverse-exact; `guardRef` -> its `GuardObligation` (0..1).
struct BalancedEffectGroup {
  std::string id;
  int firstIndex = 0;  // min(posting.effectIndex) in the group
  std::string pairing; // "identical-guard" ()
  bool mustBalance = false;
  // Lowering payloads copied from the verified projection. They do not
  // participate in stable identity or serialization: effect membership remains
  // owned by the inverse-exact effectRefs/groupRef edges, while these fields
  // prevent a target from re-selecting the already-decided gate behavior or
  // recovering a comparison predicate from source spelling. The comparison
  // expression is canonical typed-expression JSON owned by the graph, never an
  // alias into the source CoordinationPlan AST.
  PlanGateMode gateMode = PlanGateMode::None;
  std::string gatePolicy;
  std::string comparisonGuardExpression;
  // Whether this group carries a rollback CompensationObligation (§2.3 B4): a
  // mustBalance group in a single-transaction (non-temporal) coordination. This
  // makes "needs compensation" a graph-carried fact so the verifier can require
  // exact per-group coverage without re-reading the `CoordinationPlan` (a
  // temporal balanced group correctly needs none). Verification-only; not part
  // of the serialized graph or any identity payload.
  bool rollbackRequired = false;
  std::string sourceRef;
};

// One ledger posting per normalized effect (§2.3, B1/B2). `effectIndex` is the
// original `PlanEffect.index`; exactly one `groupRef`; `ledgerRef`/`partyRef`/
// `amountRef`/`currencyRef` required, `memoRef` optional.
struct LedgerPosting {
  std::string id;
  int effectIndex = 0;
  std::string direction; // "debit" | "credit"
  // Target-facing payload copied from the verified posting. The typed operand
  // edges remain the structural authority and are verified independently;
  // these values retain the lossless source spellings required by the target
  // idioms without a target reading PlanEffect.
  std::string name;
  std::string ledger;
  std::string party;
  std::string amount;
  std::string currency;
  std::string memo;
  std::string sourceRef;
};

// The coordination-scoped balance assertion (§2.3, B3). `assertsRefs` cover
// every and only `mustBalance=true` group, without duplicates.
struct BalanceAssertion {
  std::string id;
  std::string scope; // "coordination"
  std::string sourceRef;
};

// A compensation obligation (§2.3, B4). `mode=rollback` discharges via a
// governed atomicity capability at admission; `mode=compensate` is unsupported
// and must refuse before emission. `compensates` -> a group / transition (1).
struct CompensationObligation {
  std::string id;
  std::string mode; // "rollback" | "compensate"
  std::string sourceRef;
};

// ---- §2.4 node structs (typed value / reference / compute, ) -----------

// A typed operand (§2.4): an already-typed ledger/party/amount/currency operand
// a `LedgerPosting` binds to. Deduplicated by (operandKind, value) — equal
// operands project one shared node.
struct TypedOperand {
  std::string id;
  std::string operandKind; // "ledger" | "party" | "amount" | "currency" | ...
  std::string value;       // the typed operand value ("0", "ref:input:2", ...)
  std::string sourceRef;
};

// A typed transition/procedure parameter (§2.4). `type` is a closed,
// target-neutral type.
struct TypedParam {
  std::string id;
  std::string name;         // canonical structural label
  std::string bindingValue; // lossless declared name
  int ordinal = 0;          // declared parameter order
  std::string type;
  std::string sourceRef;
  // §2.4 closed instance-key role: true iff this param is the declared instance
  // key (the validated CoordinationPlan.workflowKey). Resolved once, above the
  // waist, from the plan fact — consumers read this role and never re-infer the
  // key by name/value equality (, prerequisite for the  recipe).
  bool isInstanceKey = false;
};

// A typed reference (§2.4): an observer-set (or other) reference carried by
// role, resolved by a typed edge (never re-inferred by name).
struct Reference {
  std::string id;
  std::string ref;
  std::string role; // "observerSet" | ...
  // A lossless, opaque authorization operand carried verbatim (S0.1, schema
  // v3): the raw observer-set name the reviewed quorum primitive authorizes
  // against. Present (non-empty) EXACTLY for role=="observerSet"; empty
  // otherwise. This is INDEPENDENT of `ref` — `ref` is the canonical structural
  // label that IDENTIFIES the reference (an ordinal, never a display name),
  // while `bindingValue` is the raw value it AUTHORIZES against. Neither is
  // derived from the other; the projection carries both. (The execution rail is
  // NOT carried here — it is `ProjectedLifecycleRole.mode`, .)
  std::string bindingValue;
  std::string sourceRef;
};

// A typed compute node (§2.4). `operandRefs` -> `TypedOperand`|`ComputeNode`
// (1..n), acyclic; `exprKind`/`dtype` are closed sets.
struct ComputeNode {
  std::string id;
  std::string bindingValue; // lossless declared result name
  int ordinal = 0;          // dependency-declared order
  std::string exprKind;
  std::string dtype;
  std::string expression; // canonical typed-AST JSON
  std::string sourceRef;
};

// ---- Typed edges (§3) ------------------------------------------------------
//
// Association is carried by typed edges, NEVER re-inferred by
// name/input/order. Each edge names one endpoint pair; the verifier
// resolves every `to` to exactly one node of the declared kind (a dangling or
// ambiguous ref fails). `name` is the closed edge vocabulary of §3 (execRef,
// scopeRef, requiredCommitRefs, fromRef, toRef, effectGroupRefs, and the later
// families').
struct ProjectionEdge {
  std::string from; // owning node id
  std::string name; // closed edge-name vocabulary (§3)
  std::string to;   // target node id
  std::string sourceRef;
};

// ---- The graph -------------------------------------------------------------
//
// `{schemaVersion, nodes[], edges[]}` (§2). Nodes are held per-kind (type-safe;
// a new family adds vectors, not shape). Emission is deterministically ordered
// (§4): nodes by (family/node-kind ordinal, stable id), edges by (fromId,
// name, toId). `verify()` establishes it in place.
struct BackendProjectionGraph {
  int schemaVersion = kProjectionSchemaVersion;

  // §2.1 identity / replay / lifecycle.
  std::vector<ExecutionIdentity> executionIdentities;
  std::vector<CommitState> commitStates;
  std::vector<LifecycleState> lifecycleStates;
  std::vector<Transition> transitions;
  std::vector<ProjectedLifecycleRole> projectedLifecycleRoles;

  // §2.2 attestation / guard / evidence.
  std::vector<QuorumPolicy> quorumPolicies;
  std::vector<GuardObligation> guardObligations;
  std::vector<EvidenceAcceptance> evidenceAcceptances;
  std::vector<PrimitiveObligation> primitiveObligations;

  // §2.3 effect / balance / ledger.
  std::vector<BalancedEffectGroup> balancedEffectGroups;
  std::vector<LedgerPosting> ledgerPostings;
  std::vector<BalanceAssertion> balanceAssertions;
  std::vector<CompensationObligation> compensationObligations;

  // §2.4 typed value / reference / compute.
  std::vector<TypedOperand> typedOperands;
  std::vector<TypedParam> typedParams;
  std::vector<Reference> references;
  std::vector<ComputeNode> computeNodes;

  std::vector<ProjectionEdge> edges;
};

// A lossless, association-resolved view of the §2.2 family for thin target
// consumers. It performs no semantic selection: mode/finalizedKind and every
// scalar/binding are copied from already-verified nodes reached through typed
// edges. Policy order is the PrimitiveObligation's typed-operand order.
struct AttestationBinding {
  std::string policyId;
  std::string inputBinding;
  std::string observerSetBinding;
  int threshold = 0;
  std::string canonicalization;
  std::string timeout;
  std::string fallback;
  std::string evidenceStyle;
  bool evidenceChained = false;
  std::string admissibility;
};

struct AttestationProjection {
  ExecutionMode executionMode = ExecutionMode::Effectful;
  std::string finalizedKind;
  std::vector<AttestationBinding> policies;
};

llvm::Expected<AttestationProjection>
consumeAttestationProjection(const BackendProjectionGraph &graph);

// Resolve a group's optional guard and its optional policy through guardRef /
// policyRef. `groupSourceRef` is the projector-authored stable source mapping;
// it identifies the already-projected group and is never parsed or used to
// recover a CoordinationPlan value.
struct GroupGuardProjection {
  bool present = false;
  std::string guardKind;
  std::string conditionKind;
  std::string applicationMode;
  std::string policyInputBinding;
  ExprPtr comparisonGuard;
};
llvm::Expected<GroupGuardProjection>
consumeGroupGuardProjection(const BackendProjectionGraph &graph,
                            const std::string &groupSourceRef);

struct TypedParamProjection {
  std::string name;
  std::string type;
  size_t ordinal = 0;
};

struct ComputeProjection {
  std::string name;
  std::string dtype;
  ExprPtr expression;
  size_t ordinal = 0;
};

struct PostingValueProjection {
  int effectIndex = 0;
  std::string memo;
};

// Lossless, association-resolved §2.4 view. Ordering and optional memo presence
// are facts of the verified projection; target consumers only spell them.
struct TypedValueProjection {
  std::vector<TypedParamProjection> params;
  // §2.4 instance-key association (): the typed param that binds the
  // execution instance key, resolved ABOVE the provider boundary as a dedicated
  // exact-0/1 accessor so a recipe binds it DIRECTLY — there is no scan, name
  // comparison, or boolean predicate in the provider (the closed  grammar
  // has no filter/search). Empty iff NO projected typed param binds the
  // execution key; the key itself may still exist at coordination level (an
  // ExecutionIdentity.instanceKey without a corresponding value input — e.g.
  // the evidence-only rail), in which case there is simply no param to
  // associate.
  std::optional<TypedParamProjection> instanceKeyParam;
  std::vector<ComputeProjection> computes;
  std::vector<PostingValueProjection> postings;
};

llvm::Expected<TypedValueProjection>
consumeTypedValueProjection(const BackendProjectionGraph &graph);

// The finalized, association-resolved traversal sequence consumed by both
// production backends.  This is the authoritative downstream point for
// selecting semantic nodes: targets receive ordered groups/postings and their
// already-resolved guards, rather than re-walking edges or branching on graph
// presence themselves.
enum class FinalizedAttestationKind { None, Single, PerPolicy };

enum class FinalizedPostingDirection { Debit = 0, Credit = 1 };
enum class FinalizedPostingGuardKind { Direct = 0, Comparison = 1 };

// The closed postings-shape variant: whether the coordination's postings carry
// a memo. The target-blind finalizer decides this ONCE from the verified
// posting values; backends bind its presence mechanically (they may not re-scan
// postings or inspect memo strings below the waist).
enum class FinalizedPostingsSchemaKind { Plain = 0, WithMemo = 1 };

// The per-posting closed memo variant (): whether THIS posting supplies a
// memo value to its ledger write. Distinct from the coordination-wide
// `FinalizedPostingsSchemaKind` (which decides whether the postings TABLE has a
// memo column at all): a WithMemo table may still receive individual postings
// with no memo (they omit the memo column from their own INSERT and rely on the
// column default). The target-blind finalizer decides this ONCE from the
// verified posting value; a generated backend dispatch selects the memo-column
// vs non-memo posting INSERT shape by reading this typed variant — it MUST NOT
// re-scan the posting or string-test `memo` below the waist.
enum class FinalizedPostingMemo { Absent = 0, Present = 1 };

struct FinalizedPostingProjection {
  const LedgerPosting *posting = nullptr;
  FinalizedPostingDirection direction = FinalizedPostingDirection::Debit;
  FinalizedPostingGuardKind guardKind = FinalizedPostingGuardKind::Direct;
  // Non-owning observer into the parent FinalizedEffectGroupProjection's
  // GroupGuardProjection. The group owns the immutable AST for the entire
  // lifetime of both finalizedPostings and the flattened postings view.
  const ExprNode *comparisonGuard = nullptr;
  std::optional<std::string> memo;
  // : the per-posting typed memo variant (see FinalizedPostingMemo). This
  // is the SAME fact as `memo.has_value()`, promoted to a closed enum so a
  // generated backend selects the posting shape without an optional/string
  // test. Target-neutral: it carries NO string escaping (SQL-literal-safe
  // spellings are `<target>.string.escape` under the  contract — the target
  // leaf hook's job, not the shared projection's). The RAW leaf spellings
  // survive on `posting->ledger` / `posting->name` / the `memo` optional above,
  // and a target escapes them through its own registered hook when building
  // executable output, keeping the decorative comment bound to the raw values.
  FinalizedPostingMemo memoPresence = FinalizedPostingMemo::Absent;
  size_t groupIndex = 0;
  size_t ordinal = 0;
};

struct FinalizedEffectGroupProjection {
  const BalancedEffectGroup *group = nullptr;
  std::vector<const LedgerPosting *> postings;
  std::vector<FinalizedPostingProjection> finalizedPostings;
  GroupGuardProjection guard;
  size_t ordinal = 0;
};

struct FinalizedExecutionClaimInput {
  std::string name;
  std::string type;
  std::string category;
  size_t ordinal = 0;
};

// A temporal policy's finalized, target-facing identifier and semantic order.
// The shared finalizer validates the identifier once and assigns the ordinal
// from the already-verified PrimitiveObligation operand order. Backends may
// snapshot these typed fields; they may not reinterpret inputBinding or invent
// their own ordering.
struct FinalizedTemporalPolicyProjection {
  std::string targetIdentifier;
  size_t ordinal = 0;
};

struct FinalizedProjectionSequence {
  const BackendProjectionGraph *graph = nullptr;
  ExecutionIdentity executionIdentity;
  std::vector<ProjectedLifecycleRole> lifecycleRoles;
  ProjectedLifecycleRole initialLifecycleRole;
  ProjectedLifecycleRole successLifecycleRole;
  std::vector<FinalizedExecutionClaimInput> claimInputs;
  ExecutionMode executionMode = ExecutionMode::Effectful;
  FinalizedAttestationKind attestationKind = FinalizedAttestationKind::None;
  AttestationProjection attestation;
  std::vector<FinalizedTemporalPolicyProjection> temporalPolicies;
  TypedValueProjection values;
  std::vector<FinalizedEffectGroupProjection> effectGroups;
  std::vector<FinalizedPostingProjection> postings;
  std::vector<const BalanceAssertion *> balanceAssertions;
  // Finalized once by the target-blind finalizer (see above).
  FinalizedPostingsSchemaKind postingsSchemaKind =
      FinalizedPostingsSchemaKind::Plain;
};

llvm::Expected<FinalizedProjectionSequence>
consumeFinalizedProjectionSequence(const BackendProjectionGraph &graph);

// ---- Stable identity encoding (§2.5) ---------------------------------------
//
// A collision-proof stable id: the node kind followed by a CANONICAL
// length-prefixed encoding of the identifying components. Length-prefixing
// makes punning impossible — a single quoted component `"Q.A"` cannot collide
// with the two-component path `["Q","A"]`, and separators/quotes need no
// escaping. This is NEVER a display name. `projectionNodeId` is the sole id
// minter.
std::string projectionNodeId(ProjectionNodeKind kind,
                             const std::vector<std::string> &components);

// ---- The projector ---------------------------------------------------------
//
// The deterministic, domain-blind projection of the verified
// `CoordinationPlan` into the graph (Property P1). This slice populates
// the §2.1 family, then runs `verifyAndOrder` on the result: on a non-empty
// diagnostic it returns an explicit `llvm::Error` carrying that stable
// diagnostic identity (the diagnostic is never discarded, asserted, thrown, or
// fatal). So a projection that fails verification can NEVER escape as a
// successful graph — a caller must check the `Expected` before it can reach any
// nodes, and no artifact-producing caller can proceed after a failure.
llvm::Expected<BackendProjectionGraph>
projectBackendGraph(const CoordinationPlan &coordinationPlan);

// ---- The verifier ----------------------------------------------------------
//
// Establishes the §2-§3 invariants on a graph: unique stable ids; every `*Ref`
// resolves to exactly one node of the declared kind (no dangling/ambiguous);
// exact edge cardinalities (a `CommitState` has exactly one `execRef` + one
// `scopeRef`; a `Transition` exactly one `fromRef` + one `toRef`); `terminal ⇒
// terminalKind set` and a terminal state's `requiredCommitRefs` exactly cover
// the required `CommitState`s; and the deterministic order (§4). Returns a
// stable diagnostic identity `diag:<nodeKind|edge>:<rule>` on the first
// violation (§8), or empty on success. Also normalizes ordering in place.
std::string verifyAndOrder(BackendProjectionGraph &graph);

} // namespace projection
} // namespace neutrino

#endif // NEUTRINO_BACKENDPROJECTION_H
