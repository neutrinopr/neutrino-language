# Diagnostic Taxonomy (M5 WP1c, )

The **shared failure taxonomy**: the single, compiler-owned vocabulary of stable
diagnostic `code`s emitted across the whole toolchain — the semantic **kernel
verifier**, the frontend, scenario validation, the expression gate, the value
model, the security pass, generation, and equivalence. It is also the vocabulary
that **target-profile legality** diagnostics (later M5 WPs) draw from, so a code
means the same thing wherever it appears.

This is the keystone  owns. It is binding under
[`M5_DECISIONS_ADR.md`](../process/M5_DECISIONS_ADR.md): diagnostics are the contract by
which agents and CI reason about failure, so their codes are governed, not
ad-hoc.

**Source of truth (M5  D1, ).** The taxonomy is a single **declarative
source**, [`include/Neutrino/DiagnosticTaxonomy.def`](../../include/Neutrino/DiagnosticTaxonomy.def)
— one `NEUTRINO_DIAG(Category, "code", Status, precedence, "summary", Emitter)`
row per code. The C++ table (`lib/DiagnosticTaxonomy.cpp`) **expands** those rows
via an X-macro (it no longer hand-maintains the table), and the machine-readable
[`diagnostic-taxonomy.json`](../diagnostic-taxonomy.json) is emitted from that table
(`neutrino-translate --diagnostic-taxonomy`) — so both derive from the `.def`. A
fail-closed drift check (self-test `[78]`) byte-matches the committed JSON against
the compiler's output, so a `.def` edit that isn't regenerated fails CI. To add or
change a code, edit the `.def` and regenerate the JSON.

The table registers codes from **both** producers of diagnostics in this
toolchain — the C++ tools and the stdlib (Python) validators in `scripts/` that
are part of it. Each entry records its `emitter` (`cpp` | `validator`) so a
consumer can tell a compiler diagnostic from a validator one, and so each side is
enforced against the table by its own gate (below). The `classification.*` (),
`spec.*` (), and the target-profile `profile.*` + `legality.*` (WP4, /)
families are registered here as `validator` emitters — exactly the "compatible
with the  taxonomy" hand-off each shipped with (the `legality.*` gate is the
fail-closed target-profile legality check this taxonomy's scope names directly).

Out of scope for now: the L2-semantics, binding-manifest (`NEU-*`), and
capability-claims validators use separate diagnostic schemes that predate this
taxonomy; unifying them is a later step, not part of WP1c.

The compiler is the source of truth. `neutrino-translate --diagnostic-taxonomy`
emits the table as deterministic JSON; [`diagnostic-taxonomy.json`](../diagnostic-taxonomy.json)
is that output committed and **byte-matched** by a self-test (the same
compiler-owned + drift-tested pattern as the language metadata,  / ADR D10).
`lib/DiagnosticTaxonomy.cpp` is the table; this file narrates it.

## Two guarantees

1. **Every semantic diagnostic `code` comes from this table.** No ad-hoc code
   strings. Enforced per emitter: self-test `[76]` sweeps *every* `diagnostics.json`
   the **C++** tools (`neutrino-gen`, `neutrino-equiv`) write across the suite and
   asserts each `code` is a registered, `active` code; the **validator** families
   are cross-checked by asserting the codes their validator source defines equal
   the `validator`-emitter codes registered here (so neither can drift from the
   other).
2. **Diagnostics are root-cause ordered.** The first diagnostic is the primary
   failure; cascades are subordinated. Each code carries a `precedence` (lower =
   more fundamental); `orderByRootCause` (a stable sort, so equal-precedence
   diagnostics keep emission order) is applied before `diagnostics.json` is
   written.

## Where a code appears

- **Kernel verifier** (the MLIR/IR-level checks in `NeutrinoDialect.cpp`) emits
  the code inline as a `[code] ` prefix on the op-error message (e.g.
  `[kernel.balance.unbalanced] is not balanced: …`) — a hand-written `.mlir`
  cannot fail open, and the code is greppable on stderr.
- **Tools** (`neutrino-gen`, …) put the code in the `code` field of each
  `diagnostics.json` entry, ordered root-cause first.

## Categories

Ordered by root-cause precedence (most primary first): a run that cannot even
form IR fails before one whose IR is malformed, which fails before a bad
scenario, which fails before a generation/equivalence problem.

