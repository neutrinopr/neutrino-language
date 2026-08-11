# How this demo chose its standards

The demos coordinate agents through a contract that a translator *generated* from a signed
agreement. Before shipping them, we asked a question that most demos skip: **which existing
Ethereum surfaces should this flow align with — and which alignments would be dishonest to claim?**

This document records the candidates we considered, the criteria we applied, and where each
candidate landed. It exists so the demo's alignment claims can be audited against the process
that produced them.

## The selection criteria

1. **Primary-source verification.** A standard counts only as what its text in the EIP/ERC
   repository says it is — not what secondary posts say about it. Our research passes found
   real discrepancies: adoption claims inflated in commentary, and disagreement between
   sources on a proposal's status. Every status below is quoted from the primary source and
   stamped with a retrieval date; re-verify before any submission that relies on it.
2. **Mechanics already present, not retrofit.** An alignment is claimed only when the
   *generated* contracts already exhibit the standard's mechanics as a compiled property.
   We do not add machinery to a demo to manufacture a resemblance.
3. **No conformance claims against drafts — and no "implements" language against Finals either.**
   Draft proposals move. The strongest language used anywhere is "illustrative alignment with
   the shape" or "mechanics/lifecycle resemblance." Mapping rows without a code
   anchor are claims, not mappings.
4. **Self-contained over infrastructural.** The demo runs on a local chain from a clean
   checkout. Candidates that would import external infrastructure were set aside regardless
   of merit.

## Status refresh (primary source, retrieved 2026-08-08)

Status strings below are the `status:` field from the ERC/EIP markdown in the ethereum/ERCs
(or ethereum/EIPs) repository, quoted verbatim. Source links are the raw files used for the
read.

