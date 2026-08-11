# Neutrino `.neu` Language Specification (M5)

Normative contract for the **currently accepted** `.neu` source language — the
deterministic surface the compiler (`neutrino-translate` / `neutrino-gen`) parses
into Neutrino MLIR. Reviewers, implementors, and downstream rails should rely on
this document rather than inferring behavior from examples.

Status: M5 language maturity, extending the M3 surface (strategy ) with
**conditional guards** (`when`) and the **guard-aware balanced invariant** (M5 WP7,
/; see [EXPRESSION_MODEL.md](EXPRESSION_MODEL.md)), on the M2 compiler
boundary (strategy ). What is *accepted* here is pinned by the conformance suite
under `test/conformance/` (self-test `[56]`) — and the guarded shapes by the domain
golden suite (`core_document_escrow`, an externalized domain pack); what is *rejected*
is equally normative. This spec describes the **source** language only — it is not
the MLIR/IR contract (see "Lowering boundary").

## Lexical structure

- **Encoding / lines.** UTF-8; the parser is **line-oriented** — every statement and
  every block field is its own logical line, and a block's closing `}` is on its own
  line. (`debit d { ledger = … }` on one line is a syntax error.)
- **Comments.** `//` and `#` run to end of line. A comment marker *inside* a
  double-quoted string literal is not a comment. Comments and blank lines are not
  semantically significant (they never affect any capability/semantic hash).
- **Whitespace.** Leading/trailing whitespace is insignificant; field alignment is
  stylistic.
- **Identifiers.** Procedure/participant/input/compute/leg names are bare words.
  Names are declared once; a redeclaration is an error.
- **Values.** A value is either a `"double-quoted literal"` or a `%reference` to a
  previously declared `input` or `compute`. Anything else is a parse error. A
  `compute` may only reference names declared above it.

## Top-level

A file is one or more procedures. Each top-level statement is either:

- `procedure NAME { … }`, or
- `agreement NAME between A and B { … }` — surface sugar that desugars to
  `procedure NAME { … }` plus two declared participants `A` and `B` (default role =
  the party name lowercased) and an inferred `allow` org-pair policy. A later
  explicit `participant A { … }` block augments the sugared declaration.

Anything else at top level (including the pseudo-syntax blocks below) is rejected.

## Procedure body

Statements, in source order (order is preserved into the IR and every artifact):

### `trigger NAME`
The event that initiates the coordination. Optional but conventional.

### `version "MAJOR.MINOR.PATCH"`
Optional DSL/semantic version (defaults to `0.1.0`). Must be a valid three-part
SemVer; it flows into capability identity (`capabilityVersion`/`dslVersion`).
Breaking changes fork rather than mutate (see [VERSIONING.md](../process/VERSIONING.md)).

