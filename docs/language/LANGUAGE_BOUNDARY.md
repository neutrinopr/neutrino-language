# M3 Language Maturity Boundary

**Status:** decision record (M3). Strategy: internal-tracker/neutrino- ·
Issue: internal-tracker
**Language spec:** [`NEU_LANGUAGE_SPEC.md`](NEU_LANGUAGE_SPEC.md) (the normative accepted
grammar) and [`LANGUAGE_LEVELS.md`](LANGUAGE_LEVELS.md) (the levels this boundary draws lines
through).

The M2/M3 example domains intentionally gesture at future-facing shapes — supply-chain
observation, escrow lifecycle, protocol-native payment terms. Before release messaging goes
further, the translator needs **one explicit record** of what the core language accepts
*today*, what is handled as **domain/lower-layer mapping** (reviewed artifacts, not core
source), and what is **future source syntax** that is deliberately rejected until it is
designed and tracked. This document is that record, and it is **enforced** (not just
asserted) — see [Enforcement](#enforcement-fail-closed).

The core boundary is a feature, not a limitation: a small, verifiable core keeps every
shipped capability replay-safe and lets future syntax fork in explicitly
([`VERSIONING.md`](../process/VERSIONING.md)) rather than mutate semantics under deployed evidence.

## 1. Accepted now — core `.neu` source

The frontend (`neutrino-translate`) accepts a **fixed statement vocabulary**; these are the
only source constructs, and they cover language levels L1, L3, L4, L5
([`LANGUAGE_LEVELS.md`](LANGUAGE_LEVELS.md)):

| Construct | Statement(s) | Level |
|-----------|--------------|-------|
| Agreement / coordination | `procedure` (or `agreement NAME between A and B { … }` — sugar that desugars to a `procedure` with two declared participants, self-test `[29]`), `trigger`, ledger entries | L1 |
| Capability version | `version "MAJOR.MINOR.PATCH"` | — ([`VERSIONING.md`](../process/VERSIONING.md)) |
| Inputs & computed values | `input … : <type>`, `compute …` | L4 (typed values) |
| Participants & topology | `participant …`, `party`-typed inputs/operands | L3 |
| Per-pair role policy | `allow …` | L3/L8 boundary |
| Value movement | `debit …`, `credit …` | L4 |
| Atomic settlement | `assert balanced` | L5 |

Security/binding policy travels as **separate reviewed artifacts** (security pass, binding
policy/manifest), not as new source statements — see
[`SECURITY_PASS.md`](../testing/SECURITY_PASS.md), [`BINDING_POLICY.md`](../binding/BINDING_POLICY.md).

L2 (state machines) is **not** in this list — it is future (below).

## 2. Domain / lower-layer mapping — NOT core source syntax

Some intent that *looks* like it wants new keywords is, by design, expressed through
**explicit reviewed, hash-pinned artifacts** — never written as `.neu` statements and never
hidden in adapter code:

| Shape | Routed through | Owner / contract |
|-------|----------------|------------------|
| Protocol-native payment terms (ISO 20022 / SWIFT `pacs.*`) | `neutrino.translation-map` ([`LOWER_LAYER.md`](../domains/LOWER_LAYER.md), `examples/translation-maps/iso20022_interbank.map.json`) | translator owns the reviewed map + static conformance fixtures; `neutrino-network` owns runtime execution |
| Domain business vocabulary (sponsored finance, etc.) | `neutrino.domain-dialect` ([`DOMAIN_DIALECT.md`](../domains/DOMAIN_DIALECT.md)) — **expands to** core `.neu` | fail-closed; a dialect may reference/expand core constructs but must **not redefine** them ([`DIALECT_PROMOTION.md`](../domains/DIALECT_PROMOTION.md)) |

So `pacs.009` is a *lower-layer map entry*, not a `.neu` keyword; "sponsored installment" is a
*dialect expansion*, not core grammar. Writing either as a procedure statement is rejected
(§Enforcement) — the boundary points the author at the right tool.

## 3. Future source syntax — rejected until designed and tracked

These shapes are **not** accepted as core source today. They are rejected at the frontend,
and none of them ships as a release `.neu` example. Each must be designed and **tracked in
its own issue before any implementation** (this issue does not implement them — see the
non-goals on ):

| Future shape | Why deferred | Path |
|--------------|--------------|------|
| State machines / lifecycle / transitions | L2 is future in [`LANGUAGE_LEVELS.md`](LANGUAGE_LEVELS.md); no `state`/`transition` grammar | new issue before implementation |
| Escrow-like state containers + release/refund transitions | requires L2 state/transition semantics first | new issue (depends on L2) |
| External observation / evidence verification **as source** | runtime evidence/admission stays in `neutrino-network`/`neutrino-build-tools`, not the core translator ( non-goal) | network/agents lane |
| Protocol-native payment **source syntax** | handled as a lower-layer map today (§2); promoting it to core grammar is a separate decision | new issue (after map experience), cf.  |

A repeated domain concept graduates into core grammar only through the **promotion gate** in
[`DIALECT_PROMOTION.md`](../domains/DIALECT_PROMOTION.md) — never by quietly accepting a new keyword.

## Enforcement (fail-closed)

The boundary is mechanical, not aspirational:

- **Core grammar is a whitelist.** `neutrino-translate` accepts only the §1 statements; any
  other statement is rejected with `unexpected statement: …` (the frontend parser). Future
  pseudo-syntax (`state`/`transition`, `escrow`/`release`, `pacs.008`, `observe …`) therefore
  cannot be silently ignored or half-parsed.
- **Pinned by self-test `[57]`** (`test/run_cpp_tests.sh`): committed negative fixtures
  (`test/neg_state_machine.neu`, `neg_escrow_lifecycle.neu`, `neg_protocol_native.neu`,
  `neg_external_observation.neu`) must each be rejected for the right reason. If a future
  keyword is ever accepted without a deliberate design, this check fails. This complements
  the normative conformance suite (`test/conformance/`, self-test `[56]`) that pins the
  accepted grammar and the block-level rejected forms — see
  [`NEU_LANGUAGE_SPEC.md`](NEU_LANGUAGE_SPEC.md).
- **Dialect / lower-layer paths are themselves fail-closed** — the dialect core-boundary gate
  ([`DIALECT_PROMOTION.md`](../domains/DIALECT_PROMOTION.md)) and the translation-map schema
  ([`LOWER_LAYER.md`](../domains/LOWER_LAYER.md)) reject redefinition of core concepts and unreviewed
  vocabulary.
- **Examples carry no future-facing shapes.** Every `.neu` under `examples/domains/*`
  compiles; the **cataloged release fixtures** in `examples/cross-rail-fixtures.json`
  additionally carry committed generated artifacts
  ([`CROSS_RAIL_FIXTURES.md`](../backends/CROSS_RAIL_FIXTURES.md)), while the remaining domains are
  regression/security fixtures pinned by self-tests (some without a full `generated/` tree).
  Either way, future-facing shapes appear **only** as reviewed lower-layer maps / dialects
  (§2) or as rejection negatives — never as a `.neu` example.

## Guarantee boundary (release-note ready)

> Neutrino `.neu` source compiles **coordination agreements with typed participants, value
> movement, and atomic settlement** (language levels L1, L3–L5). Protocol-native payment
> formats (ISO 20022 / SWIFT `pacs.*`) and domain vocabulary are supported through
> **explicit, reviewed translation-map and domain-dialect artifacts**, not as core source
> syntax. State machines / lifecycle (L2), escrow release/refund transitions, and
> external-observation source syntax are **not** part of the language in this release; the
> compiler rejects such constructs rather than partially accepting them, and any future
> syntax will be introduced under an explicit versioned design.
