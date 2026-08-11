#ifndef NEUTRINO_COORDINATION_PLAN_H
#define NEUTRINO_COORDINATION_PLAN_H

#include "Neutrino/Attestation.h"
#include "Neutrino/Expr.h"
#include "Neutrino/ProjectionGateMode.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <optional>
#include <string>
#include <vector>

namespace neutrino {

// Exact canonical authorization labeling backtracks only within this bounded
// actor set. Enforce the limit in assemblePlan before any projection work so a
// symmetric external spec cannot turn canonicalization into factorial work.
inline constexpr size_t kMaxCanonicalAuthorizationParticipants = 8;

// The versioned obligation-plan representation ().
// assemblePlan/planFromSpec fail closed on any other version, so a future
// obligation shape cannot be silently mis-read by this consumer.
inline constexpr int kObligationPlanVersion = 1;

// The lifecycle status vocabulary an obligation of representation `version`
// exposes. DERIVED from the version — NOT carried on the wire — so there is no
// independent field an ingested spec can tamper: the version alone defines the
// vocabulary ( P1-3). v1 = {eligible, fired, refused}. Returns an empty
// vector for an unrecognized version (the version check rejects it first).
std::vector<std::string> obligationStatusVocabulary(int version);

// A target-neutral, typed normalization of a verified coordination (). It
// is the SINGLE normalized semantic source: built directly from the verified
// MLIR (normalizePlan, the named analysis), it is what capability-spec's
// normalized decisions are serialized FROM and what every backend renderer
// consumes — so the workflow key, the per-group balance obligation, the guard
// partition, and the effect->attestation binding are resolved and VERIFIED
// once, in one place, and cannot drift between producer and consumer.
// planFromSpec reconstructs the identical contract from an external
// capability-spec.

// HOW an attestation policy gates an effect/group — decided and verified once,
// here in the normalized coordination plan, so a target legalizer consumes the
// binding rather than re-deriving it from the guard AST (, the
// anti-inference boundary ):
//   None            — ungated (no attestation policy).
//   AtomicRefuse    — a single global gate: the whole transition REFUSES until
//                     the (sole) declared policy is accepted ( legacy).
//   TemporalSuppress— per-policy SUPPRESS (accepted(x)): an unaccepted policy
//                     no-ops only its OWN balanced legs while the transition
//                     still commits, over the  per-(key,group) commit
//                     ledger.
// One effect as the coordination plan sees it: its position in effects[], the
// canonical guard that partitions it, and the attestation policy that gates it.
struct PlanEffect {
  size_t index = 0; // position in the spec's effects[]
  std::string name;
  std::string kind;           // "debit" | "credit"
  std::string participant;    // declared authorization actor ("" = unbound)
  std::string canonicalGuard; // the `when` SOURCE text ("" = unconditional) —
                              // the byte-compatibility projection, NOT the
                              // partition key
  // The SEMANTIC canonical key ( amendment 4): a deterministic STRUCTURAL
  // serialization of the guard predicate used for partitioning/equivalence,
  // separate from the source text above. Conservative — no algebraic folding /
  // commutation — so it never claims two differently-meaning guards equal.
  std::string guardKey;
  std::string attestationInput; // gating policy's input ("" = ungated)
  // The explicit, verified attestation binding () a target legalizer reads
  // WITHOUT recognizing `accepted()` or inspecting the guard AST: the gating
  // policy input (`gatePolicy`, "" when None) and HOW it gates (`gateMode`).
  // AtomicRefuse mirrors attestationInput; TemporalSuppress carries the
  // accepted(x) policy that attestationInput deliberately leaves "".
  PlanGateMode gateMode = PlanGateMode::None;
  std::string gatePolicy;
  // The ledger-delta operands (): this effect posts `amount` of `currency`
  // to `ledger` on behalf of `party`. `ledger` is a literal ledger name;
  // party/amount/currency are operand identities ("kind:value", e.g.
  // "ref:amount" / "literal:100") — the SAME form assemblePlan conserves. The
  // reference evaluator (CoordinationEval, ) resolves `amount` against the
  // transition input to produce the signed ledger delta; renderers ignore them
  // (they read the spec/view), so carrying them here is additive.
  std::string ledger;
  std::string party;
  std::string amount;
  std::string currency;
  // The optional free-text memo/reference declared on this effect () — a
  // presentation label carried on the normalized plan so a renderer never has
  // to re-read it from the spec ("" = none).
  std::string memo;
  // The target-neutral typed guard predicate the renderers lower (
  // amendment 3); null when unconditional. Owned by the plan, MLIR-free.
  ExprPtr guard;
};

// Effects sharing one canonical guard — the partition a renderer wraps
// together. The balance obligation is per group: value must be conserved on the
// partition where the guard holds, so a guarded pair (debit+credit under one
// guard) is the balanced unit. `firstIndex` (first appearance in effects[])
// fixes emission order.
struct PlanEffectGroup {
  std::string canonicalGuard; // representative source text ("" = unconditional)
  std::string guardKey; // the semantic canonical key this group is keyed on
  std::string attestationInput; // "" = ungated
  // The verified attestation binding for this group (), consistent across
  // its effects — the field a target legalizer consumes. See PlanEffect above.
  PlanGateMode gateMode = PlanGateMode::None;
  std::string gatePolicy;
  std::vector<size_t> effectIndices;
  size_t firstIndex = 0;
  bool mustBalance = false; // the balanced obligation applies to this group
  unsigned debitCount = 0;
  unsigned creditCount = 0;
};

// A compute in dependency-declared order, carrying its typed value category and
// the target-neutral typed expression the renderers lower ( amendment 3).
struct PlanCompute {
  std::string name;
  std::string category; // typed value category (money/number/party/…/extension)
  std::vector<std::string> deps;
  ExprPtr expr; // owned, MLIR-free typed AST
};

// A first-class undertaking carried into the plan (L1 v0.2 O1, ). The
// MINIMUM versioned representation that preserves obligation identity,
// obligor/scope, the activation predicate, the lifecycle status vocabulary, and
// the ORDERED referenced effects — WITHOUT flattening the obligation into an
// anonymous guard + effects. Its lifecycle (eligible/fired/refused) stays
// distinct from effect execution: the `effects` are references to declared plan
// effect names, in order; the `when` predicate determines eligibility, the
// effects fire only when eligible, and the plan never re-reads a backend.
struct PlanObligation {
  // The versioned obligation-plan representation. assemblePlan/planFromSpec
  // fail closed on an unknown version, so a future obligation shape cannot be
  // silently mis-read by this consumer.
  int version = 1;
  std::string name;                            // the obligation identity
  std::string obligor, beneficiary, authority; // declared authorization actors
  std::string canonicalGuard; // the `when` source text ("" is not permitted)
  std::string guardKey;       // canonicalGuardKey(when) — the structural key
  ExprPtr when;               // owned, MLIR-free typed activation predicate
  std::vector<std::string> effects; // ORDERED references to plan effect names
  // The lifecycle status vocabulary this obligation ranges over, distinct from
  // effect execution (the evaluator observes exactly these).
  std::vector<std::string> statuses;
};

// The replay/idempotency obligation: effects post at most once per this key.
struct ReplayObligation {
  std::string key;        // the workflow/idempotency key
  bool idempotent = true; // one posting per key (replay-safe)
};

// The backend-visible lifecycle projection current targets read: the success
// terminal each backend's Reconciled state projects, plus the other terminals.
struct TerminalProjection {
  std::string success;   // required; the renderers fail closed without it
  std::string aborted;   // "" when the lifecycle declares none
  std::string contested; // "" when the lifecycle declares none
};

// One schema-defined guard on a lifecycle transition. This is distinct from
// the typed expression guards on ledger effects above: lifecycle guard kinds
// are a closed capability-spec vocabulary carried byte-for-byte through the
// normalized coordination plan.
struct LifecycleTransitionGuardPolicy {
  std::string kind;   // "participant" | "deadline" | "sequence"
  std::string detail; // optional producer-defined detail ("" = absent)
};

// A schema-defined evidence obligation on a lifecycle transition. `style`
// selects the evidence aggregation contract; `chained` is an independent
// continuity obligation and must never be inferred from the style.
struct LifecycleTransitionEvidencePolicy {
  std::string style; // "single_hash" | "batched_root"
  bool chained = false;
};

// Backend-visible lifecycle transition policy. It is target-neutral data
// carried from the canonical lifecycle/spec into the normalized plan so
// backend consumers do not infer transition semantics from the spec text.
struct LifecycleTransitionPolicy {
  std::string name;
  std::string from;
  std::string to;
  std::vector<std::string> effects; // e.g. {"post"}, {"compensate"}
  std::vector<LifecycleTransitionGuardPolicy> guards;
  std::string idempotency; // "reject" | "noop_on_identical"
  std::optional<LifecycleTransitionEvidencePolicy> evidence;
};

// A declared input in the normalized inventory: its name and declared type
// name. Carried so the semantic-requirement derivation can classify inputs
// (e.g. a temporal type -> a time requirement) from the verified plan alone,
// without re-reading source or spec text.
struct PlanInput {
  std::string name;
  std::string type; // the declared type name (e.g. "money", "timestamp")
};

// A target-neutral authorization actor. Runtime binding families, capabilities,
// and assurance metadata are realization policy and deliberately stay outside
// the normalized execution plan.
struct PlanParticipant {
  std::string name;
  std::string role;
  std::string org;
};

// One permitted organization-to-organization coordination edge. Roles are
// target-neutral policy labels; role eligibility remains a downstream policy
// check while this seam verifies that the organization endpoints exist.
struct PlanOrgPolicy {
  std::string orgA;
  std::string orgB;
  std::string roleA;
  std::string roleB;
};

struct CoordinationPlan {
  std::string procedure;

