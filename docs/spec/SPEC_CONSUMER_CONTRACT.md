# Capability-spec consumer contract (agents / network / console)

**Audience:** the rails that consume translator output after M5 — the **agents** control plane,
**neutrino-network**, and the **console**. This is the *consumer-facing* view of the canonical
capability-spec: what it is, how to obtain it, which fields are stable to build on, and how each
rail uses it. The **normative spec** is [CAPABILITY_SPEC.md](CAPABILITY_SPEC.md); the
capability-spec's JSON **shape** is fixed by [`docs/schemas`](../schemas) and enforced by
`scripts/validators/validate_capability_spec.py`. This page does not restate the schema — it states the
*contract* consumers may rely on.

> **Naming (; wire rename ):** the translator emits a compiled **capability-spec**; "spec"
> is the network/runtime concept.  hard-cut (pre-v0.4.0) the wire tokens to
> `neutrino.capability-spec`, `capability-spec.json`, `capability-spec/v1`,
> `--target=capability-spec`, `specHash`, and the `spec.*` diagnostic family; `capabilityHash` keeps
> its name. A bare `spec` in a code font below is always one of those current wire tokens. See
> [CAPABILITY_SPEC.md § Naming](CAPABILITY_SPEC.md#naming-capability-spec-is-the-wire-identity-279).

## The one contract: the canonical capability-spec

After M5, every backend renderer (Solidity contract, PostgreSQL procedure, slot) is a **consumer
of the canonical capability-spec** (`neutrino.capability-spec`, schemaVersion 1) — not of `ProcedureView` or
raw scenario semantics (WP3/, WP5/, WP6/; the milestone-wide sweep is self-test
`[87]`). So the capability-spec is the **single external contract** across the toolchain and the rails: if a
rail agrees with the capability-spec, it agrees with every backend.

Produce it **scenario-free** from source:

```sh
neutrino-gen --target=capability-spec <source.neu|.mlir> -o <dir>   # writes <dir>/capability-spec.json (+ manifest/diagnostics)
```

It is also **re-entrant** — a rail can render an artifact *from* a capability-spec file it was handed, with no
source or scenario, and the renderer re-types the ingested expressions (so a tampered spec is
rejected, not trusted):

```sh
neutrino-gen --target=solidity|postgres --from-spec <capability-spec.json> -o <dir>
```

## What a consumer may rely on

| Section | Contract |
|---|---|
| `identity.capabilityHash` | Stable semantic identity — a pure function of the semantic core (excludes `sourceMap` + `targetRequirements`). **Scenario-independent** and insensitive to source formatting; changes only on a semantic change. Use it to key/pin a capability. |
| `identity.specHash` | Whole-spec digest; moves with any spec change (incl. formatting-driven `sourceMap`/`targetRequirements`). Use it to detect *any* drift. |
| `procedure`, `trigger` | Capability identity names. |
| `inputs`, `computes`, `effects`, `invariants` | The semantic core: typed inputs (name/type/category), serialized compute ASTs, ledger effects (debit/credit + operands), and declared invariants (e.g. `balanced`). |
| `participants`, `topology`, `binding` | Who coordinates, the allowed org pairs/roles, and late-binding policy. |
| `lifecycle` | **The one canonical coordination state machine** (`INITIAL..CLOSED`, `terminalStates`). Slot operations project from it. See the layer note below. |
| `targetRequirements` | Per-requirement `feature`/`primitive`/`source`/`requirement`/`fallback` records matched against a target profile **before** rendering (the legality gate, WP4/). |
| `sourceMap` | 1-based source span per construct (diagnostics/traceability). Derived; not hashed into `capabilityHash`. |

**Hash rule of thumb:** key on `capabilityHash` for *identity*, watch `specHash` for *any* change.
A scenario/test change never moves `capabilityHash`.

## How each rail consumes it

- **agents.** The spec is the capability contract carried in the artifact bundle; validate it with
  `scripts/validators/validate_capability_spec.py` and gate claims with `scripts/gates/check_capability_claims.py`,
  which now **grounds invariant honesty in the capability-spec** (`--spec`): a model must Verify every
  invariant the capability-spec structurally declares, not merely those one scenario happens to prove ().
- **network.** The spec's **lifecycle** machine projects to the slot operation set
  (`OPEN..CLOSE`); `scripts/rails/cross_rail_dry_run.py` confirms the slot bundle **derives from the
  spec** (same `procedure`/`trigger`, and every spec input/compute/effect-ledger present in the
  slot capability). The identity handoff to Fabric is `capabilityHash → EnvelopeHeader.schema_hash`
  via `capability.lock` (unchanged; pinned by the dry run's bridge stage).
- **console.** Reference for the EVM coordination slot. **Layer note:** the capability-spec's 8-state
  lifecycle is the **coordination-layer** machine; the on-chain (Solidity) surface is a *fixed
  2-state coordination projection* (`Status{None, Reconciled}`), intentionally not derived from the
  full machine (recorded in [M5_DECISIONS_ADR_ADDENDUM.md](../process/M5_DECISIONS_ADR_ADDENDUM.md) and
  [BACKEND_GENERATORS.md](../backends/BACKEND_GENERATORS.md); deriving it is tracked in
  [](internal-tracker)).

## Guarantees a consumer inherits

- **Schema-valid, byte- and hash-stable, backend-independent** — the same spec regenerates
  byte-identically from source alone and validates without any backend (WP1d/).
- **Legality is enforced before rendering** — `neutrino-gen --profile=<target-profile.json>` fails
  closed (`legality.unsupported_feature`, exit `6`) on an unsupported required feature, so no
  artifact is emitted for a capability a target cannot legally realize (WP4/).
- **Artifacts structurally reflect the capability-spec** — `neutrino-equiv` runs **spec-vs-artifact structural
  checks** for Solidity + PostgreSQL (toolchain-free): every spec input/compute/effect-ledger must
  appear in the rendered artifact, else `equivalence.spec_artifact_mismatch` (self-test `[90]`).
  Scope of this check (don't over-read "structurally projects"): it is **presence-based** (a capability-spec
  name *appears* in the artifact text — not its structural position, so a name could in principle
  match inside a comment) and **one-directional** (spec → artifact — it catches a *dropped or
  renamed* spec element, but not a renderer emitting *extra* semantics with no spec source). The
  stronger properties — exact structure and runtime behavior — are covered by the byte-identical
  fixtures and the execution-based equivalence, not by this guard.
- **No renderer backsliding** — the milestone-wide sweep `[87]` pins that every migrated renderer
  is `View.h`-free and never re-parses expression text.

## Renderer surface: fully spec-derived; one spec feature still tracked

Both backend **test harnesses** are now single-sourced onto the capability-spec — PostgreSQL
(`generatePostgresDbTestFromSpec`, WP5/) and Solidity
(`generateSolidityTestFromSpec`, ) — so **the entire Solidity and PostgreSQL renderer surface
(contract/procedure + harness) is `View.h`-free** and derives its structure from the canonical
spec; only concrete values come from the folded test-realization (). Renderer APIs accept
*spec + test-realization*; the target `emit*` entries still take `ProcedureView` because they are
the registry `EmitFn` and call `realize`/`capabilitySpecJson`.

Still tracked in [](internal-tracker): the on-chain
**`lifecycleProjection`** (so the EVM control structure *derives* from the canonical machine rather
than being a hand-authored fixed projection), and the open question of whether `GenViews` should
converge to `View.h`-free like the backends did. Neither affects the capability-spec *contract* consumers rely
on above.

## References

- [CAPABILITY_SPEC.md](CAPABILITY_SPEC.md) — normative spec spec (identity, hashes, sections).
- [TARGET_PROFILES.md](../backends/TARGET_PROFILES.md) — target profiles + the legality gate.
- [BACKEND_GENERATORS.md](../backends/BACKEND_GENERATORS.md) — the migrated renderers + the EVM lifecycle note.
- [M5_DECISIONS_ADR_ADDENDUM.md](../process/M5_DECISIONS_ADR_ADDENDUM.md) — AD1–AD4 + the coordination-layer lifecycle note.
