# Verification Hardening

**Status:** Phase 16. Spec: [`BACKEND_MATURITY_SPEC.md`](../backends/BACKEND_MATURITY_SPEC.md).
Methodology companion: an internal design record.

Beyond happy-path scenarios and cross-backend equivalence, two low/mid-cost layers
raise confidence in the coordination semantics. Both are deterministic, need no new
heavy dependencies, and run in the self-test and `make acceptance`.

## Mutation testing — `scripts/mutation_test.py` (`make mutation`, self-test `[17]`)

Deliberately breaks coordination invariants in the `.neu` source and asserts
the **frontend or verifier catches** each. A surviving *critical* mutant is a
verifier gap (non-zero exit).

| Mutation | Breaks | Caught by | Class |
|----------|--------|-----------|-------|
| `drop_credit` | balance (debit with no credit) | verifier/frontend | critical |
| `undeclared_ref` | SSA integrity (operand references a value never declared) | frontend | critical |
| `duplicate_input` | name uniqueness | frontend | critical |
| `drop_assert_balanced` | balance assertion on a value-moving procedure | frontend | critical |
| `alter_compute_expr` | a value inside a compute expression | **nothing static** | expected survivor |

`alter_compute_expr` is the **negative control**: a compute expression's template
is opaque to the verifier (lowered, not evaluated), so a wrong constant produces
valid IR. It is caught downstream by `neutrino-equiv` / the backends, not by static
verification. It surviving proves the harness distinguishes caught from survived
and documents exactly where static guarantees end. (Score is `caught/applied`;
`alter_compute_expr` is skipped — `applied:false` — for procedures with no compute.)

## Property-based testing — `scripts/property_test.py` (`make property`, self-test `[18]`)

Generates seeded-random valid scenarios (default n=12, seed 1337) within
value-model bounds and asserts properties on the reference `neutrino-equiv`
computes:

- **balance conservation** — net ledger sums to zero for *every* input. A real
  invariant: a balanced procedure's debit/credit legs move the same
  (amount, currency), so the net is zero regardless of input values.
- **reference well-formed** — `reference.ok` for every input.
- **determinism** — identical input ⇒ byte-identical reference (run twice with
  `SOURCE_DATE_EPOCH` pinned).

equiv is run **reference-only**: the subprocess PATH is restricted so the Solidity
/ PostgreSQL backend toolchains are not found and skip (`--allow-skips`); only the
in-process reference is computed, keeping the harness fast (~2s for 12 cases) and
independent of `forge`/`docker`.

## Where this sits on the maturity ladder

These are the low/mid-cost verification that begins moving the backends toward
**Level 2 "Verifiable & Secure."** They are *not* formal proof; full Level 2 also
needs broader runtime/security lifecycle evidence. The Capability Security Pass
(see [`SECURITY_PASS.md`](SECURITY_PASS.md)) has landed and is one part of that,
but the honest baseline remains Level 1 "Core Compliant"
(see [`LANGUAGE_LEVELS.md`](../language/LANGUAGE_LEVELS.md)) until that broader evidence exists.
