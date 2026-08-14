# Backend Maturity & Language-Level Spec (translator-local)

**Status:** DONE — phases 14–17 shipped: backend capability models, language-level
coverage, property + mutation verification hardening, DSL versioning, and
capability-fork scaffolding.
**Date:** June 22, 2026
**Owner:** Track 2 (translator & runtime engineering)
**Source:** internal design record (pre-publication)
(the framework) and `…/backend-maturity-review.md` (the current-state review).

This is the **translator-owned execution slice** of the Backend Maturity framework.
Track 5 defines the rules/models; this document records how Track 2 landed them
inside the translator implementation without reopening the completed phases 1–13.

---

## Scope & guardrails

What this spec deliberately does **not** redo, because the toolchain already has it:

- deterministic, file-based generation with `manifest.json` / `diagnostics.json`
  on every path (Phase 2);
- native-tool backend validation — `make validate` → `solc --standard-json`
  (mandatory gate) + Slither + `pglast` → `validation.json` (Phase 11);
- machine-readable cross-backend equivalence — `neutrino-equiv --report`
  → `equivalence.json` (Phase 6/11);
- generated executable tests (`forge test`, docker+psql) per backend (Phase 4/5);
- a slot **operation** descriptor — `GenSlot` → `examples/domains/<domain>/generated/slot/capability.json`
  (Phase 9/12), and the bundle capability descriptor `neutrino-bundle --capabilities`.

So the review's "ad-hoc process" gap was narrow: the missing pieces were a
per-backend **semantic** capability model, an explicit **language-level** coverage
map, and **verification beyond happy-path scenarios**. Those are now implemented;
the "Engineering Playbook" is mostly documentation that codifies the existing
pipeline plus these shipped artifacts.

### Three scoping decisions (corrections to the framework, applied here)