### `instance_key NAME`
Declares the coordination's replay/idempotency identity explicitly, as a declared
string-typed `input` — independent of any ledger effect. Optional for an effectful
coordination (whose key is otherwise derived from its effects' idempotency keys), but
**required** for an effectless **evidence-only** coordination (an `attest` policy with no
debit/credit), which has no effect to derive a key from. At most one declaration; the named
input must be declared and string-typed, or the coordination fails before dispatch.

### `participant NAME { … }`
Optional abstract participant (a role/trust boundary, not a concrete identity).
Fields:

- `role = "..."` — abstract role.
- `org = "..."` — owning organization / trust boundary.
- `capabilities = ["...", ...]` — declared capabilities.
- Late-binding policy (Trust lane): `binding = "to_be_bound"`, plus
  `bind_runtimes = ["evm", ...]` and `bind_min_assurance = "A2"`. A participant with
  `binding = "to_be_bound"` yields a late-bound slot in the slot binding-topology;
  one without is `fixed`. (`bind_*` fields require `binding = "to_be_bound"`;
  `to_be_bound` requires `bind_runtimes` and an `org`.)

### `allow "OrgA" with "OrgB"` [`{ "OrgA" as "roleA"; "OrgB" as "roleB" }`]
Optional org-pair topology policy: permits two organizations to coordinate, with an
optional per-org role constraint block. Every pair of organizations that co-occurs
in a capability must be permitted by some `allow` (see [SECURITY_PASS.md](../testing/SECURITY_PASS.md)).

### `input NAME : TYPE`
A typed input. The **recognized** value-model types — those with defined validation
and lowering semantics (see [VALUE_MODEL.md](VALUE_MODEL.md)) — are `string`,
`party`, `money`, `decimal`, `currency`, `evidence` (plus the integer/time aliases).

The type vocabulary is **intentionally open**: the parser accepts any bare type name
(`TYPE` must be present and non-empty). An *unrecognized* type is stored verbatim and
validated generically (numeric-vs-string) — it carries **no** type-specific
semantics and is **not** part of the governed value model. Authors should use the
recognized types; tightening to a closed, parser-enforced set is a deferred
language-design decision (it would be a breaking change to the deliberately open
model). The conformance suite pins both: the recognized types translate
(`accepted/core.neu`, `accepted/participants.neu`) and an unrecognized type is
accepted as an open extension (`accepted/extension_type.neu`).

The `evidence` type carries an **attested observation** — a governed **non-numeric**
(string-like) value ([VALUE_MODEL.md](VALUE_MODEL.md)). Declaring `input NAME :
evidence` is only half the surface: an accompanying **`attest NAME { … }`** policy
block (below) binds the M-of-N attestation requirement to that input. Because
`evidence` is non-numeric it **cannot** be a `when` guard operand (guards are
numeric-only — see `debit`/`credit`); an unattested claim is kept from posting
effects by the **attestation policy + backend-generated quorum/acceptance
machinery**, not by a `when` comparison on the evidence value.

### `compute NAME = EXPR`
A computed value over previously declared inputs/computes. Arithmetic expression
(`+ - * /`, integer/decimal). Referenced names must be declared above.

### `attest NAME { … }`
Binds an **M-of-N oracle attestation policy** to a declared `evidence` input (M5
oracle S1, ). `NAME` must reference an `input` of type `evidence` — a compute, a
non-evidence input, or an undeclared name is rejected. Fields:

- `quorum = M` — the threshold M (a bare positive integer; **required** — a missing
  or non-positive quorum is rejected).
- `observer_set = "…"`, `observer_role = "…"` — the observer-set *reference* / role.
  The concrete N and observer members are **binding-level** (), never in source.
- `canonicalization = "…"` (e.g. `"exact"`), `tolerance = "…"` — how observed claims
  reduce to a canonical value.
- `assurance = "…"`, `independence = "…"` — the observer assurance / independence
  posture (feeds the security surface).
- `timeout = "…"` (ISO-8601 duration, e.g. `"PT24H"`), `fallback = "…"` (e.g.
  `"abort"`) — liveness bound + on-timeout behavior.

All non-`quorum` values are string literals (not `%references`); an unknown field is
rejected. The policy lowers to the capability-spec `attestations` section (frontend
and the IR `AttestOp` verifier reject the same shapes via the shared contract
validator) and raises the `attestation:quorum` target-support requirement — a target
that cannot honor the quorum **fails closed** (no artifact written), never rendering
as if unattested.

### `debit NAME { … }` / `credit NAME { … }`
A value-moving ledger leg. All six fields are **required** on every leg:
`ledger`, `owner`, `party`, `amount`, `currency`, `idempotency_key`. The optional
`participant = "Name"` binds the leg to a declared participant (its authorization
actor; checked by the Capability Security Pass).

Optional **conditional guard** (M5, ): `when = <predicate>` makes the leg post
**iff** the predicate holds. A predicate is a single **comparison** `<lhs> <op>
<rhs>` with `op` one of `< <= > >= == !=` over NUMERIC (`money`/`decimal`) operands.
The comparison is a guard-only construct — **not a value**: it is valid only at the
top of a `when`, never as a `compute` value or arithmetic operand (there is no
Boolean value type). It lowers to `if (<p>) { … }` (Solidity) / `IF <p> THEN … END
IF` (PL/pgSQL). See [EXPRESSION_MODEL.md](EXPRESSION_MODEL.md).

### `assert balanced`
Asserts the balanced invariant. A value-moving procedure asserting balance must have
≥1 debit and ≥1 credit whose value multisets match. The invariant is **guard-aware**
(M5, ): the multiset is keyed on `(guard, amount, currency)`, so a guarded leg
balances only against a counterpart carrying the **identical** `when` guard (an
unguarded leg has the empty guard). A one-sided guard — or `when C` "balanced" by
`when ¬C` — is **refused** with a source-linked `[kernel.balance.unbalanced]` (exit
4), never compiled. This accepts exactly the identical-guard-pairing shape (the only
statically provable one); richer guarded-balance proofs are future work.

## Source-level non-goals (must remain rejected)

The following are **not** accepted source syntax. They are rejected by the parser
(not silently ignored), and the conformance suite pins this:

- `capability { … }`, `topology { … }`, `flow { … }`, `security { … }`, and inline
  `binding_manifest { … }` blocks. Capability identity, topology, flows, the
  security report, and Binding Manifests are **compiler-owned artifacts / reviewed
  inputs**, not authored in source. (See `examples/binding-manifests/` and the slot
  binding-topology, both *generated*/*reviewed*, never source.)

## Lowering boundary (informative)

Source lowers to the textual `neutrino` MLIR dialect via the C++ front-end; the IR
and its determinism are a separate contract ([COMPATIBILITY.md](../process/COMPATIBILITY.md) →
"Textual `neutrino` MLIR"). Readers do **not** need to reverse-engineer MLIR: source
order is preserved; `%references` become SSA operands (an undeclared reference is
invalid IR, not a lint); `assert balanced` is a verifier rule. Generated artifacts
(slot/solidity/postgres/capability/coverage/security) are downstream of the IR and
are byte-stable for fixed source.

## Current (M5) vs future language candidates

**Accepted now (this spec):** procedures/agreements, trigger, version, participants
+ roles/orgs/late-binding, `allow` policy, typed inputs (incl. `evidence`), compute,
**`attest` attestation policies** (M5 oracle, ), debit/credit, **conditional
`when` guards + guard-aware `assert balanced`** (M5, /).

**Future candidates — NOT in the language yet** (tracked separately; must not be
authored as source until accepted by a language-design issue):

- **State machines / lifecycle** (L2) — no explicit state/transition construct.
- **External observation / receipts / runtime evidence** — network/agents-owned.
- **Protocol-native payment syntax** (ISO 20022 / SWIFT `pacs.*`) — lower-layer /
  domain-dialect / translation-map concerns ([DOMAIN_DIALECT.md](../domains/DOMAIN_DIALECT.md),
  [LOWER_LAYER.md](../domains/LOWER_LAYER.md)), not core `.neu`.
- **Escrow-like state containers** (release/refund transitions) — depend on L2.

The M3 **language maturity boundary** decision record — these buckets in full, the
domain/lower-layer routing, the per-shape tracking discipline, and a release-note-ready
guarantee paragraph — is [`LANGUAGE_BOUNDARY.md`](LANGUAGE_BOUNDARY.md). Those future shapes
are additionally pinned as future-facing-keyword negatives by self-test `[57]`.

## Conformance suite

- `test/conformance/accepted/*.neu` — minimal fixtures exercising the accepted
  constructs; each must `neutrino-translate` cleanly.
- `test/conformance/rejected/*.neu` — pseudo-syntax that must be rejected.
- Self-test `[56]` runs both; the frontend negatives `[3b]` and the
  example-grammar drift guard `[37]` pin diagnostics and keep the editor grammar in
  sync with `examples/`.
