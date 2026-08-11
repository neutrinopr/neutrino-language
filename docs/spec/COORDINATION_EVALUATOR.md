# The coordination evaluator (`--target=coordination-trace`, )

The **coordination evaluator** is the *one* deterministic reference interpreter of a
[coordination plan](../../include/Neutrino/CoordinationPlan.h) (): the **semantic oracle**
every backend realization (Solidity, PostgreSQL, …) is checked against. Given a coordination plan,
an initial state, and one transition input, it produces a normalized, ordered **observation trace**
and the **next state**. It lives in the frozen-contract leaf
([`CoordinationEval.h`](../../include/Neutrino/CoordinationEval.h)) so consumers use it MLIR-free,
and it is exposed as the `coordination-trace` target.

```sh
# realize a coordination for one invocation; writes <dir>/coordination-trace.json
neutrino-gen --target=coordination-trace --scenario=s.json path/to/source.neu -o <dir>
# the same trace, reconstructed from the frozen capability-spec
neutrino-gen --target=coordination-trace --from-spec --scenario=s.json capability-spec.json -o <dir>
```

Because the evaluator runs over the *normalized coordination plan* — the single form the `.neu`,
the direct-MLIR, and the `planFromSpec` reconstruction paths all produce — the three paths reach a
**byte-identical** trace and next state.

## What it models: semantic state transitions — NOT the network session/transcript lifecycle

This evaluator owns exactly the **semantic** state of a coordination and nothing else:

- **Per-account ledger balances** — value moves are netted per **`(ledger, party, currency)`**
  posting identity, not per ledger alone, so two effects against one ledger for different parties or
  currencies stay distinct balances (as a backend whose posting identity is ledger + party/account +
  currency would keep them).
- **Replay / idempotency guard** — the set of workflow-key values already committed, so a re-post is
  a deterministic no-op.
- **Lifecycle status** — the coordination's own terminal status (`""` = open; else the reached
  success/aborted/contested terminal), so an invocation on an already-terminal coordination is
  rejected.

It deliberately does **not** model, own, or admit the **network-owned session/transcript
lifecycle** — the runtime concerns the translator has always held at arm's length (the  boundary,
neutrino-):

- session establishment, connection/channel state, retries, or messaging transcripts;
- real admission / authorization decisions (who may invoke);
- the *collection* of external attestations or oracle evidence;
- wall-clock time.

Those are **inputs** to a transition here, never behaviors of it. Authorization is a given boolean,
attestation decisions are a given map, and **time is an ordinary explicit numeric input** a guard may
compare against — the evaluator never reads an ambient clock, opens a session, or writes a transcript.
The network binds those inputs from the real session; the evaluator only records what it was handed.
This keeps the oracle a pure function of `(coordination plan, state, input)` and keeps runtime
lifecycle ownership where it belongs — outside the translator. The **semantic** lifecycle status
above is distinct from that network session lifecycle: it is the datum the coordination plan's
terminal projection describes, nothing more.

## State, transition input, and the next-state relation

**Initial state** (`EvalState`): the per-`(ledger, party, currency)` `balances` (absent = 0), the
`postedKeys` set, and the lifecycle `status` (`""` = open).

**Transition input** (`TransitionInput`): the concrete invocation — `numeric` inputs (minor units,
including any time inputs), `symbols` (party / currency / the workflow key / strings), the
`attestations` decision map (policy input → accepted?), and the `authorized` boolean.

**Next-state relation.** The evaluator is **total** over the closed vocabulary and **atomic** — every
failure is an explicit, coded refusal taken *before* the single commit, so a refused or replayed
transition returns the input state unchanged. In order:

1. **Authorization** — record it; an unauthorized invocation is refused (`auth.denied`).
2. **Workflow key** — resolve its value from the input; an unresolvable key is refused
   (`key.unresolved`).
3. **Replay** — if the key was already committed (and the obligation is idempotent), emit a `replay`
   no-op and return the success terminal with the state unchanged.
4. **Terminal status** — a new invocation on an already-terminal coordination is refused
   (`state.terminal`) without mutation.
5. **Computes** — fold each compute into the numeric env in declared order. Expression evaluation is
   **checked**: signed overflow refuses `expr.overflow`, division by zero `expr.divide_by_zero`, an
   unbound variable `expr.unbound` — a reference oracle is total, so no arithmetic fault is host/
   compiler-dependent UB (this matches a backend's revert-on-overflow). The same checks guard a
   **guard operand**, since guards evaluate through the same expression evaluator.
6. **Validate effects** — for each effect in coordination-plan order: reject an unknown effect kind
   (`effect.kind`); evaluate its `guard` (a false guard suppresses the leg); enforce its attestation
   gate (a firing gated leg whose policy is not accepted refuses the *whole* transition —
   `attestation.rejected` — since a balanced group cannot drop one leg); resolve its `amount`
   (numeric, non-negative), `party`, and `currency` operands (a malformed identity or an **empty**
   ledger/party/currency posting-identity component is `operand.malformed`, an unresolved ref is
   `operand.unresolved`, a negative amount is `amount.negative`); and stage the signed delta into a
   **copy** of the balances with checked addition (an overflow is `balance.overflow`). **No
   observable state is mutated in this phase.**
7. **Commit** — publish the staged balances, emit the ledger deltas in order, the choreography events,
   and the verified **success terminal**; mark the key posted and set the status to the success
   terminal. This is the only mutation.

**Refusal is not a state transition.** A refused transition returns the input state byte-for-byte
unchanged and appends a `refusal` observation. The observations produced *before* the fault
(`authorization`, any `compute`/`guard`, a rejected `attestation`) remain in the trace — the refusal
is not necessarily the only element — but **no terminal observation is appended**, so the trace never
claims a terminal the state disagrees with. The invariant every trace upholds: **each `terminal`
observation's state equals `nextState.status`** (success on commit; the coordination's existing
terminal on replay; and no terminal observation at all on a refusal, which leaves the status open). A
state that posted a key yet is still open is inconsistent and is refused `state.invalid` rather than
fabricating a success terminal.