| document | `status:` (verbatim) | created | primary source (retrieved 2026-08-08) |
|---|---|---|---|
| **ERC-8001** Agent Coordination Framework | `Final` | 2025-08-02 | [erc-8001.md](https://github.com/ethereum/ERCs/blob/master/ERCS/erc-8001.md) |
| **ERC-8183** Agentic Commerce | `Draft` | 2026-02-25 | [erc-8183.md](https://github.com/ethereum/ERCs/blob/master/ERCS/erc-8183.md) |
| **ERC-8004** Trustless Agents | `Draft` | 2025-08-13 | [erc-8004.md](https://github.com/ethereum/ERCs/blob/master/ERCS/erc-8004.md) |
| **ERC-8273** Attestation-Gated Agentic Actions | `Draft` | 2025-05-26 | [erc-8273.md](https://github.com/ethereum/ERCs/blob/master/ERCS/erc-8273.md) |
| **EIP-712** Typed structured data hashing and signing | `Final` | 2017-09-12 | [eip-712.md](https://github.com/ethereum/EIPs/blob/master/EIPS/eip-712.md) |

**Disposition re-read after this refresh.** ERC-8001 is **Final** (earlier research disagreed
2-of-4 on Final vs Draft; this pass read the repository and quotes `status: Final`). That
raises the bar for honesty: a Final standard gets a **mechanics/lifecycle resemblance mapping
with code anchors**, not a vague "orientation" claim, and still never "conforms" / "implements".
ERC-8183, ERC-8004, and ERC-8273 remain **Draft** — dispositions unchanged in strength
("illustrative alignment" / "local shape" / "set aside"). EIP-712 remains Final and deferred
for the *demo* attestation surface (see candidates table and the typed-attestation design note
under `materials/` when present).

## Candidates considered

| Candidate | What it is | Disposition |
|---|---|---|
| **ERC-8001** — agent coordination framework | Propose → accept → execute handshake between agents; defers richer flows to extension modules | **Recorded as a mechanics/lifecycle resemblance** (see table below): agreement ≈ proposal, on-chain checkpoint ≈ the lifecycle's acceptance step, `execute` ≈ execution; compiled guarantees fill what 8001 defers to modules. NOT a profile, NOT an interface claim — demo `attest(string)` is an open, **unattributed** checkpoint: no EIP-712 acceptance surface, no signer recovery, no authenticated role, so 8001's participant-acceptance semantics are not present. |
| **ERC-8183** — agentic commerce | Client funds a job, provider submits work, evaluator's attestation releases escrowed payment | **Recorded as a role/lifecycle resemblance** (Demo 3): requester ≈ client, verifier ≈ provider+evaluator roles, compiled accounting + scripted ERC20 settlement ≈ the payment beat. **Absent, explicitly: funding escrow (no funds held by the contract), provider work submission (no work artifact on-chain), atomic token release (the transfer is a separate script step).** Draft status: no stronger language. |
| **ERC-8004** — trustless agents | On-chain registries giving agents portable identity and reputation | **Adopted as a local shape.** The demo deploys its own registry modeled on the registration shape so both agents register before coordinating. It is demo scaffolding on a local chain — deliberately *not* presented as adoption of the live registries. Draft status: no stronger language. |
| **EIP-712 typed attestation** | Typed structured-data signing, verifiable on-chain | **Considered and deferred — honestly** (for the demo coordination surface). Demo contracts expose open `attest(string)` and do not recover signers. Logging off-chain signatures the contract never checks would *look* like cryptographic verification while providing none; we rejected that as cosplay. Related packs elsewhere already exercise EIP-712 recovery; wiring that shape into *agent attestation* is future emitter/language-surface work, not a demo retrofit. |
| **ERC-8273** — attestation-gated actions | Gates actions inside transient-storage attestation windows | **Set aside.** Window-scoped transient-storage gating is a different mechanic from agreement-compiled persistent gating; claiming kinship would fail criterion 2. |
| **EAS** — attestation service | Live attestation infrastructure with resolver contracts | **Set aside** on criterion 4: it would make the demo depend on external infrastructure without changing what the demo demonstrates. |
| **x402** | HTTP-native payment protocol | **Set aside.** A payment rail, not a coordination protocol — adjacent, not overlapping. Named by mechanics only; not a coordination competitor. |
| **ERC-7683** — cross-chain intents | Standardized intent settlement across chains | **Set aside.** Solves routing of user intents between chains; our problem is holding multiple agents to one agreement on one ledger. |

## ERC-8001 mechanics/lifecycle resemblance (code-anchored)

Language bar for this section: **the demo flow resembles the 8001 lifecycle in its mechanics.**
Not "implements 8001." Not "conforms to 8001." Not "a strict profile" — 8001's acceptance
surface is authenticated (EIP-712 / ERC-1271) and this demo's checkpoint is open and
unattributed, so profile language would claim an acceptance semantics the contract does not
have. Every row has a code anchor; a row without one would be a claim, not a mapping.

ERC-8001 (Final) specifies a multi-party propose → accept → execute lifecycle and **explicitly
defers** privacy, reputation, thresholds, bonding, and richer coordination semantics to
modules. The demo's generated contracts exhibit a *resembling lifecycle* and supply, as
compiled properties, several of the richer guarantees 8001 leaves open.

| 8001 shape element | Profile mapping (this demo) | Code anchor (what exhibits it) |
|---|---|---|
| **Proposal** (initiator posts an intent) | The authored agreement (`.neu` procedure) is the proposal: roles, inputs, and permitted value movements fixed before any agent acts | Source: `domains/packs/token_mint/pack/source/token_mint.neu` (Demos 1–2); `demo/kyc/kyc_attestation.neu` (Demo 3). Generation: `neutrino-gen --target=solidity` in `demo/run_local_demo.sh`, `demo/run_agent_coordination.sh`, `demo/run_kyc_paid_attestation.sh`. |
| **Acceptance** (participant attestation that the intent may proceed) | The lifecycle POSITION is resembled by an **unattributed on-chain checkpoint**: open `attest(string)` sets a flag for a workflow key, and without it `execute` cannot move value. It is not participant acceptance — no signer is recovered, no role is authenticated; any holder of a demo key can call it | Contract: `attest(string)` and `attested` mapping in `domains/packs/token_mint/pack/generated/solidity/src/TokenMint.sol` (lines 19, 24–28). Script beat: issuerco attests in `demo/run_agent_coordination.sh` (`cast send … 'attest(string)'`); verifier attests in `demo/run_kyc_paid_attestation.sh` after real dossier checks. |
| **Execution** (intent runs once acceptances are present) | `execute(…)` runs only when `attested[key]` is true and status is still open | Contract: `execute(…)` in `TokenMint.sol` (lines 30–51), gate `require(attested[_k], "missing attestation")`. Script beat: walletco early execute refused, then execute after observing attestation — `demo/run_agent_coordination.sh` (beats 1 and 4). |
| **What 8001 defers: balanced movement** | Per-key credit totals equal debit totals before reconciliation | Contract: `require(debitTotal[_k] == creditTotal[_k], "not balanced")` in `TokenMint.sol` (line 48). Source invariant: `assert balanced` in `demo/kyc/kyc_attestation.neu`. Script check: Demo 1 read-back `creditTotal == debitTotal` in `demo/run_local_demo.sh` step 5/6. |
| **What 8001 defers: policy-input gating** | Value moves only when the caller-supplied policy input is set (`u_supply_approved`, an `execute` argument); an unset input suppresses movement without inventing balance. This is an execution input controlling paired accounting — the contract does not authenticate any authority or policy decision | Contract: `if (u_supply_approved == 1)` guards on both legs in `TokenMint.sol` (lines 38–46). Script beat: Demo 1 step 6/6 unapproved mint — `creditTotal=0`, status still Reconciled (`demo/run_local_demo.sh`). Missing attestation path reverts with `"missing attestation"` (Demo 2 early execute). |
| **What 8001 defers: replay protection** | Second `execute` for the same workflow key is refused | Contract: `require(statusOf[_k] == Status.None, "replay")` in `TokenMint.sol` (line 32). Script beat: replay attempt refused in `demo/run_agent_coordination.sh` and `demo/run_kyc_paid_attestation.sh`. |

**Explicit non-mapping (honesty boundary).** ERC-8001's acceptance surface is **EIP-712 typed
attestations** (and ERC-1271 org signers). The demo coordination contracts use an open
open, unattributed `attest(string)` — called in the demo by the key scripted to play that
role, with nothing in the contract authenticating it — and they do **not**
recover an EIP-712 signer on `attest`. That gap is intentional and recorded under the EIP-712
row above; closing it is design work, not a silent claim that the current surface is 8001's
typed acceptance.

## The refusal-semantics finding

One selection question produced a design confirmation rather than an adoption. Standards
discussion around agent coordination converges on a two-tier split: an action refused by
*policy* should conclude as a lawful, recorded no-op, while malformed or replayed actions
should be errors. The generated contracts already behave exactly this way — an unapproved
act completes with zero movement and a recorded status, a replay reverts — not because the
demo was tuned to the discussion, but because the split falls out of compiling refusal
semantics from the agreement. That convergence, found rather than built, is the strongest
alignment in this document.

Anchors: policy no-op — `demo/run_local_demo.sh` step 6/6 (unapproved mint, `creditTotal=0`,
status Reconciled); defect/replay revert — `TokenMint.sol` `"replay"` / `"missing attestation"`
requires, exercised in `demo/run_agent_coordination.sh`.

## What this coordination style is called

There is no settled name for using a ledger as the shared coordination medium between
agents — the ledger holding checkpoints, attestations, and net positions while authoritative
state stays in participants' own systems. Across independent research passes the converged
term was **ledger-mediated agent coordination**: the contract is a coordination artifact,
not fund custody, and the demos are written in that vocabulary.

## Demo 4 — deliberately no new alignment

The authoring demo (untrusted machine-authored `.neu`, verified compilation) makes **no
standards-alignment claim of its own** — that is a choice, recorded here so silence is not read
as an omission. Its subject is the trust model: the language model proposes, the translator
verifies and refuses, and the refusal beat (a dropped balance assertion refusing with a named
machine code) is the same two-tier refusal semantics documented above, exercised at authoring
time instead of coordination time. The coordination it then runs is Demo 3's flow, whose
alignments are already stated.

## Honest boundaries

- Status table above is as-of **2026-08-08** primary-source retrieval; drafts move and get
  re-verified before submission.
- No demo claims conformance to anything. The strongest language used anywhere is
  "illustrative alignment with a shape" or "mechanics/lifecycle resemblance,"
  and that bar is enforced at review.
- The deferred EIP-712 line for demo attestation is a boundary, not a roadmap promise.
  A design note (owner-facing) may describe the successor shape without implementing it.
- Mapping tables require code anchors; narrative without anchors is not an alignment claim.
