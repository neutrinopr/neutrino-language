# The canonical capability-spec (`--target=capability-spec`, wire kind `neutrino.capability-spec`)

The **capability-spec** is the single frozen external contract of the M5 architecture
(ADR [D1](../process/M5_DECISIONS_ADR.md)): a canonical JSON serialization of the semantic model that
every renderer — and the agents / network / console consumers — build on, instead of
re-deriving semantics from `ProcedureView`. It is emitted by
`neutrino-gen --target=capability-spec` and lives once, here. (It is a declarative semantic *contract*,
not a procedural to-do list — hence *spec*, the human concept name.)

```sh
# from source ALONE — no --scenario (D2); writes <dir>/capability-spec.json
neutrino-gen --target=capability-spec path/to/source.neu -o <dir>
```

- **Schema:** [`schemas/capability-spec.schema.json`](../schemas/capability-spec.schema.json)
  (`neutrino.capability-spec`, schemaVersion 1; fail-closed, `additionalProperties:false`).
- **Validator:** [`scripts/validators/validate_capability_spec.py`](../../scripts/validators/validate_capability_spec.py)
  (stdlib-only) — validates the capability-spec **independently of any backend**.

## Naming: capability-spec is the wire identity ()

The translator emits a compiled **capability-spec** — the frozen declarative semantic contract.
An earlier draft named this artifact with an orchestration-flavored term; that term denotes a
**network/runtime orchestration** concept, not a translator artifact
(neutrino- boundary decision), so  hard-cut it to `capability-spec` across the
wire kind, file, schema, CLI target, and identity fields **at the public boundary**. The
current tokens are:

| Surface | Token (since ) |
| --- | --- |
| wire `kind` | `neutrino.capability-spec` |
| schema `$id` | `.../capability-spec/v1` |
| artifact file | `capability-spec.json` |
| committed path | `generated/capability-spec/` |
| emit target | `--target=capability-spec` |
| ingest flag | `--from-spec` |
| whole-artifact digest | `identity.specHash` |
| version / source-map path | `specVersion` / `sourceMap[].specPath` |
| diagnostic code family | `spec.*` |
| validator | `validate_capability_spec.py` |

**Compatibility.** This was a **pre-v0.4.0 hard rename**, not a deprecated alias: the earlier
surfaces were removed outright, and because the wire `kind` is inside the `capabilityHash`
preimage, **every committed capability-spec / view / slot / test-realization was regenerated**
and its identity hashes changed. Downstream repos (build-tools packaging, network admission)
must re-ingest against the current tokens — tracked in the follow-up issues linked from .
`capabilityHashOf` / `capabilityHash` keep their names (the capability identity was always
correctly named).

## Why scenario-free

A scenario is a *test input*, not part of what a capability *means* (ADR [D2](../process/M5_DECISIONS_ADR.md)):
the capability-spec is the capability's meaning, so it is generated from source alone. `--target=capability-spec`
selects the procedure from the module directly (**last declaration wins**, matching
`findProcedure`) and never loads or validates a scenario. A source with multiple procedures
therefore specs only the last one today — the samples are single-procedure; multi-procedure
planning is a future extension. This is what lets the test-realization split (WP2/) re-hash a
scenario without re-hashing the capability.

## Gating (why the capability-spec is non-gated)

