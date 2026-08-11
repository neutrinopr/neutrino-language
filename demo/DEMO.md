# The Neutrino Translator, demonstrated

Four runnable demonstrations, in ascending order. Everything shown is produced by the translator
from an authored agreement. The scripts re-verify the **chain-audited facts** — coordination
status, credit/debit totals, registry state, token balances, replay outcomes — from chain state;
dossier contents, verifier checks, policy decisions, and digest handoffs are off-chain/local
observations, reported as such. Local only: a simulated EVM (anvil), throwaway keys, no network
access.

```
./demo/run_local_demo.sh              the pipeline, end to end
./demo/run_agent_coordination.sh      two agents, one contract, no other channel
./demo/run_kyc_paid_attestation.sh    the main case: real work, checkpointed on chain, paid in ERC20
./demo/run_authoring_demo.sh          untrusted authoring → verified compile → pay-for-work
```

Clean-clone build and prerequisites: [QUICKSTART.md](QUICKSTART.md).

## What the translator is

A deterministic compiler for coordination agreements. The input is a `.neu` procedure — participants,
roles, typed inputs, and guarded, balanced value movements, written at the level of the *agreement*.
The translator verifies the procedure's invariants structurally and renders executable backends —
Solidity in these demos; PostgreSQL generation is a separate compiler capability, not exercised
by the four Web3 scripts. Fixed inputs produce fixed artifacts; every generation writes
machine-readable diagnostics and receipts.

The properties people hand-audit smart contracts for — value cannot appear from nowhere, an
unauthorized action moves nothing, a replay cannot double-move, both sides of a transfer land or
neither does — hold, **for the constructs and artifact family demonstrated here, because the
language cannot express their violation**, not because a developer remembered to check.

## Demo 1 — the pipeline

`token_mint.neu` describes an approval-gated mint as a balanced debit/credit pair (the approval
arrives as a caller-supplied `execute` input; the contract gates accounting on it, and
authenticates nobody). The script
compiles it, deploys it, and refuses to proceed unless the on-chain bytecode is byte-identical to
this run's compiler output — an address holding *some* contract proves nothing.

Two runs: the **approved** mint moves 2500 units, credit equals debit by construction, status
`Reconciled`. The **unapproved** mint is the point: it does not error — both legs suppress, zero
value moves, and the coordination still concludes lawfully as a no-op. Fail-closed value movement is
a property of the artifact, visible in state.

## Demo 2 — coordination through the contract, and nothing else

Two autonomous agents, separate keys, **no channel between them**. The wallet-side agent acts early —
the *contract* refuses it ("missing attestation"). It adapts: watches chain state. The issuer-side
agent's policy clears; it posts the on-chain attestation checkpoint — an **unattributed**
`attest(string)` call, its only signal to anyone; the contract requires the checkpoint, not an
authenticated identity. The wallet agent observes the checkpoint in state, executes, and the
settlement balances. A replay attempt is refused.

The compiled agreement is the entire protocol between the parties. The interleaved agent log *is*
the demonstration.

## Demo 3 — the main case: verified work, attested and paid

A requester (a bank) needs a KYC dossier verified. A verifier firm does the work and is paid for it.
The agreement (`demo/kyc/kyc_attestation.neu` — authored fresh for this demo) compiles to a contract
holding **balanced pay-for-work accounting**: the fee debit and the compensation credit are one
guarded, balanced pair — recorded exactly when the verification checkpoint is present, by
construction. Payment then settles as a **separate scripted ERC20 transfer**. Nobody wrote the
accounting logic by hand; the token transfer is a script step, not contract custody.

What the audience sees:

1. The verifier agent **reads the actual dossier file** and runs real checks — required fields,
   document expiry, sanctions screening.
2. The first dossier **fails** (expired passport, named in the log). The verifier refuses. No
   checkpoint exists, so the accounting records **nothing owed** — and in this scripted run the
   requester process therefore does not execute the separate transfer. The refusal pays the
   verifier nothing.
3. The corrected dossier passes. The verifier checks it off-chain and posts the case checkpoint
   on-chain (`attest(case)` — the checkpoint carries the case key, **not** the digest). The
   dossier's keccak256 (computed over the exact file bytes) is recorded locally and handed to the
   requester, who passes it into `execute` as **requester-supplied execution metadata**. The
   on-chain checkpoint is **not bound to that digest**.