  // The declared invoked-event name (the `trigger`), a presentation label the
  // normalized plan carries so a renderer never re-reads it from the spec ("" =
  // none declared; a renderer may apply its own default).
  std::string invokedEvent;

  // The declared input inventory in declaration order.
  std::vector<PlanInput> inputs;

  // Declared authorization actors and their allowed coordination topology.
  std::vector<PlanParticipant> participants;
  std::vector<PlanOrgPolicy> allowedOrgPairs;

  // The one verified workflow/idempotency key. It is either the explicitly
  // declared instance key (below) or, for a legacy effectful procedure that
  // declares none, the input every effect's idempotencyKey references.
  // Resolution fails when it is missing, is not a `ref`, or when effects
  // disagree.
  std::string workflowKey;

  // The procedure-level explicit instance-key declaration: the input the
  // coordination declares as its identity, independent of any ledger effect
  // ("" when the key is derived from effects the legacy way). Target-neutral;
  // an effectless evidence-only coordination MUST declare one.
  std::string explicitInstanceKey;

  // An effectless coordination whose action is evidence acceptance (an
  // attestation policy with no ledger movement). Permitted only with an
  // explicit instance key and a success terminal.
  bool evidenceOnly = false;

  // The procedure-level balanced obligation (invariants[].balanced). Per-group
  // obligations live on PlanEffectGroup.mustBalance.
  bool balanced = false;