## Observation vocabulary (ordered)

The trace is an ordered array; order is load-bearing (a reordered / dropped / duplicated / changed
ledger delta perturbs it). Each observation is a sorted-key JSON object with a `kind`:

| kind | fields | meaning |
| --- | --- | --- |
| `authorization` | `authorized` | the recorded authorization decision |
| `compute` | `name`, `value` | a compute folded into the env |
| `guard` | `effect`, `held` | a conditional leg's predicate outcome |
| `attestation` | `effect`, `policy`, `accepted` | a gated leg's attestation decision |
| `ledger-delta` | `effect`, `ledger`, `party`, `currency`, `delta` | a signed posting (debit −, credit +) |
| `event` | `name` | a choreography event (`<Effect>Debited/Credited`, `<Proc>Reconciled`, `<Proc>Accepted`) |
| `replay` | `key` | an idempotent re-post no-op |
| `terminal` | `state` | the reached terminal (success on commit; the existing terminal on replay); always equals `nextState.status` |
| `refusal` | `code`, `effect?` | an explicit, coded refusal appended when a transition is rejected; no terminal observation accompanies it (earlier observations remain) |

`nextState` serializes the `status`, the `balances` (a sorted array of
`{ledger, party, currency, balance}`), and the `postedKeys`.

## Evidence-only coordination (no ledger effects)

A coordination whose action is **evidence acceptance** carries an attestation policy and **no**
debit/credit. It has no effect to derive a replay key from, so it declares one explicitly — an
`instance_key <input>` naming a declared, string-typed input (verified once, at the coordination-plan
normalization seam; an absent, ambiguous, non-string, or undeclared key fails before dispatch). Its
identity is target-neutral (`identity:explicit_instance_key`), and the evidence-only shape itself is a
distinct closed feature (`coordination:evidence_acceptance`).

For such a coordination the evaluator takes a **zero-ledger** path after key resolution / replay /
terminal checks: each declared policy's evidence must be **presented** (else `evidence.malformed`) and
**accepted** (else `attestation.rejected`, state unchanged — a clean rollback). On acceptance it emits
an `attestation` observation per policy, a `<Proc>Accepted` event, and the success `terminal`, then
commits the instance key with **no `ledger-delta`**. A re-post of the same instance key is an
idempotent `Replayed`; a distinct key is an independent coordination.

The reference evaluator realizes this, and (as of ) the rigid Solidity and PostgreSQL profiles
advertise `coordination:evidence_acceptance` and **realize** it too: each renders a zero-ledger
lowering that records the accepted terminal keyed by the instance key, gated by the same M-of-N quorum
guard, with no ledger movement (Solidity's `accept()` + `Accepted` event; PostgreSQL's atomically
replay-locked `execute_<proc>` + acceptance row). The acceptance event/record carries only the instance
key — the evidence payload is verified off-chain by the quorum and is not re-logged on-chain. The guard,
however, now persists what the quorum co-signed: both the attested `canonicalClaimHash` and the
`executionClaim` (the coordination's recomputable payload digest), exposed as `acceptedClaim` /
`acceptedExecutionClaim`. So a downstream coordination CAN bind execution to the accepted payload —
requiring its recomputed execution claim to equal `acceptedExecutionClaim(claimId)` before committing —
rather than proceeding on the key alone. A target that does **not** advertise the feature still refuses
before dispatch.

## Determinism & tests

Determinism comes from ordered iteration (coordination-plan effect order; the `std::map`/`std::set`
sort in the state) and the sorted-key JSON printer. Coverage:

- [`test/ir/coordination_trace.neu`](../../test/ir/coordination_trace.neu) — the `.neu` ==
  direct-MLIR == `--from-spec` three-way equivalence, plus a non-vacuous ledger-delta tamper.
- [`test/ir/evidence/shipment_evidence_anchor.neu`](../../test/ir/evidence/shipment_evidence_anchor.neu)
  — the source-authored evidence-only sample: zero-ledger acceptance, `--from-spec` trace agreement,
  Solidity/PostgreSQL realization (byte goldens + no-ledger structural checks, ), and a non-vacuous
  drop-the-key mutation; with negative fixtures for an undeclared / non-string / duplicate instance key.
- [`unittests/CoordinationEvalTest.cpp`](../../unittests/CoordinationEvalTest.cpp) — the
  state-machine cases (guarded balance, distinct-party accounts, auth failure, attestation gate,
  replay, terminal-state rejection, unknown kind, malformed/negative/empty operand, checked
  compute + guard arithmetic (overflow / divide-by-zero / `LLONG_MIN`), balance overflow, inconsistent
  replay state, the terminal↔status agreement invariant, atomic rollback, determinism) and the drop /
  reorder / duplicate / change mutation sensitivity.
