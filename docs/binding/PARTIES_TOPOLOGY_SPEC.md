# Parties, Topology & Identity — translator (implemented state)

**Status:** DONE (phases 18-20). First-class participants, organization
boundaries, `allow` org-pair + per-org-pair role policies, the Capability Security
Pass (gating on hard violations + on lowering), and the `agreement … between`
surface sugar all shipped. This document describes the **implemented** translator
slice and the **remaining follow-ups**.
**Source vision:** an internal design record
and `…/security-validation-architecture.md` (the Capability Security Pass).

Concrete cryptographic identity and slot wiring are **not** here — see the
cross-rail notes at the bottom.

---

## Ownership boundary (the layered model, mapped to repos)

| Layer | Defines | Owner | Where it lands |
|-------|---------|-------|----------------|
| L1 Abstract Participants | semantic roles + relationships | DSL/compiler | **translator** (Phase 18) |
| L2 Business Rules & Contracts | permissions, obligations, invariants | DSL/compiler | **translator** (Phase 18 + 20) |
| L3 Capability Topology | abstract capability connections/routing | IR + slot | **translator IR** (Phase 19); concrete wiring → network |
| L4 Cryptographic Identity | wallets / certs / DIDs / attestations | deployment/fabric | **neutrino-network** (+ agents orchestration) |
| L5 Concrete Slot Integration | endpoints, protocols, runtime wiring | network/fabric | **neutrino-network** |

Rule of thumb: the DSL/IR defines *who* participates and *what* may interact
(abstract, stable across identity models); concrete identity binding and wiring
are resolved at deploy/runtime by the sibling rails.

## Language-level coverage (current)

With participants declared, `GenCoverage` reports **L3 "full"** (was "partial" —
party-typed inputs/operands only) and, when participants span ≥2 orgs, **L8
"partial"** (abstract topology translator-owned; concrete multi-org execution stays
`networkOwned`). Capability-model v1 does not duplicate participant/topology
support flags; it projects only the corresponding verified target-profile facts.
Sources that declare no participants/org are **byte-unchanged** (the constructs
are additive).

---

## Phase 18 — First-class participants (L1/L2) — DONE

Participants are first-class DSL/IR constructs rather than bare value references.

- DSL: `participant NAME { role = "..."  capabilities = ["..."] }`, plus an
  `agreement NAME between A and B { … }` form. Backward-compatible: existing
  sources (no `participant`) keep working; their parties remain inferred operands.
- IR: a real `neutrino.participant` op that round-trips through textual MLIR
  (parsed by the frontend, verified by `ParticipantOp::verify`).
- `ProcedureView.participants` (name, role, capabilities, org).
- Generators: slot `capability.json` gains a `declaredParticipants` array (emitted
  only when declared, so existing fixtures are byte-unchanged); `GenCoverage`
  promotes **L3 partial → full**. Capability-model v1 projects the verified
  target profile and does not author a participant `supports` block.
- The `agreement NAME between A and B { }` sugar auto-declares the two parties
  (default role = the lowercased party name) and, when their orgs differ and the
  body declares no policy, auto-emits the org-pair `allow`; an explicit `allow`
  stays authoritative.

Covered by self-test `[21]` (positive + negative) and `[29]` (agreement sugar).

## Phase 19 — Abstract capability topology (L3/L8) — DONE (org boundaries)

The **organization-boundary** half of the abstract topology is translator-owned.

- DSL/IR: participants carry an optional `org = "..."` (trust/organization
  boundary, a `neutrino.participant` attribute).
- Generators: slot `capability.json` gains a `topology` summary (`organizations` +
  `crossOrganization`) and per-participant `org`; `GenCoverage` promotes **L8 →
  "partial"** when participants span ≥2 orgs. Additive — sources without `org` are
  byte-unchanged.
- The `allow` policy gates *which organizations may coordinate* (org-pair) and,
  with the `{ A as "role" }` block, *which role each org plays* — hard-gated by the
  security pass (self-tests `[25]`, `[30]`).

Covered by self-test `[21]` (cross-org topology + L8 partial).

**Not implemented (follow-up):** declared **inter-capability dependencies** (which
capability may invoke which) — there is no dependency graph, and nothing rejects an
"undeclared dependency". Dynamic join/leave (L9) is also deferred (network/runtime-
owned).

## Phase 20 — Capability Security Pass (translator) — DONE (report + gates)

`neutrino-gen --target=security` (`lib/security/SecurityTarget.cpp`) emits a deterministic
`security.json` over the five categories from the security debate — authorization,
value, topology, trust-boundary, state — computed at the IR level from the
`ProcedureView` (using the Phase 18/19 participant + org declarations). Status
model per finding: `pass` / `advisory` (non-gating) / `violation` (hard,
`ok=false`) / `n/a`.

Hard gates today:

- **Value safety** — balance/asset conservation (the `assert_balanced` invariant,
  also enforced by `ProcedureOp::verify`).
- **Authorization safety** — value-moving legs must be bound to a declared
  participant (the optional `participant = "Name"` field on `debit`/`credit`); an
  unbound leg while participants are declared is a hard violation (self-test `[23]`).
- **Topology safety** — the `allow` org-pair + per-org-pair role policy: a
  disallowed pair or an unsatisfied role is a hard violation (self-tests `[25]`,
  `[30]`).

The pass also gates **lowering**: `neutrino-gen` refuses to emit deployable /
coordination artifacts (`solidity`/`postgres`/`slot`/`views`) for a capability with
hard violations unless `--allow-insecure` (self-tests `[27]`, `[33]`). Analysis
targets (`security`/`capability`/`coverage`) are never gated. Advertised as
`generate.security` / `make security`; in `make acceptance`; self-test `[22]`.

Advisory (not yet gating): "no participants" and bare "cross-org" — gating those
needs a further participant-binding policy decision.

---

## Remaining follow-ups

- **Inter-capability dependencies** (Phase 19): a declared dependency graph (which
  capability may invoke which) and rejection of undeclared dependencies — not
  built.
- **Dynamic topology** (join/leave, L9): network/runtime-owned, deferred.
- **Cryptographic identity (L4) + concrete slot integration (L5):** owned by
  `neutrino-network` (abstract role + optional identity hint is as far as the DSL
  goes today).
- **Advisory → gate** for "no participants" / "cross-org": pending the
  participant-binding policy decision.
- Open design questions carried from the debates: backend-aware security checks vs
  pure IR; security pass mandatory vs configurable per domain/trust level; the
  precise definition of an "unauthorized execution path" for topology safety.

## Cross-rail (not in this repo)

- **Cryptographic identity binding (L4) + concrete slot integration (L5) + runtime/
  dynamic topology** → `neutrino-network`:
  `neutrino-network/docs/parties-topology-identity-spec.md`.
- **Deployment binding orchestration** (resolve abstract participants → concrete
  identities via deployment manifests; schedule the generate/security steps) →
  `neutrino-build-tools`: `neutrino-build-tools/docs/parties-topology-deployment.md`.
- **Backend/runtime implementation security** (CodeQL/Semgrep/fuzzing/SBOM) is
  conventional CI hardening, not this domain-aware pass — out of scope here.
