# Language Levels & Coverage

**Status:** Phase 15 shipped. Spec: [`BACKEND_MATURITY_SPEC.md`](../backends/BACKEND_MATURITY_SPEC.md).

The Backend Maturity framework defines language levels L1–L10. This document maps
them to concrete `neutrino` semantics and explains how `neutrino-gen
--target=coverage` derives a procedure's coverage and the resulting maturity
ceiling **mechanically** (from the IR), rather than asserting it.

Levels are a **feature matrix, not a strict ladder**: L1–L5 are cumulative
language semantics the translator owns; L6–L10 are distribution/runtime concerns
owned by `neutrino-network` and reported as `networkOwned`, never claimed here.

> **These `L1–L10` language levels are not the realization layers `L1/L2/L3`
> (core/domain/binding).** For the map disambiguating the overlapping `L*` schemes,
> see [`M5_DECISIONS_ADR_ADDENDUM.md` §AD1](../process/M5_DECISIONS_ADR_ADDENDUM.md). Here "L4"
> means **Assets & Value**, never a realization layer.

For the explicit M3 record of **what the core language accepts today** (L1, L3–L5),
what is handled as **domain/lower-layer mapping** rather than core source, and what is
**future source syntax** (L2 state machines, escrow lifecycle, protocol-native and
external-observation terms — rejected, not partially accepted), see
[`LANGUAGE_BOUNDARY.md`](LANGUAGE_BOUNDARY.md).

**ChannelVerificationEarmark stays above L1.** First-class L1 Core IR ops/types for the earmark
(`request_earmark` / `admit_earmark` / `challenge_receipt` / `admission_result`) are **deliberately
deferred** — the concept is expressed by L2/L3 artifacts + the network/agents runtime, and L1 carries
no earmark op. See the decision record [`EARMARK_L1_DECISION.md`](EARMARK_L1_DECISION.md)
().

## Level → `neutrino` semantics

| Level | Name | Detected from the IR (ProcedureView) | Owner |
|-------|------|--------------------------------------|-------|
| L1 | Agreements | a `trigger` and/or ledger entries (it is a coordination agreement) | translator |
| L2 | State Machines | explicit state/transition construct — **not in the current DSL** | translator (future) |
| L3 | Participants | `party`-typed inputs and/or `party` operands on legs (→ `partial`: typed parties, but no roles/permissions yet) | translator |
| L4 | Assets & Value | numeric (`money`/`decimal`) inputs moved by `debit`/`credit` legs | translator |
| L5 | Settlement | `assert_balanced` + ≥1 `debit` + ≥1 `credit` (atomic multi-leg) + reconciliation | translator |
| L6 | Sagas | long-running distributed workflows | network |
| L7 | Compensation | explicit rollback/recovery at runtime | network |
| L8 | Topology | multi-organization networks | network |
| L9 | Capability Discovery | dynamic capability routing | network |
| L10 | Distributed Coordination | full fabric execution | network |

`present` is tri-state: `true`, `false`, or `"partial"` (L3 today).

## Maturity ceiling (derived)

The framework rule: *a backend cannot exceed the maturity implied by its highest
verifiably-supported language level.* `coverage.json` computes the ceiling from:

- the **highest exercised level** (today L5 for both sample domains),
- whether the suite **tests** it (yes — `forge` / docker+psql / equivalence),
- whether it is **formally verified** (no — Phase 16 added property/mutation, not
  theorem-level formal verification).

→ `L ≤ 5 + tests + no formal verification ⇒ Level 1 "Core Compliant"`. Level 2
"Verifiable & Secure" needs stronger lifecycle/runtime evidence beyond the current
translator-local property/mutation hardening. When the DSL gains L2 (state
machines) or any backend stops supporting a level, the coverage — and the reported
ceiling — change automatically rather than by edit.

## Generate

```bash
make coverage
# or:
neutrino-gen --target=coverage --scenario=<scenario.json> <source.neu|.mlir> -o <dir>
# writes <dir>/coverage.json
```

Deterministic and fixture-comparable: committed fixtures live under
`examples/domains/<domain>/generated/coverage/coverage.json`, diffed (and the L5 → Level 1 ceiling
asserted) by self-test check `[16]` for both sample domains.

## Relationship to the capability model

[`CAPABILITY_MODEL.md`](../backends/CAPABILITY_MODEL.md) defines the catalog-derived
v1 backend capability model. It deliberately carries no language-level or
maturity claims. `coverage.json` remains the procedure-grounded language-level
derivation and is the only core-owned surface in this comparison.