| Category | Owner | Meaning |
| --- | --- | --- |
| `frontend` | frontend / source load | `.neu`→IR parse, `.mlir` parse, IR verification entry |
| `kernel` | semantic kernel verifier | the structural + flow invariants of the coordination (balance, version, binding, …) |
| `value` | typed value model (WP1a, ) | an operand carries the wrong value category for its role |
| `expr` | compute-expression gate (WP1b, ) | an unsupported / ill-typed compute expression |
| `scenario` | scenario validation | the scenario document is malformed or invalid for the procedure |
| `security` | capability security pass | a hard security-posture violation gates lowering |
| `generate` | generation / tooling | target/usage errors, aborted generators, internal faults |
| `equivalence` | cross-backend equivalence | a backend disagreed with the reference evaluator / a backend toolchain failed or was skipped |
| `classification` | solidity-classification validator (, `validator` emitter) | the solidity-samples `classification.json` profile shape is invalid |
| `spec` | capability-spec validator (, `validator` emitter) | the canonical compiled capability-spec is malformed / inconsistent |
| `profile` | target-profile validator (/, `validator` emitter) | a target profile is malformed / declares conflicting features |
| `legality` | spec-legality gate (/, `validator` emitter) | a spec requires a feature its target profile does not support |
| `realization` | test-realization validator (WP2, , `validator` emitter) | a test-realization companion is malformed or its `capabilityHash` does not match the spec |
| `view` | participant-view validator (, `validator` emitter) | a participant view is malformed or disagrees with the referenced spec |
| `observation` | domain-observation-set validator (S0, , `validator` emitter) | a deterministic corpus-observation set is malformed, its corpus content-hash binding / dimension vocabulary is violated, or an AI-trust field (`observation.ai_field_forbidden`) leaked into what must be pure facts |
| `domain` | L2 domain layer — versioned import resolution (, `cpp` emitter) | a domain's `l2.import` resolves to no registry capability (`domain.import.dangling`), a capability at the wrong version (`domain.import.unknown`), more than one registry entry (`domain.import.ambiguous`), a cyclic transitive import graph (`domain.import.cyclic`), or a registry entry whose governed v2 sidecar is missing/invalid or fails its hash/identity pin (`domain.import.ungoverned`) |

## Active kernel codes (this WP)

WP1c gives every kernel verifier diagnostic a machine-readable code (before, only
`value_type.mismatch` carried one). The balance codes realize the acceptance
item *"balance conservation is statable and checked at spec level"*:

- `kernel.version.invalid`
- `kernel.balance.assert_missing` · `kernel.balance.not_balanceable` · `kernel.balance.unbalanced`
- `kernel.binding.invalid_mode` · `…policy_without_flag` · `…missing_binder` · `…missing_runtimes` · `…empty_runtime` · `…invalid_assurance`
- `kernel.attest.invalid_quorum` · `…missing_observer_set` · `…invalid_canonicalization` · `…invalid_fallback` · `…invalid_assurance` · `…invalid_independence`
- `kernel.obligation.identity` · `…obligor` · `…scope` · `…ambiguous_ref` · `…predicate` · `…effects_empty` · `…not_an_effect` · `…duplicate_effect` — the L1 v0.2 `obligation` structural verifier (): an active first-class undertaking whose lifecycle is distinct from effect execution; its obligor/beneficiary/authority resolve to declared participants, its `when` predicate reuses the `#neutrino.expr` typing (`expr.*` on an ill-typed/unbound predicate), and its ordered effect references must each resolve to a value effect (`debit`/`credit`), never a participant or another obligation. The R1b coordination-plan realization () additionally fails closed (a plain, uncoded diagnostic) when an obligation's ordered effect references disagree with the executable coordination-plan order — a reversed authorization is refused, not silently reordered.

## Reserved kernel codes (future WP1c slices)

The remaining  rules need kernel primitives that L1 does not model yet (state
machines, compensation, reservations, evidence gates, ordering scopes). Their
codes are **reserved** in the taxonomy — named and stable so target profiles and
the follow-up rule slices bind to them now — but they are `status: "reserved"`
and must not appear in emitted diagnostics until the rule that owns them lands:

`kernel.state.guard_undeclared_state`, `kernel.state.nonterminal_success`,
`kernel.effect.unreachable`, `kernel.effect.abort_value_effect`,
`kernel.compensation.not_inverse`, `kernel.reservation.not_conserved`,
`kernel.idempotency.inconsistent`, `kernel.ordering.undeclared_scope`,
`kernel.participant.guard_undeclared`, `kernel.target.requirement_unbacked`,
`kernel.evidence.gate_unsatisfiable`.

**Ownership transfer note.** `spec.dead_end_state` today lives only in the Python
capability-spec validator () and is correct there while the state machine is
emitter-hardcoded (a C++ check would verify a constant). When the L2 author-defined
machine arrives, exit-completeness becomes a **kernel verifier** rule under the
reserved `kernel.state.*` space (e.g. `kernel.state.nonterminal_success`), and the
Python check demotes to independent verification per D10. The reserved space above
anticipates that transfer.

## Known follow-up (F3): surface the kernel code across the IR-verify boundary

When `neutrino-gen`/`neutrino-equiv` load a failing `.mlir`, `diagnostics.json`
currently carries `code: "ir.verify"` while the specific `[kernel.*]` code sits in
the message (the verifier emits it as a stderr bracket prefix). A fast-follow will
extract that leading `[kernel.*]` prefix at the `ir.verify` failure path and
surface it as the diagnostic `code` (falling back to `ir.verify`), so machine
consumers never scrape brackets. The bracket stays as a stderr-greppability nicety.

## Adding a code

1. Add the entry to `kTaxonomy` in `lib/DiagnosticTaxonomy.cpp` (code, category,
   status, a `precedence` in the right band, one-line summary). Ship it
   `reserved` until the emitter exists, then flip to `active` in the same PR that
   emits it.
2. Regenerate the committed JSON: `neutrino-translate --diagnostic-taxonomy > docs/diagnostic-taxonomy.json`.
3. Emit it from exactly one place; the membership self-test enforces that every
   emitted code is registered and `active`.

Do **not** hand-edit `diagnostic-taxonomy.json` — it is a generated artifact.
