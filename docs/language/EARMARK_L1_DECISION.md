# ChannelVerificationEarmark — L1 / Core IR hardening decision ()

**Status:** decided (M4) — **first-class L1 Core IR ops/types are DEFERRED**, not required.
Strategy: internal-tracker/neutrino- · Existing L2/L3 artifacts: internal-tracker ·
Runtime follow-ups: internal-tracker/neutrino-network, internal-tracker/neutrino- · Issue:
internal-tracker.

The  review noted that M4 proved the `ChannelVerificationEarmark` concept at L2/L3
artifacts, network admission, and agents runtime fixtures, while the *original* proposal also sketched
possible L1 constructs (`request_earmark`, `admit_earmark`, `challenge_receipt`, `admission_result`).
This records whether the translator's L1 Core IR needs those **today**, before any sample assumes
unsupported earmark syntax.

## Decision: keep the earmark at L2/L3/profile; do NOT add L1 Core IR ops/types now

**We do not add first-class `request_earmark` / `admit_earmark` operations or
`challenge_receipt` / `admission_result` types to the L1 `neutrino` dialect.** The
`ChannelVerificationEarmark` is fully expressed by the artifacts and runtimes M4 already shipped:

- **L2** declares the earmark as a typed proof intent — an `evidenceRequirements[]` entry with
  `category: channel_verification` and `proofTags: [authority, event, liveness]`
  (, [`L2_DOMAIN_SEMANTICS.md`](../domains/L2_DOMAIN_SEMANTICS.md)).
- **L3** binds the admission profile (`channel_verification.v1`) + challenge policy
  ( Binding Manifest).
- **Network** admits the tripartite proof (authority / event / liveness → success / retryable /
  permanent) — network, iOS bridge network.
- **Agents** runtime does the challenge/resume fixture and promo usage — agents, agents.

L1 stays what it is: a **value-movement coordination agreement** (`trigger` + balanced ledger
legs). The earmark is admissible *evidence about* a redemption, not a value-moving leg, so it belongs
above L1 — the same boundary the promo/`core_verified_payout` samples already use (their L1 slot is
`to_be_bound` to the `channel_verification.v1` profile; the earmark never appears as an L1 op).

This is the repo's standing discipline: **schema-first, structure only when a consumer earns it**
(cf. [`L2_LIFECYCLE_DECISION.md`](../domains/L2_LIFECYCLE_DECISION.md),
[`L2_DOMAIN_SEMANTICS.md`](../domains/L2_DOMAIN_SEMANTICS.md), [`LANGUAGE_LEVELS.md`](LANGUAGE_LEVELS.md) where
L2 state-machine syntax is likewise deferred). Adding earmark ops now would be **unexercised IR
structure** for a runtime concern that L1 does not own.

## Why L1 ops/types are the wrong tool right now

| Concern | Why L1 first-class support is deferred |
|---|---|
| **Type explosion** | A proof/earmark *taxonomy* in the MLIR type system (a type per proof kind / result) multiplies the dialect. The taxonomy is already a small **static** L2 `category` + `proofTags` enum — data, not types. |
| **Dynamic data in types** | Challenge, nonce, timestamp, subject, attempt budget are **per-realization dynamic values**. Encoding them as MLIR type parameters is an anti-pattern; they belong as SSA values / sidecar artifacts (today: L3 policy + the agents runtime fixture), not in the IR type. |
| **Privacy boundary** | L1 must never carry plaintext channel concepts (phone/email/SMS). Keeping the earmark out of L1 keeps the privacy line clean — see the privacy rule below. |
| **No lowering need yet** | No backend lowers *from* an earmark op; admission is a network/runtime gate, not codegen. Async continuation + retryable admission are still being proven at runtime (network, agents) — designing L1 ops before that runtime settles would ossify the wrong shape. |

## Privacy rule (binding, whether or not L1 ops ever land)

Any L1-visible representation of an earmark **must use blinded / committed identifiers only**
(e.g. `subjectCommitment = sha256:…`, a `challengeReceipt` handle) — **never** a plaintext channel
(phone/email/SMS/user id). Unblinding happens **only inside a trusted adapter / profile boundary**
(the `channel_verification.v1` runtime), never in L1 Core IR. This is the same rule
enforces at L2 (a transport is an L3/profile concern, never a proof tag) and that the agents runtime
fixture pins (no plaintext leak).

## If/when first-class L1 support is justified — the intended shape (deferred, documented)

Recorded so a future implementation has a target and does not re-derive it:

- **Static vs dynamic separation.** The *taxonomy* (`category` + `proofTags`) stays static (an enum /
  attribute), so it never explodes the type system; the *challenge/nonce/timestamp/subject/attempt*
  stay **dynamic** (SSA values or a sidecar the op references by committed handle), never type
  parameters.
- **Operation shape.** `request_earmark` (produces a `challenge_receipt` value from a blinded subject
  commitment + policy attributes) and `admit_earmark` (consumes a `challenge_receipt` + a presented
  proof, produces an `admission_result`) — pure, side-effect-free ops whose *effect* is the runtime
  admission, mirroring `neutrino_runtime::compat::admit_channel_verification` (network).
- **Value model.** `challenge_receipt` and `admission_result` as **opaque handle/enum SSA values**
  (blinded), not structured plaintext; `admission_result ∈ {success, retryable, permanent}` + a
  taxonomy attribute.
- **Lowering / sidecar.** Async continuation + retryable admission lower to a **sidecar continuation
  artifact** (the same shape network / agents are proving), not to inline control flow — L1
  requests/admits; the runtime carries the resume state.
- **Compatibility gate.** Any such op MUST lower through the **existing**  L2/L3
  ChannelVerificationEarmark artifacts and keep the current samples
  (the verified-payout curated pack,
  agents an externalized domain pack) passing unchanged. That is the acceptance bar for adding the
  structure — a validator + positive/negative fixtures (reject any plaintext channel concept in L1
  Core IR), exactly as 's acceptance states for the *if-implemented* path.

## When to revisit

Reopen the first-class-L1 question when a concrete consumer earns it, e.g.:

1. **Runtime settles.** network (continuation + retryable-admission conformance) and agents
   (bounded-retry runtime fixture) prove the async/retry semantics — and a *sidecar* value/SSA model
   turns out insufficient to express them (i.e., an L1 control-flow construct is genuinely needed).
2. **Cross-backend lowering** of an admission decision becomes a codegen requirement (a backend must
   emit from the earmark op, not just consume a runtime verdict).
3. **Multiple domains** need the earmark as a first-class L1 construct rather than an L2 evidence
   declaration, such that the L2/L3 path causes real duplication.

Until then, the L2/L3/profile + network/agents runtime path is the supported representation, and this
document is the record that the L1 omission is **deliberate**, not an oversight.

## References

- Strategy proposal/review: internal-tracker/neutrino-.
- Existing L2/L3 artifacts + privacy model: internal-tracker ·
  [`L2_DOMAIN_SEMANTICS.md`](../domains/L2_DOMAIN_SEMANTICS.md) ·
  the receipted curated pack selected by the corpus manifest.
- Network admission + bridge + follow-up: internal-tracker/neutrino-network /  / .
- Agents runtime fixture + promo + follow-up: internal-tracker/neutrino- /  / .
- Language levels + deferral discipline: [`LANGUAGE_LEVELS.md`](LANGUAGE_LEVELS.md) ·
  [`L2_LIFECYCLE_DECISION.md`](../domains/L2_LIFECYCLE_DECISION.md).