1. **Levels are a feature matrix, not a strict ladder.** L1–L5 are roughly
   cumulative language semantics; L6 sagas / L7 compensation / L8 topology /
   L9 discovery / L10 fabric are distribution & runtime concerns, several owned by
   `neutrino-network`. We model coverage as a per-feature matrix with a derived
   ceiling, not a single linear rung. (Compensation metadata already exists in slot
   artifacts ahead of "settlement sagas," which a strict ladder can't express.)
2. **"DSL Semantic Coverage" has a cross-rail ceiling.** The translator cannot
   reach L10 alone — fabric execution is `neutrino-network`. The translator metric
   tops out at *what it can lower and verify*; L8–L10 are reported as
   network-owned, not claimed here.
3. **Maturity Level 2 favors low/mid-cost verification over formal methods.**
   Property-based + mutation testing of the invariants we already assert (see
   an internal design record) is the core
   evidence — not theorem proving. But that translator-local hardening is
   necessary, not sufficient: Level 2 ("Verifiable & Secure") also needs broader
   runtime/security lifecycle evidence, so the backends stay Level 1 until it
   exists. This keeps the bar reachable while staying honest about the remaining gap.

### Honest baseline after Phases 14-17

By the framework's own maturity rule, current `neutrino` semantics cover L1
(agreements), L3 multi-party/topology at the translator-owned abstract layer, L4
(assets/value: money + debit/credit), and L5 (settlement: balanced +
reconciliation). No explicit L2 state machines or L6+ distribution are owned here.
The coverage report makes this assessment machine-checked rather than asserted,
and both execution backends remain Level 1 "Core Compliant" until the broader
runtime/security evidence needed for Level 2 is present.

---

## Phase 14 — Backend Capability Model (catalog projection)

**Status: SUPERSEDED BY v1.0.0.** The original v0.1 model mixed verified profile
facts with core-authored conformance, cost, security, maturity, language-level,
and assurance claims. Those fields and their static fixtures are retired.

The current driver-serialized `neutrino-gen --target=capability` emits exactly
one closed v1 model per independently verified external target profile. The
model contains the package/profile facts verbatim, their authenticated profile
digest, the complete catalog identity, and the source capability witness. It
does not infer conformance or evidence status. The complete contract is
[`CAPABILITY_MODEL.md`](CAPABILITY_MODEL.md) and
`lib/policy/capability-profile/backend-capability-model-v1.schema.json`.

`scripts/gates/check_capability_claims.py` consumes an independently
materialized verified-catalog closure, reconstructs every expected model,
validates the closed schema, enforces the exact filename/model bijection, and
checks every manifest byte hash. Missing, extra, malformed, stale, substituted,
or consistently re-signed output fails closed.

Language-level coverage and maturity remain the separate Phase 15 `coverage`
surface. Future conformance, assurance, or maturity declarations require their
own versioned package-owned contract; they cannot be added to capability-model
v1.

---

## Phase 15 — Language-Level Coverage Map

**Status: DONE.** Implemented by `neutrino-gen --target=coverage`,
`lib/coverage/CoverageTarget.cpp`, fixtures under `examples/domains/<domain>/generated/coverage/`, and self-test `[16]`.

**Goal:** make the L-level coverage and the resulting maturity ceiling
machine-derived, not asserted.

**Deliverables**

- `docs/language/LANGUAGE_LEVELS.md` — the L1–L10 feature matrix mapped to concrete
  `neutrino` ops/attributes/invariants, with the cross-rail boundary marked
  (which levels are network-owned).
- `coverage.json` emitted from the frozen **capability-spec** (`GenCoverageSpec`,  —
  no `ProcedureView`): per procedure, which features/levels it exercises; per target, the highest
  level it verifiably supports → the derived **maturity ceiling** (Level 0–3) via the framework rule.
- Self-test asserting the current sample domains resolve to the expected ceiling
  (Level 1 today), so a future regression or new level shows up as a diff.

**Acceptance criteria**

- coverage + ceiling are computed and reported, not hardcoded.
- adding a new DSL feature/level updates the matrix and (if unsupported by a
  backend) visibly lowers that backend's reported ceiling.

**Priority:** High · **Effort:** Low–Medium · **Repo-local:** yes.

---

## Phase 16 — Verification Hardening (property-based + mutation)

**Status: DONE.** Implemented by `scripts/property_test.py` and
`scripts/mutation_test.py`, wired into `make test` / `make acceptance` through
self-tests `[17]` and `[18]`.

**Goal:** raise confidence past happy-path scenarios, at low/mid cost. Detailed
methodology lives in the sibling `verification-implementation-spec.md`; this phase
is its translator landing.

**Deliverables**

- Property-based tests for the invariants the toolchain already asserts —
  balance conservation, replay-safety / idempotency, determinism (same input →
  same bytes), reconciliation drift detection — run against the generated backends
  and the equivalence reference, with randomized scenario inputs within
  value-model bounds.
- IR/source **mutation testing**: a harness that mutates `.neu` / IR (drop a
  credit leg, alter a compute, duplicate an idempotency key, unbalance a posting)
  and asserts the verifier or a generated backend test **catches** it; surviving
  mutants are reported (mutation score is a supporting metric).
- Wire both into `make test` / `make acceptance`; emit results under the
  agent-layer report conventions.

**Acceptance criteria**

- a documented property set with a runnable harness, green on both sample domains;
- a mutation run with a reported score and zero undetected critical mutants
  (unbalanced posting, double-post, dropped leg).

**Priority:** Medium · **Effort:** Medium · **Repo-local:** yes (per-backend
execution still needs `forge`/`docker`, as today).

---

## Phase 17 — DSL Versioning & Capability Forking

**Status: DONE.** DSL versions flow source -> IR -> capability identity (self-test
`[19]`), and `scripts/generators/fork_capability.py` / `make fork` scaffolds compatible
capability forks (self-test `[20]`).

**Goal:** make language evolution explicit and replay-safe, per the framework's
versioning rules.

**Deliverables**

- a `version` (DSL/semantic) threaded through `.neu` → IR → `manifest.json`
  and into the capability identity, so a capability id pins its DSL + security-rule
  version;
- **capability forking** as the breaking-change strategy: a new version is a new
  capability, deployed capabilities stay immutable (protects evidence/replay);
- transcript/equivalence outputs bound to the DSL version; `COMPATIBILITY.md`
  updated with the version + fork policy;
- a `neutrino-gen`/helper path to scaffold a new capability version from an older
  one (migration assist), kept deterministic.

**Acceptance criteria**

- capability identity includes a version; changing semantics forks rather than
  mutates; compatibility statement and tooling reflect it.

**Priority:** Medium · **Effort:** Medium · **Repo-local:** yes.

---

## Sequencing & rationale

```
14 Capability Model  →  15 Level Coverage Map  →  16 Verification Hardening  →  17 Versioning
   (linchpin: both docs       (cheap; sets the         (raises the ceiling           (locks evolution
    rank it first)             honest ceiling)           toward Level 2)               + replay safety)
```

14 landed first because it is the comparison substrate both strategy docs
prioritize and is fully repo-local. 15 makes the maturity claim honest. 16 is the
real lift toward Level 2 "Verifiable & Secure." 17 protects evidence as the
language evolves. The review's "pilot a new backend (Move/WASM/JVM)" remains
correctly ranked lower / higher-effort: a new target should be the first consumer
of the capability model + playbook, not a prerequisite.

## Metrics (translator-owned subset)

- **DSL Semantic Coverage** — highest language level verifiably supported by a
  target (Phase 15), capped at translator-reachable levels.
- **Conformance/Security coverage** — share of supported semantics at `Verified`
  with a native security property (Phase 14).
- **Mutation score** + **% of self-test/equivalence suite passed** — supporting
  signals (Phase 16).

## Deferred / out of scope (cross-rail or later)

- L8–L10 (topology / discovery / fabric execution) — `neutrino-network`-owned;
  reported, not implemented here.
- formal verification / theorem proving — explicitly not in scope. Level 2 is
  earned via property + mutation testing **plus** broader runtime/security
  lifecycle evidence — not by theorem proving.
- piloting a new execution target (Move, WASM, JVM, Yul) — after 14–16.
- agent scheduling of `generate.capability` — `neutrino-build-tools`-owned.