4. The coordination executes and reconciles; **150.00 dEUR (ERC20) settles to the verifier** by
   the requester's scripted transfer. The compiled contract records whether the accounting
   obligation reconciled; it neither holds nor gates the ERC20 funds — the transfer is a script
   step that follows the recorded result.
5. An auditor block re-derives the **chain-audited facts** from chain state — status, both
   coordination ledgers, the token balance, the replay refusal — and separately recomputes the
   dossier keccak256 from exact file bytes, asserting **local equality** with the digest the
   agents handed off. That equality is useful evidence about the local run; it is not a chain
   fact.

The document never touches the chain; its digest appears only as requester-supplied `execute`
metadata. Verification work stays where the data is; the chain records the checkpoint, the
balanced accounting, and the settlement.

This flow **resembles draft ERC-8183's tripartite roles and lifecycle** — client, provider,
evaluator — as compiled accounting plus a scripted settlement transfer. The resemblance is
role/lifecycle only; ERC-8183's **funding escrow, provider work submission, and atomic token
release are absent** here: no funds are escrowed in the contract, no work artifact is submitted
on-chain, and the ERC20 transfer is a separate script step, not an evaluator-released escrow.
Naming the shape the ecosystem is standardising, rather than inventing a rival one, is a
deliberate choice — and so is naming what of it this demo does not do.

How that shape — and every other standards alignment in these demos — was chosen, and which
candidates were considered and set aside, is recorded in [STANDARDS.md](STANDARDS.md).

## Demo 4 — untrusted authoring, verified compilation

The same pay-for-work shape can start as natural language. Under
`demo/authoring/`:

- `agreement.md` is a human-written agreement;
- `PROMPT.md` is the L1 grammar contract an authoring tool would use;
- `authored.neu` is a **committed, untrusted machine-authored** translation of
  that agreement (produced by applying the prompt; not trusted source).

`run_authoring_demo.sh` compiles `authored.neu` with the pinned toolchain, runs
the generated contract through a local-chain pay-for-work path to PASS, then
**deliberately mutates** a temp copy (drops `assert balanced`) and shows a
**named translator refusal** (`kernel.balance.assert_missing`). Trust model
printed by the script: *the language model proposes; the translator verifies
and refuses; the guarantees come from compilation, not from the model.* The
LLM is a user-side tool, never a claimed component of the translator.

## Where this sits among coordination protocols

Two familiar shapes exist for multi-party coordination on and around chains, described here by
mechanics:

- **Workflow runners attached to oracle networks**: trigger-and-callback scripts — short-lived,
  human-written, stateless, with no semantic awareness of the value they move. They coordinate
  *calls*. Whether a run was balanced, authorized, or replayed is the script author's problem.
- **Institutional agreement platforms**: closed-world, human-authored state machines encoding a
  legal agreement's roles and permitted transitions. Rigorous, but every agreement is a bespoke
  program, and the guarantees live in that program's correctness, not in the medium.

The translator takes a third position: the agreement is the **source**, and the guarantees are
**compiler output**. Parties author what should be true — roles, permissions, guarded balanced
movements — and receive an artifact in which the coordination semantics are structural. The same
source renders to more than one backend, so the on-chain contract and an institution's database-side
procedure are two projections of one agreement, not two programs to keep in agreement by hand.

## Honest boundaries

- Demo scaffolding is labeled: `DemoEUR.sol` is a 25-line settlement token, not a product; anvil is
  a simulated EVM; the agents' decision policies are scripted for reproducibility.
- The M6 translator compiles a fixed language surface; extending what agreements can express is a
  compiler change at this stage.
- The refusal semantics shown are deliberately two-tier: an act refused by agreement *policy* (an
  unapproved mint) concludes as a lawful, recorded no-op, while malformed or replayed acts are
  errors and revert. That distinction — policy refusals as outcomes, defects as failures — is the
  semantic split agent-coordination standards work is converging toward, and here it is a compiled
  property rather than a convention.
- Nothing here is a financial product, custody mechanism, or production deployment.