  // Effects in spec order, each tagged with its guard partition + policy
  // binding.
  std::vector<PlanEffect> effects;

  // Effects partitioned by canonical guard (group order = first appearance),
  // each carrying its balance obligation + debit/credit shape.
  std::vector<PlanEffectGroup> effectGroups;

  // Computes in declared order, with their typed value category + deps.
  std::vector<PlanCompute> computes;

  // Declared attestation policies (/).
  std::vector<AttestationPolicy> attestations;

  // The replay/idempotency obligation (keyed on workflowKey).
  ReplayObligation replay;

  // The verified lifecycle->backend terminal projection.
  TerminalProjection terminal;

  // The verified lifecycle state inventory and its distinguished initial
  // state. State names are identities inside the plan; canonical projections
  // structurally relabel them rather than dropping the graph obligation.
  std::string lifecycleInitialState;
  std::vector<std::string> lifecycleStates;

  // The verified lifecycle transition idempotency projection.
  std::vector<LifecycleTransitionPolicy> lifecycleTransitions;

  // First-class undertakings (L1 v0.2 O1, ). Empty for every current spec,
  // so an obligation-free plan serializes + hashes byte-identically.
  std::vector<PlanObligation> obligations;
};

// Raw, pre-normalization inputs gathered by either builder — normalizePlan
// (from the verified MLIR view) or planFromSpec (from a capability-spec).
// assemblePlan applies the ONE normalization + verification, so both paths
// yield an identical plan and the derivation lives in a single place.
struct PlanEffectInput {
  std::string name;
  std::string kind;            // "debit" | "credit"
  std::string participant;     // authorization actor ("" = unbound)
  std::string idempotencyKind; // "ref" | "literal" | ""
  std::string idempotencyValue;
  std::string canonicalGuard;     // "" = unconditional
  std::string guardAcceptedInput; // if the guard is accepted(x): x; else ""
  // The moved value's operand identity, "kind:value" ("ref:amount",
  // "literal:100", …). assemblePlan checks that a balanced group's debited
  // (amount, currency) multiset equals its credited one — so the group provably
  // conserves value, not merely "has a debit and a credit".
  std::string amount;
  std::string currency;
  // The remaining ledger-delta operands the reference evaluator needs (),
  // carried through to PlanEffect. `ledger` is a literal ledger name; `party`
  // is an operand identity ("kind:value").
  std::string ledger;
  std::string party;
  // The optional effect memo (), carried through to PlanEffect ("" = none).
  std::string memo;
  // The target-neutral typed guard predicate (null when unconditional); moved
  // into the assembled plan ( amendment 3).
  ExprPtr guard;
};

// Raw obligation input (), gathered by either builder before assemblePlan
// resolves obligor/scope/effects and stamps the lifecycle statuses.
struct PlanObligationInput {
  int version = 1;
  std::string name, obligor, beneficiary, authority;
  std::string canonicalGuard;
  ExprPtr when; // owned typed activation predicate
  std::vector<std::string> effects;
};

struct PlanInputs {
  std::string procedure;
  std::string invokedEvent;      // the declared trigger ("" = none)
  std::vector<PlanInput> inputs; // the declared input inventory
  std::vector<PlanParticipant> participants;
  std::vector<PlanOrgPolicy> allowedOrgPairs;
  std::vector<PlanEffectInput> effects;
  std::vector<PlanCompute> computes;
  std::vector<AttestationPolicy> attestations;
  bool balanced = false;
  TerminalProjection terminal;
  std::string lifecycleInitialState;
  std::vector<std::string> lifecycleStates;
  std::vector<LifecycleTransitionPolicy> lifecycleTransitions;
  std::vector<PlanObligationInput> obligations; //
  // The declared procedure-level instance key ("" = derive from effects). Both
  // builders populate it (from the MLIR attribute / the spec's declared key);
  // assemblePlan verifies it names a declared, string-category input.
  std::string explicitInstanceKey;
};

// The SEMANTIC canonical key of a guard predicate ( amendment 4): a
// deterministic STRUCTURAL serialization used for guard partitioning /
// equivalence. Conservative — NO algebraic folding, commutation, or
// reassociation — so `a >= b` and `b <= a` get DIFFERENT keys (a commutation
// that rounding/division/overflow need not preserve is never performed). "" for
// a null (unconditional) guard.
std::string canonicalGuardKey(const ExprNode *n);

// The single normalization + verification seam. Fails (Error) BEFORE renderer
// dispatch on: no effects; a missing / non-ref / ambiguous workflow key; an
// effect gated on an undeclared attestation policy; a guard group whose effects
// disagree on their policy binding; a balanced group with no debit/credit pair;
// or a lifecycle with no success terminal. Takes PlanInputs BY VALUE so it can
// move the owned expressions into the plan.
llvm::Expected<CoordinationPlan> assemblePlan(PlanInputs in);

// Reconstruct + VERIFY the plan from an external / emitted capability-spec (the
// consumer/round-trip path). Returns an Error (never throws —  ratchet)
// BEFORE renderer dispatch on: no effects; a missing / non-ref / ambiguous
// workflow key; an effect gated on an undeclared attestation policy; a guard
// group whose effects disagree on their policy binding; a balanced group with
// no debit/credit pair; or a lifecycle with no success terminal. The plan it
// produces is byte-for-byte the plan normalizePlan builds from the same
// procedure's verified MLIR.
llvm::Expected<CoordinationPlan> planFromSpec(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_COORDINATION_PLAN_H