`--target=capability-spec` is **not** security-gated — a deliberate decision. The `views` target *is*
gated ("an agent must not receive narrowed views for a capability the security pass already
knows is invalid") because it is a lowered, agent-facing *implementation* contract. The capability-spec is
the opposite: the **pre-render semantic contract that is itself the subject of the security
analysis**. Gating it would make an insecure capability's capability-spec unobtainable — exactly as gating
`security`/`capability` would prevent diagnosing the violation — so the capability-spec follows the
**analysis-target precedent, not `views`**. Capability *meaning* exists independent of admission
(D2 artifact families), so a capability-spec is emitted regardless of the security verdict.

**Consumers must consult the security report / admission before treating a capability-spec as
actionable.** A valid, hash-stable capability-spec asserts what the capability *means*, not that it is
*admissible*.

## What the capability-spec contains

| Section | Content |
| --- | --- |
| `identity` | `capabilityHash` (over the semantic content) + `specHash` (over the whole canonical spec). Both lowercase-hex sha256. |
| `inputs` | typed inputs — `name`, `type`, and the `` value `category`. |
| `computes` | each compute's `expr`, resolved `category`, `deps`, and the **typed `` expression AST** (`ast`), so no renderer re-parses. |
| `effects` | debit/credit legs with `ref`/`literal` operands (party/amount/currency/idempotencyKey). |
| `invariants` | e.g. `balanced`. |
| `participants` / `topology` | declared participants + binding policy; allowed org-pair coordination policy. |
| `lifecycle` | the **one canonical coordination state machine** (states, transitions, `instanceKey`, terminal-state kinds) the slot lifecycle and the on-chain surface both project from. An attestation policy inserts an M-of-N **quorum gate** (`QUORUM_PENDING`/`QUORUM_MET`/`QUORUM_TIMEOUT` + the declared `abort`/`escalate` timeout fallback; oracle S3, ) — the post departs only from `QUORUM_MET`, so a leg never fires on `< M`. |
| `targetRequirements` | **per-requirement records** — each a `feature` (e.g. `value_category:money`, `value_extension:temporal`, `effect:debit`, `invariant:balanced`), the originating `primitive`, its `source` span, a `requirement` level (`required`/`optional`), and a `fallback` — a renderer/profile is matched against **before** rendering (WP4/, AD3). Temporal declarations remain extension-typed but use the narrow `value_extension:temporal`; arbitrary extensions remain the fail-closed `value_category:extension`. Matching is set-intersection over `feature`; the source span lets a legality diagnostic name the exact line. Today all requirements are `required` with no `fallback` (both forward space). |
| `sourceMap` | DSL → spec-path map with the **1-based source span per construct** (from the frontend's `FileLineColLoc`/`FusedLoc`; `source` is null only when an op has no file location). Column is 1 — the lexer is line-oriented. |

The normalized authorization topology accepts at most **8 participants**. This
deliberate fail-closed bound is checked before canonical graph labeling on both
the source and `--from-spec` paths; larger declarations are rejected with the
stable `coordination plan: authorization participant count ... exceeds canonical
topology limit 8` diagnostic. The bound prevents a large symmetric actor set
from causing unbounded canonical-labeling work.

## Determinism, canonicalization, and hashes

The capability-spec is **byte-reproducible**: no timestamps or git sha, keys sorted (llvm json), so
`capability-spec.json` is fixture-comparable and regenerated byte-identically in CI. Canonicalization has
two levels:

- **in-block field reordering** (operands are keyed, not positional; a debit's fields are a map)
  that does **not** move a statement's line → a **byte-identical** spec;
- **reformatting that shifts lines** (blank lines, etc.) → the semantic **`capabilityHash` is
  stable**, while `specHash` (the whole-artifact digest) tracks the shift.

Hashes are over the **compact** canonical form — `json.dumps(sort_keys=True,
separators=(",",":"), ensure_ascii=False)`, which the C++ emitter's `llvm::json` compact print
(sorted keys, **raw UTF-8**) matches byte-for-byte, so the stdlib validator recomputes them
exactly. `ensure_ascii=False` is load-bearing: a non-ASCII literal would otherwise be `\u`-escaped
by the validator and diverge from the emitter (a false tamper alarm). Control characters use the
JSON short escapes on both sides.

- `capabilityHash = sha256(compact(spec \ identity \ sourceMap \ targetRequirements \ kind \ schemaVersion))`
  — the **pure semantic identity**. It excludes the two **derived, line-bearing projections**
  (`sourceMap`, `targetRequirements`) *and* the **envelope discriminators** (`kind`,
  `schemaVersion`, ): a `kind` is a constant document tag and `schemaVersion` is a derived flag
  (its guard semantics are already hashed via the effects' `when`), so neither is capability
  *meaning*. It is therefore insensitive to source formatting **and to any future envelope rename**
  (`kind`/`schemaVersion`/`$id` bump never moves it — so the corpus of derived artifacts that
  cross-check it never re-churns), but changes on **any identity-bearing rename** (the
  rename-negative fixture proves both hashes change; the `[76]` envelope-invariance check proves an
  envelope-only change moves `specHash` but not `capabilityHash`);
- `specHash = sha256(compact(spec \ identity.specHash))` — the whole-artifact digest (moves with
  source lines **and** with the envelope discriminators).

The `capabilityHash` is **scenario-independent** by construction (a pure function of the
source-derived view). The concrete test cases a scenario produces live in the separate
[test-realization companion](../testing/TEST_REALIZATION.md) (`--target=test-realization`), which
*references* `capabilityHash` but is never hashed into it — so changing only a scenario/test
never moves the capability's identity (M5 WP2, ).

## Beyond-schema invariants (validator)

The schema cannot express these; the validator enforces them fail-closed with stable `spec.*`
diagnostic codes (shared taxonomy direction, ), and a self-test asserts the validator's
field set / const / enums / hash pattern stay aligned with the schema:

- both hashes recompute (tamper / rename caught: `spec.hash_mismatch`);
- every compute `dep` and every `ref` operand resolves to a declared input/compute
  (`spec.unresolved_dep` / `spec.unresolved_ref`);
- every non-null effect `participant` resolves to a declared participant;
- every lifecycle transition `from`/`to`, the `initialState`, and each `terminalStates` value
  resolve to a declared state; a `terminalKind` implies `terminal:true`;
- **no dead-end sinks** — every non-terminal state has at least one outgoing transition, so the
  executable machine can always reach a terminal (the exit-completeness rule the  kernel
  verifier will enforce). `CLOSE` is therefore reachable from both `COMMITTED` and `COMPENSATED`;
- every array section — top-level (`inputs`, `computes`, …) **and nested**
  (`topology.allowedOrgPairs`, `lifecycle.states`/`transitions`, transition `effects`/`guards`,
  participant `capabilities`/`bindRuntimes`, `targetRequirements.unsupportedConstructs`,
  `instanceKey.fields`, …) — is type-checked, so a non-array section cannot pass as hash-valid.
  The validator fully mirrors the schema (CI runs the stdlib script, not a JSON-Schema library).

## Lifecycle projection

The acceptance is that the slot lifecycle and the on-chain surface **project from one
canonical machine**. Self-test `[76]` proves it on `core_sponsored_offer`: the spec's
lifecycle transitions equal the slot `operations.json` operations, the spec's posting
transition(s) equal the slot's `compensable` operations, and the spec's single posting
transition is the on-chain contract's state-changing `execute` entrypoint.

## Scope today vs. forward primitives

The lifecycle is the fixed `OPEN..CLOSE` machine the slot already emits; the DSL has no
author-defined state machines yet (language level L2). Per ADR **D5 / addendum AD2** (no
speculative primitives without a gate sample), the capability-spec **schema reserves** forward space —
`reserve`/`consume`/`release` effects, participant/deadline/sequence guards (quorum reserved),
per-transition chained evidence, `noop_on_identical` idempotency, `contested` terminal — but
the **emitter produces only what today's samples contain**. Those primitives are emitted when a
gate sample and the DSL syntax for them land.

## Where it runs

- **fast tier** (`[fast/9]`) — every committed sample capability-spec validates; a tampered one fails
  closed. No build.
- **full tier** (`[76]`, `make test` → release gate) — schema alignment; every sample capability-spec
  **regenerates byte-identically from source alone** and validates; scenario-required targets
  fail closed without `--scenario`; canonicalization stability; rename changes both hashes; the
  lifecycle projection above.

See ADR [D1/D2/D6/D11](../process/M5_DECISIONS_ADR.md) and the addendum [AD2](../process/M5_DECISIONS_ADR_ADDENDUM.md).
Consumed next by WP3 slot migration () and WP4 target profiles ().
