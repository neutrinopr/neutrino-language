# Normalized trace-equivalence (`neutrino-equiv`)

The differential harness [`neutrino-equiv`](../../tools/neutrino-equiv/neutrino-equiv.cpp) proves each
supported realization preserves **observable agreement meaning** — not artifact bytes. It extends the
existing reference recompute + backend run with a **normalized trace-equivalence** check against the
[deterministic reference evaluator](../spec/COORDINATION_EVALUATOR.md) (the semantic oracle), gated
**within each realization's [declared semantic profile](TARGET_PROFILES.md)**.

## The equivalence hierarchy

1. **Semantic equivalence** — a realization's normalized observation trace vs the reference evaluator's
   trace. The comparator lives in
   [`TraceEquivalence.h`](../../include/Neutrino/TraceEquivalence.h): each realization is projected to a
   canonical `ObservedTrace` (outcome, computed values, the ordered movement-event choreography, net
   ledger by ledger, terminal, replay set), and `compareTraces` reports the **first divergence with
   coordinates** (`field`, `locator`, reference vs realization values).
2. **Observable-trace equivalence** — the same normalized observations compared across realizations
   *within a common profile*. `neutrino-equiv` compares the reference evaluator's trace against its own
   independent recompute (toolchain-free), and — when the Foundry/psql toolchains are present — the
   rendered backends assert the same events + net ledger + terminal.
3. **Resource conformance** — the [semantic profile](TARGET_PROFILES.md) limits are **bounded and
   enforced** (via `checkPlanLegality`), *not* required numerically equal across targets.

## Within the declared profile — refuse, don't compare misleadingly

Before comparing a realization, `neutrino-equiv` runs the  legality gate for that backend's
built-in profile. A coordination plan illegal for a backend (e.g. a deep-expression coordination plan exceeding
Solidity's gas-bounded `maxExpressionDepth`, or a `time:explicit_input` coordination plan Solidity does not realize)
is **REFUSED** for that backend — recorded with its `profileId`/`profileVersion` — and a refusal does
**not** fail equivalence. Only an actual observable divergence, or an empty trace, does.

## Non-vacuous + fail-closed

- `--tamper=<kind>` deliberately breaks the candidate trace — `drop_effect`, `alter_amount`,
  `reorder_obs`, `wrong_terminal`, `replay_omission`, `partial_commit`, `alter_computed`,
  `alter_outcome` (one per compared field, so no field is trusted without a negative that proves its
  check bites — `alter_computed` covers the launder-via-derived-value vector) — and the gate MUST
  detect the divergence. A tamper that finds nothing to break, or an unknown tamper kind, **fails
  closed**.
- The report's `traceEquivalence` object carries `ok`, `executedCases`, `observationCount`, the
  per-backend profile identities, and the first `divergence` coordinates.
- The gate script
  [`test/ir/equiv/check_trace_equivalence.py`](../../test/ir/equiv/check_trace_equivalence.py) enforces
  **non-vacuous floors**: every committed sample trace-equivalent (`executedCases >= 1`, `>= 5`
  samples), a profile-incompatible coordination plan refused (not compared), and **all eight** tamper
  classes detected — so a zero/empty/skipped run fails closed rather than passing silently.

## Diagnostics

`equivalence.trace_divergence` (a realization's normalized trace diverged from the reference),
`equivalence.profile_incompatible` (a realization refused — warning, not compared), and
`equivalence.no_cases` (empty trace / zero executed cases — fail-closed). These complement the existing
`equivalence.{reference_mismatch,backend_failed,backend_skipped,spec_artifact_mismatch}` codes.

## Complementary to the byte goldens

The backend byte-goldens remain the artifact-fidelity check; this gate is the **semantic** one —
source/artifact byte equality is never used as a proof of observable agreement. Tests:
[`test/ir/equiv/trace_equivalence.test`](../../test/ir/equiv/trace_equivalence.test) (the gate + a
fail-closed self-test) and `unittests/TraceEquivalenceTest.cpp` (the comparator + every tamper class).
