# Backend / Generator Module Boundaries

How the translator's generation targets are organized, and the intended boundaries
for adding more without growing a monolith (issues , ). This is a structure /
ownership document — it changes no generated artifact bytes.

## Capability-spec migration (M5 WP3+)

Renderers are migrating from `ProcedureView` to the **canonical capability-spec** (the frozen external
contract, [`CAPABILITY_SPEC.md`](../spec/CAPABILITY_SPEC.md)). **The migration is now complete:** slot
(), PostgreSQL procedure + harness (/), Solidity contract + Foundry harness
(//), participant **views** (, [`lib/views/GenViewsSpec.cpp`](../../lib/views/GenViewsSpec.cpp)),
the **slot** lifecycle projector (, [`lib/slots/GenSlotSpec.cpp`](../../lib/slots/GenSlotSpec.cpp)),
the per-backend **capability model** (, [`lib/policy/capability-profile/GenCapabilityModelSpec.cpp`](../../lib/policy/capability-profile/GenCapabilityModelSpec.cpp)),
the **Capability Security Pass** (, [`lib/security/GenSecuritySpec.cpp`](../../lib/security/GenSecuritySpec.cpp)),
and the **language-coverage report** (, [`lib/coverage/GenCoverageSpec.cpp`](../../lib/coverage/GenCoverageSpec.cpp))
all render from the capability-spec JSON in `View.h`-free translation units — every renderer consumes
the frozen contract, none re-derives from `ProcedureView`. The milestone-wide anti-backslide sweep
`[89]` discovers them structurally (`lib/Gen*Spec.cpp`) and pins the property.

The retained-core **coverage** report derives L1-L10 level presence from the spec's
`trigger` / `effects` / `inputs` / `participants` / `invariants` fields (numeric-input classification
reuses the shared `ValueModel.h`, so it can't drift from the ProcedureView path), keeps L6-L10 marked
network-owned (out of translator runtime scope), and owns no production-backend capability claims.
Full builds append the legacy bundled-backend maturity overlay in a full-profile-only adapter; that
adapter is absent from the backend-free core export. Since the spec is scenario-free, the report is
byte-invariant to the scenario (self-test `[16b]`).

The **security** report + gate () read the spec's `participants` / `effects` / `invariants` /
`inputs` / `topology.allowedOrgPairs` fields to compute the five categories (authorization, value,
topology, trustBoundary, state); like `GenViewsSpec` / `GenSlotSpec` / `GenCapabilityModelSpec` it is
a structural renderer (no compute-AST lowering, so it is a documented carve-out from the
`exprFromJson` rail). `security.json` and the `hasSecurityViolations` gate share one spec-driven
category builder, and — since the spec is scenario-free — the report is byte-invariant to the scenario
(self-test `[22b]`). Output is byte-identical to the pre-migration `ProcedureView` path.

The v1 capability model is a structural projection of a verified target-profile
catalog row plus the capability-spec source witness. Backend support facts are
not authored in core: package, semantic-profile, supported, and unsupported
facts remain byte-for-byte those of the verified profile. Conformance,
value-model, language-level, maturity, and assurance claims are absent from v1;
adding any such claim requires a separately versioned package-owned contract.

**Include-boundary lock (M5 R4, ).** The sweep's blocklist (`no View.h` / `no parseExpr`) is
generalized into a **positive include allowlist** for renderer TUs — [`scripts/gates/check_renderer_includes.py`](../../scripts/gates/check_renderer_includes.py),
run in the fast tier (`[fast/15]`) and the full sweep (`[89]`). A renderer TU may include ONLY its
own header, the capability-spec contract + `View.h`-free adapters (`Expr.h`, `ValueModel.h`,
`Lifecycle.h`, `StrCase.h`, `Manifest.h`), `llvm/…`, and the C++ standard library; any reach-back
into `ProcedureView` / kernel-IR / parser / analysis internals fails CI. There are **no exceptions**:
the former `SlotTarget.cpp` `Analysis.h` allowance was retired by the slot→spec-JSON migration () —
`GenSlotSpec.cpp` reconstructs the lifecycle from the capability-spec via `lifecycleModelFromSpec`
(`Lifecycle.h`), and `SlotTarget.cpp` is the registry ENTRY (emits + re-parses the capability-spec,
like `ViewsTarget.cpp`), not a scanned renderer TU. This is an **output-side extractability lock only, not
the physical renderer split** (which stays speculative for M5); see the allowlist rationale in the
script's docstring and `architecture/repo-boundary-map.md` (R1, neutrino-).

**Renderer terminology ( / total rename).** The renderer **functions**, **params**, AND
**filenames** all carry capability-spec terminology — `generate<Backend>FromSpec(const json::Object
&spec)` and `lifecycleModelFromSpec`, defined in `lib/**/Gen*Spec.cpp` / `CapabilitySpecTarget.cpp` /
`SpecLegality.cpp` (+ matching `include/Neutrino/*Spec.h`). The  include-boundary lock + `[89]`
sweep discover renderer TUs structurally via `glob("lib/**/Gen*Spec.cpp")` (excluding the producer
entry) and derive each TU's own header from that filename. The pre- orchestration term is
**fully eradicated repo-wide** — the `[fast/18]` gate greps the whole tree and fails CI if it
reappears (only genuine English/domain words such as `planned` / `control plane` / `installment plan`
/ `explanation` are allowlisted), so there is no internal-convention residual to keep.

**PostgreSQL is fully migrated (WP5,
):** BOTH `procedure.sql` and the docker/psql test harness (`run_db_test.sh`) are rendered by
[`lib/backends/postgres/GenPostgresSpec.cpp`](../../lib/backends/postgres/GenPostgresSpec.cpp) from the capability-spec JSON — that translation
unit includes **no `View.h`** and calls **no `parseExpr`** (compute expressions are rebuilt from
the capability-spec's serialized AST via `exprFromJson` and lowered with `toSql`). `emitPostgresProject`
emits the capability-spec (`capabilitySpecJson`) and re-parses it, so the renderer consumes exactly the
external contract; the old `ProcedureView`-based renderers are **removed**.

**Coordination lifecycle parity ().** `procedure.sql` renders the same two-phase
attest → execute → reconciled projection the Solidity contract does: an `attest_<proc>` function
and a `coordination_status` row per workflow key, with the execute path refusing an un-attested
key (`missing attestation`), a reconciled key (`replay`), and an attest of a reconciled key
(`bad transition`), then marking the key reconciled. Each leg also carries the  runtime money
guard (a negative amount `RAISE`s rather than inverting the transfer on signed `bigint`). The
generated `run_db_test.sh` proves the attestation gate + replay/transition refusals on a real
container. PG is no longer a flat ledger-projection: it is a peer coordination backend.

The docker/psql **test harness** (`generatePostgresDbTestFromSpec`) is single-sourced onto the
**same spec** as `procedure.sql`: its structural shape (input names/types/order, workflow
idempotency key, entry count, procedure name) comes from the capability-spec, so it can never drift from the
procedure; the scenario is folded once into the **test-realization artifact** (WP2/) and
supplies only the concrete values/ledger. It is a `View.h`-free entry point too, so the migrated
PostgreSQL renderer owns no independent workflow/state semantics. (`emitPostgresProject` itself
legitimately keeps `ProcedureView`: it is the registry `EmitFn` entry and calls
`realize`/`capabilitySpecJson`.) Rendering PostgreSQL SQL directly from a frozen spec is available
via the shared `neutrino-gen --from-spec` ingestion surface (WP6, /).

**Solidity is migrated for the contract (WP6, ):** the coordination contract `src/<Name>.sol`
is rendered by [`lib/backends/solidity/provider/GenSoliditySpec.cpp`](../../lib/backends/solidity/provider/GenSoliditySpec.cpp)
(`generateSolidityContractFromSpec`) from the capability-spec JSON — that translation unit includes **no
`View.h`** and calls **no `parseExpr`** (compute expressions are rebuilt from the capability-spec's
serialized AST via `exprFromJson`, **re-typed on ingestion** with `typeExpr` so a tampered spec is
rejected with `expr.type` rather than trusted, and lowered with `toSolidity`). `emitSolidityProject`
emits the capability-spec (`capabilitySpecJson`) and re-parses it, so the renderer consumes exactly the
external contract; output is **byte-identical** to the old `ProcedureView` path (self-test `[83]` +
equivalence). The old `ProcedureView`-based `generateSolidityContract` is **removed**. The Foundry
**test harness** is migrated too (`generateSolidityTestFromSpec`,  — the symmetric analog of
the PostgreSQL harness migration ): its structural shape (input names/types/order, workflow
key, trigger, compute/effect names, entry set) is single-sourced from the **same spec** as the
contract, so contract and test cannot drift; only concrete values/ledger come from the folded
test-realization (WP2/). Both renderers live in `GenSoliditySpec.cpp` (`View.h`-free), so the
whole migrated Solidity renderer owns no independent structural semantics; `SolidityTarget.cpp`
is the target's `emitSolidityProject` entry. `pascalCase` was extracted to
[`Neutrino/StrCase.h`](../../include/Neutrino/StrCase.h) (a `View.h`-free header) so the capability-spec renderer
can name Solidity symbols without pulling in `ProcedureView`.

#### What WP6 migrated — and what it deliberately did not (the on-chain state machine)

WP6 migrated the contract's **data** (inputs / computes / effects / invariants) onto the capability-spec. It
did **not** derive the contract's **state machine** from the capability-spec's lifecycle, and that is a
recorded decision, not an oversight. The spec carries the canonical
OPEN..CLOSE lifecycle machine; slot (/) derives its operations from that shared machine
and `[80]` cross-checks them. The **on-chain surface is different**: the Solidity contract is a
**fixed 2-state coordination projection** — `Status{None, Reconciled}`, `attest`→`execute`, the
replay/attestation guards, the `Reconciled` terminal — hand-authored, **intentionally not
derived** from the 8-state machine. The chain records `attest → execute → reconciled`; the full
negotiation lifecycle (OPEN/NEGOTIATE/PROPOSE/…) runs in the **coordination/slot layer**, not on
chain. So M5's "one canonical machine" is realized for **slot** (unified) and is **N/A** for
PostgreSQL (relational, no state machine); for **EVM the coordination machine is a separate,
intentionally fixed projection**. This is a real milestone caveat — recorded here, not a footnote.

"Not derived" is **not** "disconnected": the renderer pins the fixed surface to the capability-spec so it
cannot silently diverge — it **fails closed** (`spec.ast`) if the capability-spec's lifecycle has no
`success` terminal (the `Reconciled` terminal projects it), and it emits the
`require(debitTotal == creditTotal)` balance guard **iff** the capability-spec carries a `balanced`
invariant. Self-test `[85]` cross-checks both directions against the committed spec + contract.
Building a first-class **`lifecycleProjection`** into the capability-spec — so the on-chain control structure
*derives* from the canonical machine rather than projecting it by hand — is the deferred WP1
prototype, tracked as a follow-up (WP6's remaining half): [](internal-tracker).

**Capability-spec legality gate at the renderer entry (WP4/WP6, /).** A gated render now runs the
spec-legality gate **before dispatch**: `neutrino-gen --profile=<target-profile.json>` matches the
spec's `targetRequirements` against the profile's `supportedFeatures` and **fails closed**
(`legality.unsupported_feature`, exit `6`) on an unsupported *required* feature — so no artifact is
emitted for a capability the target profile cannot legally realize. The check is the in-process
C++ twin ([`lib/SpecLegality.cpp`](../../lib/SpecLegality.cpp)) of the canonical Python gate
([`scripts/gates/check_spec_legality.py`](../../scripts/gates/check_spec_legality.py)); the two **must agree**, so
the `legality.*` codes are `DiagEmitter::Both` and `[84]` is a parity test (same spec+profile,
same accept/reject). When no `--profile` is supplied the gate is skipped (nothing to gate
against); CI/release always supply the target profile.

#### Oracle S2c: the on-chain M-of-N acceptance guard ()

When the capability-spec carries an **attestation policy** ( — an `attest` block on an `evidence`
input: `quorum` M, `observer_set`, `canonicalization`, `timeout`, `fallback`), `emitSolidityProject`
ALSO emits `src/ThresholdQuorumAcceptance.sol` — the on-chain guard that verifies at least M distinct
authorized observers signed the canonical claim before the coordination proceeds. This is the S2
lowering of the spec-declared policy, and it follows the **reference-first methodology** (): the
renderer does not invent an acceptance pattern, it **reproduces the security-reviewed reference golden**
([`examples/oracle-reference/threshold-quorum`](../../examples/oracle-reference/threshold-quorum), )
**byte-identically**. The byte-golden diff in [`test/ir/oracle/oracle_delivery.neu`](../../test/ir/oracle/oracle_delivery.neu)
is the proof — the rendered bytes equal the reviewed contract, so drift on either side fails CI, and the
reference's 11-test Foundry suite (missing quorum, duplicate/unknown signer, mismatched claim,
malleable/invalid signature, replay, cross-fork replay) transitively covers the rendered output.

Key properties:

- **Deployment-independent guard.** M (threshold), N (observer count), the observer addresses, and the
  `capabilityHash` are all **constructor arguments** resolved at deploy/binding ( slice 5), so
  nothing in the guard source is spec-interpolated — the same reviewed bytes render for every `exact`
  attestation policy. The guard is a **separate** contract deployed alongside the coordination contract;
  it records acceptance only (it moves no value — the leg's value movement stays the coordination's
  concern).
- **The coordination is GATED BY the guard (no self-attest bypass).** For an attested spec the generated
  coordination contract (`<Name>.sol`) takes the guard address at construction and its `execute()`
  requires `acceptanceGuard.isAccepted(_k)` (the workflow key is the guard's `claimId`). The legacy
  self-attestation — a `mapping attested` plus a **public `attest(string)` setter any caller could flip
  to satisfy the gate** — is **removed** for attested specs, so a leg can never post on unattested
  evidence. An unattested spec keeps the legacy self-attested 2-state projection **byte-identical**.
  Proven two ways: a **structural** lit regression (`oracle_delivery.neu` — the coordination has no
  `attest(`, requires `isAccepted`, and the harness has a `quorum not accepted` revert case), PR-gated;
  and a **behavioral** `make oracle-coordination-test` (acceptance tier) that `forge test`s the generated
  project against a mock guard — `execute()` reverts unaccepted, proceeds once accepted. The guard's own
  crypto (M-of-N / replay / low-s / cross-fork) stays proven by its reviewed Foundry suite.
- **Fail-closed on an unreviewed shape.** Only `exact` canonicalization (byte-equal discrete claim) has
  a reviewed on-chain guard. Numeric `median`/`tolerance` aggregation is a **deferred profile** (),
  so `generateThresholdQuorumGuard` **fails closed** (`attest.canonicalization.unsupported`) rather than
  emit an unreviewed guard. Pinned by [`test/ir/oracle/neg_quorum_guard_median.neu`](../../test/ir/oracle/neg_quorum_guard_median.neu).
- **Timeout/fallback is NOT in the guard.** The guard records acceptance; the declared `abort`/`escalate`
  timeout fallback lives in the S3 coordination machine (), not on the guard. The concrete
  timeout-transition rendering settles under  — see the reference `REVIEW_NOTES.md`.
- **`schemaVersion` bumps to 3.** An attestation policy is the **first point where a consumer that
  IGNORES the policy is UNSAFE** — a pre-3 Solidity backend would deploy the coordination WITHOUT the
  M-of-N guard, firing a leg on unattested evidence. So `capabilitySpecSchemaVersion` returns **3** for
  any attested spec (it subsumes the conditional-guard bump to 2); a pre-3 consumer must refuse such a
  spec rather than silently drop the guard. Asserted in `oracle_delivery.neu` / `neg_quorum_guard_median.neu`.
- **Non-oracle output is byte-identical.** A spec without an attestation policy emits no guard, so its
  Solidity project is byte-for-byte what it was before this slice (the `[83]` domain goldens are
  unchanged — no committed domain declares `attest`).

#### Oracle S2d: the PostgreSQL M-of-N acceptance guard ()

The **same** attestation policy renders an M-of-N quorum acceptance guard on the **PostgreSQL** rail too,
in parity with the Solidity baseline. When the spec is attested, `generatePostgresProcedureFromSpec`
gates the coordination: `execute_<proc>()` requires the workflow key to be **accepted**
(`NOT EXISTS (SELECT 1 FROM quorum_acceptance WHERE claim_id = <key>) → RAISE 'quorum not accepted'`), and
the naive `attest_<proc>` self-attestation is **replaced** by `accept_<proc>(claim_id, canonical_claim_
hash, observers[])`. `generatePostgresQuorumSchemaFromSpec` adds the `authorized_observer` (the bound
set, N — seeded at deploy like the Solidity guard's constructor args) and `quorum_acceptance` (the
replay lock) tables; the threshold M is spec-portable and rendered into `accept_`. An unattested spec's
`schema.sql`/`procedure.sql`/`run_db_test.sh` stay **byte-identical**.

**Intentional rail difference (the one  says to make explicit).** PostgreSQL has **no on-rail
signature recovery** — there is no `secp256k1`/`ecrecover` in vanilla Postgres. So unlike the Solidity
guard (which recovers signers on-chain via `ecrecover` and enforces EIP-712 domain separation / low-s /
strict-ascending distinctness), the SQL guard admits **already-recovered observer IDENTITIES** and
enforces the **admission** policy: at least **M distinct authorized** observers over the **same**
canonical claim, accepted **at most once** (fail-closed on an unauthorized observer id, fewer than M
distinct, or a replay of an accepted claim). The cryptographic signature recovery stays with the
**off-chain aggregator** (S4, ), which already recovers + authorizes signers before submitting
observer identities. This is the correct division for the rail — Postgres is a *coordination database*,
not a trustless VM — and it is surfaced in the guard's SQL comments, the `oracle_delivery.neu` structural
checks, and the fail-closed matrix test. Numeric `median`/tolerance canonicalization fails **closed** at
render (only `exact` is lowered), exactly as on the Solidity rail. A spec with **more than one** `attest`
policy fails **closed** at render (`attest.multi_policy.unsupported`) on **both rails** ( — the
Solidity guard matches this parity): the quorum lowering gates exactly one policy per procedure, keyed by
the workflow key, so it refuses rather than silently leave the others ungated (fail-open). Real per-policy
binding (one acceptance per policy) is the remaining  scope; `neg_multi_policy.neu` pins the
fail-close on both rails.

**Access control is part of the trust model — the guard is no-access-by-default (fail-safe).** The
admission model's soundness rests on **who may call `accept_<proc>`**: it verifies the observer ids are
*authorized*, not that they *actually attested* (SQL can't recover signers). PostgreSQL grants `EXECUTE`
to `PUBLIC` by **default**, and the observer ids are **not secret** (they are the observer set) — so a
`PUBLIC`-callable `accept_` would be **forgeable** by any database user (the SQL-rail analog of a
decorative on-chain guard with a bypass path). So the rendered `procedure.sql` **`REVOKE`s** `EXECUTE ON
FUNCTION accept_<proc>(...) FROM PUBLIC` — the guard is **no-access-by-default**, the SQL counterpart of
the Solidity guard being trustless by construction. **Deployment step (mandatory):** the deployer must
then `GRANT EXECUTE ON FUNCTION accept_<proc>(...) TO <aggregator_role>` — granting the accept path to
**only** the off-chain aggregator identity (S4). `execute_<proc>` may stay `PUBLIC` (it is gated on
`quorum_acceptance`, so it fires only for a claim the aggregator accepted). Superusers bypass `REVOKE`,
so the container-superuser test harness is unaffected; the fail-closed matrix test additionally proves a
**non-privileged role is denied** `accept_` (the `REVOKE` is load-bearing, not decorative).

**Proof.** `oracle_delivery.neu` byte-diffs the rendered `procedure.sql`/`schema.sql`/`run_db_test.sh`
against the committed golden and structurally pins the `accept_`/gate/tables (PR-gated, lit). The
generated `run_db_test.sh` proves the happy path (accept M distinct → execute posts) + the quorum gate +
replay against a real container; the dedicated `make postgres-quorum-guard-test` (acceptance tier + the
scoped `oracle-postgres` PR workflow) proves the full fail-closed **admission matrix** — fewer than M,
duplicate observers, an unauthorized observer, a different claim not aggregating, and accept-replay.

#### The three oracle single-sourcing invariants

The oracle vertical renders **three artifacts from one spec/binding** — the on/off-chain acceptance guard
(S2, /), the serverless observers (S4, ), and the coordination that gates on the guard
(/). Three gates keep them from drifting apart independently, each non-vacuous (a tampered artifact
FAILS):

1. **Cross-backend equivalence ()** — the Solidity and PostgreSQL renders of the *same* spec agree on
   the coordination semantics.
2. **Observer↔guard parity (, `check_observer_guard_parity.py`)** — the rendered observers sign exactly
   the guard's EIP-712 `claimDigest` (scheme + domain + threshold + observer-set + claim shape), so their
   signatures actually verify on the guard.
3. **Coordination↔guard claimId parity (, `check_coordination_guard_parity.py`)** — the id the guard
   accepts under is exactly the id the coordination's `execute()` checks: **`claimId ≡ workflowKey`** (the
   spec's `idempotency_key`), single-sourced, on both rails. Two-sided per rail — Solidity *derives*
   `keccak256(bytes(u_<key>))` and *checks* `isAccepted` with that same variable (and its guard interface
   matches the guard's actual `isAccepted` accessor); PostgreSQL *records* under and *checks*
   `quorum_acceptance.claim_id = p_<key>`. This is **fail-safe** — a drift bricks liveness (`isAccepted`
   never true), it can never bypass quorum — but the gate stops the silent-drift window (`coordination_guard_parity.test`).

### Yul / standard-json / via-IR spike (WP6, ship/no-ship evidence, not a blocker)

The WP6 charter asked whether emitting **Yul** (or driving `solc` via **standard-json** / **via-IR**)
should replace the current Solidity **source** emission now that the contract is rendered from the
spec. Finding: **no-ship for M5** — keep emitting Solidity source. Evidence:

- **The spec is the leverage point, not the surface syntax.** Migrating the renderer onto the capability-spec
  (this WP) is what makes an alternative backend cheap later: a Yul/IR emitter would be *another*
  spec consumer (`exprFromJson` + a Yul lowering of `Expr`, mirroring `toSolidity`), fully additive
  and independent of the source emitter. Nothing about staying on Solidity source blocks it.
- **Source emission keeps the audit story.** The coordination contract is meant to be **read and
  reviewed** by the participants who accept its checkpoints; `solc --standard-json` already compiles
  it and `slither` already lints it (`validate_backends.py`). Hand-authored Yul forfeits that
  reviewability for no semantic gain at this scale (no tight gas budget, no constructs Solidity
  can't express).
- **via-IR is a `solc` flag, not a translator concern.** If a consumer wants IR-based optimization
  they pass `--via-ir` to `solc` on the emitted source today; the translator need not own that.
- **Cost/benefit is negative now.** A second lowering path doubles the byte-stability + equivalence
  surface we must pin, with no capability it unlocks for the current samples. Revisit only if a
  target profile ([`TARGET_PROFILES.md`](TARGET_PROFILES.md)) appears that *requires* a construct
  the Solidity surface can't carry.

This is recorded as evidence, not a gate: WP6 ships on the byte-identical source migration above.

## Today

- **`TargetRegistry` is the single source of dispatch truth.**
  [`lib/emit/TargetRegistry.cpp`](../../lib/emit/TargetRegistry.cpp) holds one `TargetSpec` table
  (`name`, `emit` function pointer, `gated`). The CLI derives the valid-target list,
  the lowering/gating classification, and the emit dispatch from this one table —
  adding a target is one entry, not three scattered edits. `neutrino-gen` only ever
  calls `targetSpec->emit(...)`, never a generator function by name.
- **Target entries are split by output family**: `SolidityTarget` / `PostgresTarget` /
  `SlotTarget` / the driver-serialized capability target / `CoverageTarget` / `SecurityTarget` / `ViewsTarget`,
  each a `lib/targets/*Target.cpp`. They consume `ProcedureView` (+ shared `NeutrinoAnalysis`)
  and write artifacts; they share the uniform `EmitFn` signature
  `(const ProcedureView&, const Scenario&, const std::string& outDir) -> paths`.
- **The coupling problem (resolved):** `include/Neutrino/Backends.h` *was* a
  kitchen-sink header that, besides the registry, declared *every* emitter plus
  unrelated concerns (`validateScenario`, `sha256OfFile`/`writeManifest`,
  `hasSecurityViolations`) — every generator/tool/registry translation unit included
  it and so depended on far more than it used. It has now been split into focused
  per-target / registry / validation / tooling headers and **retired** (see the
  migration order below); each translation unit includes only what it uses.

## Intended boundaries

1. **Each target owns a small header** `Neutrino/Gen<Target>.h` declaring only its
   `emit<Target>` entry. Its `lib/targets/<Target>Target.cpp` and the registry include that;
   nothing else needs it. (Exemplar in this slice:
   [`Neutrino/GenCoverage.h`](../../include/Neutrino/GenCoverage.h).)
2. **The registry stays the one dispatch authority.** The central `TargetSpec` table
   includes the per-target headers and lists the entries. We deliberately keep the
   function-pointer table rather than a virtual/plugin interface or static
   self-registration: the table is simple, centrally reviewable, and *is* the single
   source of truth — a plugin interface would add indirection without addressing the
   real coupling (the shared header), and self-registration would scatter the
   authoritative list. So the acceptance "introduce a pluggable interface or justify
   keeping the table" is answered: **keep the table.**
3. **Non-target concerns leave `Backends.h`.** Scenario validation
   (`validateScenario`), manifest/hash tooling (`sha256OfFile`/`writeManifest`), and
   the registry types move to their own headers — realized as `Validate.h`,
   `Manifest.h`, and `Targets.h`, and `Backends.h` retired (see Migration order).

## Invariants (every slice must hold)

- No change to target **names**, **manifests**, **diagnostics**, **exit codes**, or
  **generated file layouts** — these are frozen contracts.
- **No generated-artifact byte churn.** The R0 characterization net (`[43]`) plus
  per-target fixtures (`[14]` capability, `[16]` coverage, `[22]` security, `[33]`
  views, `[11]`/`[13]`/`[32]` slot, solidity/postgres equivalence) prove byte
  stability across each boundary move.
- Pure declaration/`#include` moves; no behavior edits in the same commit.

## Migration order

1. **Done** (): document the model + move one representative, low-risk target
   (`coverage`) to `Neutrino/GenCoverage.h`.
2. **Done**: the remaining analysis/agent targets — `capability`, `security`,
   `views`, `slot` — now own `Neutrino/Gen{CapabilityModel,Security,Views,Slot}.h`.
   (At the time, `SecurityTarget.cpp` still depended on the shared
   `hasSecurityViolations` predicate and `SlotTarget.cpp` on `sha256OfFile`; those
   shared helpers were split out in step 4, so they now include `Neutrino/Validate.h`
   and `Neutrino/Manifest.h` respectively.)
3. **Done**: the backend validators `solidity`/`postgres` now own
   `Neutrino/Gen{Solidity,Postgres}.h` (their internal `generate*` helpers moved
   too). **Every target now owns its header**; `Backends.h` carries no target
   declaration. `neutrino-equiv` includes both target headers for the cross-backend
   run; at the time it still kept `Backends.h` for `sha256OfFile`/`validateScenario`,
   which step 4 moved to `Neutrino/Manifest.h` / `Neutrino/Validate.h`.
4. **Done**: the shared non-target surface is split out and `Backends.h` is
   **retired** — `validateScenario`/`hasSecurityViolations` → `Neutrino/Validate.h`,
   `sha256OfFile`/`writeManifest` → `Neutrino/Manifest.h`, the registry types
   (`EmitFn`/`TargetSpec`/`targetRegistry`/`findTarget`/`targetUsageList`) →
   `Neutrino/Targets.h`. Each translation unit now includes only the focused headers
   it uses.

The modularization is complete: every target owns a `Gen<Target>.h`, the registry
owns `Targets.h`, validation owns `Validate.h`, run tooling owns `Manifest.h`, and
the kitchen-sink `Backends.h` is gone. Each step was its own small,
behavior-preserving PR `Refs `.

## Target discovery is programmatic and enforced ()

The registry is not just the dispatch source — it is the **discovery** source:

- **`neutrino-gen --list-targets`** prints the registered targets (one per line)
  straight from `targetRegistry()`, so tools/agents/CI enumerate targets from the one
  table instead of scraping usage text. An unknown `--target` is refused with
  `targetUsageList()` (also registry-derived) and a non-zero exit.
- **Self-test `[62]`** (`test/run_cpp_tests.sh`) pins this end to end: every target from
  `--list-targets` routes through the registry to a real emit (its `manifest.json`
  records that target), and an unregistered target is refused with a registry-derived
  list. So a target cannot exist that the registry doesn't know, nor be registered yet
  unreachable. (The per-target byte-stability fixtures + R0 `[43]` keep the *outputs*
  frozen across boundary moves.)

## Structured emitter for target-language text (, parent  E1)

Spec renderers that emit a **target language as text** (SQL, Solidity) historically
hand-assembled output with `+`/`push_back` string concatenation: they owned newline
joins, indentation, and block framing inline, which is where formatting bugs and
irregular indentation crept in. `` introduces a **typed representation + printer**
boundary (`include/Neutrino/SqlEmitter.h`, `lib/backends/postgres/SqlEmitter.cpp`, `neutrino::sql`) that
renderers build against instead:

- **Typed representation** — a small closed node set (`Stmt{Line,Blank,If}`,
  `Function`, `Document`) that models the block/line STRUCTURE. Expression and
  predicate text still comes from the existing lowerers (`toSql`/`guardToSql`) and is
  carried verbatim; this is not a full SQL AST, and (per the E1 non-goal) not
  TableGen.
- **Printer** — `sql::print(Document)` owns the framing (`CREATE OR REPLACE
  FUNCTION`/`RETURNS void`/`LANGUAGE plpgsql`/`DECLARE`/`BEGIN`), four-space
  indentation, and `IF … THEN`/`END IF;` blocks. The renderer no longer touches
  bytes.

`GenPostgresSpec::generatePostgresProcedureFromSpec` is the first consumer. The
migration is **byte-identical** — all four committed PostgreSQL goldens are unchanged,
which is the equivalence proof (the structured path == the old string-concat path);
`[43]`/`[81]` freeze it and `[96]` pins that the renderer builds `sql::Document`/
`sql::print` and that the framing lives in the printer (not re-inlined).

**Migration checklist** — remaining target-language *text* renderers to move onto the
boundary (JSON/document renderers already emit through `llvm::json::OStream`, which is
already structured — they are out of scope):

- [x] `GenPostgresSpec.cpp` — `procedure.sql` (this slice, ).
- [ ] `GenSoliditySpec.cpp` — the `.sol` contract renderer (~77 concat sites; the
      largest text renderer, the natural next slice — needs a Solidity-flavored
      representation or a shared core with the SQL one).
- [ ] `GenPostgresSpec.cpp` — the `run_db_test.sh` harness (`generatePostgresDbTestFromSpec`,
      a flat bash line buffer; lower value than the two contract/procedure renderers).

## The semantic-lowering boundary (M6 –) — the compiler rule

**Semantics normalize once; targets legalize; CodeText prints.**

1. **Normalize once ().** A coordination's semantics are normalized ONE time
   into the typed `CoordinationPlan` and VERIFIED there — the workflow key, the
   per-group balanced obligation, the guard partition, the lifecycle-terminal
   projection, the effect→attestation policy binding. `normalizePlan` (from the
   verified MLIR) and `planFromSpec` (from a capability-spec) yield a byte-for-byte
   identical coordination plan, so a decision cannot drift between producer and consumer.
2. **Targets legalize ().** A backend's contract-legalization TU
   (`SolidityModel.cpp`, `PostgresModel.cpp`) lowers the already-decided coordination plan into
   a **typed target model** (`SolidityContract` / `PgProcedure` with typed shapes —
   `Require`/`Transition`/`Emit`, `Raise`/`StatusWrite`/`LedgerUpsert`, typed
   params). Every target decision lives here; it reads NOTHING but the coordination plan.
3. **CodeText prints ().** `printSolidity` / `printPostgres` lay the typed
   model out via the CodeText / `sql::` emitters — layout only, no decision.

A legalization TU must therefore **never reach back into the raw capability-spec
(JSON) to re-derive a shared semantic decision** — the first-effect workflow-key
selection, renderer-local balance/lifecycle/policy discovery, etc. that S1–S3
moved into the coordination plan. A new target-independent semantic field is added to the coordination plan
(and validated by `planFromSpec`/`assemblePlan`), not re-read in a renderer.

**Enforcement (, S4).** The boundary is durable on two axes:

- **Source** — `scripts/gates/check_anti_inference.py` (the `anti-inference-boundary`
  CTest + the `anti_inference_test` fast check). It is **fail-closed for new code**.
  The governed backend source set — TUs (from the extraction manifests) **and every
  backend-dir header** — is classified: each source is either on a *reviewed*
  JSON-legitimate allowlist (the ingress entry, the shared spec-decode primitives +
  seam header, the test harnesses, the oracle policy renderer) or it must be
  structurally **JSON-free** (names no `llvm::json` type, includes no JSON header, so
  `spec["x"]` / `spec.find(...)` / `getString(...)` / a helper are structurally
  impossible — not merely unmatched by an access-syntax list). Independently, the
  coordination **decisions the coordination plan already makes** (first-effect workflow-key
  selection, renderer-local balance / lifecycle discovery) are forbidden in **every**
  governed source, allowlisted or not, through the full CI path. Completeness is
  **derived from the authoritative schema** (`docs/schemas/capability-spec.schema.json`):
  the schema is walked recursively, local `$defs` refs are followed, combinators
  are descended, known expression/operand/lifecycle subtrees are consciously
  pruned, and every discovered path is classified `normalized` / `structural` /
  `meta` with an equality check (a new schema field at any depth must be triaged).
  Each `normalized` field must then be parsed by the coordination-plan contract
  with an object-scoped getter witness (`spec.getArray("effects")`,
  `eo->getObject("when")`, `term->getString("success")`, etc.), so an unrelated
  `"name"` read or dead string literal cannot satisfy the wrong field. The
  comment/char-literal scanner is reused from `check_cpp_policy.py` (), and
  `--selftest` is non-vacuous: it bites on injected JSON access, a
  char-literal-obfuscated read, a first-effect selection injected into an
  **allowlisted** source through `check_all()`, a legalizer declaration that must
  not count as an implementation, a dropped object-scoped parse + dead token, and
  new unclassified schema fields at top level, nested depth, and inside a
  `oneOf` branch.
- **Runtime** — the differential/generalism runner (`neutrino-equiv`, ; result
  classifier ; CI gate ; result/evidence contract ; see
  [TRACE_EQUIVALENCE.md](TRACE_EQUIVALENCE.md)) classifies a semantic bypass that
  slips past the source gate as `SILENT`/`BROKEN` and fails CI. This runtime axis
  is deliberately owned by the staged generalism runner, not by the lexical
  source gate; 's job is to keep backend source unable to reintroduce the
  bypass class without being caught before runtime.

(The test-artifact harnesses — `GenSolidityTest.cpp`, `PostgresDbTest.cpp` — render
a Foundry / docker test from the spec's STRUCTURAL surface, not the coordination
contract, so they are on the JSON-legitimate allowlist; making them
coordination-plan-driven too — the strict boundary — is a tracked follow-up.)

## Backend / policy module split ( D1–D7) — the physical library carve

The / subproject separation splits the renderer/model construction out of the monolithic
`NeutrinoEmit` into physical CMake libraries, so dependency direction is enforced by the *linker*, not
just convention. The **carve-out record  links to**:

- **D1 leaf ()** — `NeutrinoSpecContract`: the frozen capability-spec model (ValueModel , the
  typed Expr AST , LifecycleModel , JSON/hash, AttestationPolicy ). Links only
  `MLIRSupport`. Everything below depends *only* on this.
- **D3 backend ()** — `NeutrinoBackendPostgres` (`GenPostgresSpec.cpp` + `SqlEmitter.cpp`).
- **D5 policy/profile models ()** — `NeutrinoSecurityPolicy` (`GenSecuritySpec.cpp`) and
  `NeutrinoCapabilityProfile` (`GenCapabilityModelSpec.cpp`). *(No lifecycle-projection target: the
  LifecycleModel already lives in the leaf and `GenSpec` owns the projection — no separable surface.)*
- **Oracle observer (M5 oracle S4, )** — `NeutrinoBackendOracle` (`GenOracleObserverSpec.cpp`):
  renders the deterministic off-chain serverless observers + aggregation (subscribe → canonicalize →
  keccak256 → secp256k1-sign, N from the binding) from the frozen attestation policy () + an
  `neutrino.observation-binding` (the concrete mock source + observer members; formalized by S5). A
  `--from-spec --binding`-only target (`neutrino-gen --target=oracle-observer`), deliberately NOT a
  view-routable registry row (). The runtime hasher/signer are injected, so the render is
  deterministic + byte-goldened with no CI crypto dependency.
- Each of these **leaf-only modules** `LINK_LIBS PUBLIC NeutrinoSpecContract` alone — no ProcedureView,
  no other backend — proven by a per-module **link-smoke** (`backend-postgres-smoke`,
  `security-policy-smoke`, `capability-profile-smoke`): a symbol leak fails to *link*.
- **Entry vs renderer.** The thin registry entries (`PostgresTarget.cpp` / `SecurityTarget.cpp` /
  the capability driver seam) emit the spec (via `CapabilitySpecTarget.cpp`, needing `ProcedureView` + validation),
  re-parse it, and call the leaf-only renderer/model; they stay in `NeutrinoEmit`, which links the
  leaf-only modules. (`SolidityTarget`/`SlotTarget` follow the same entry pattern.)

### Legacy / naive emit — retired, not relocated (D7 )

The split must not merely MOVE legacy hand-built emitters into smaller libraries:

- The naive raw-`ModuleOp` `sql`/`contract` projections (the byte-for-byte `emitters.py` port, incl.
  the no-upsert `UPDATE` bug) were **retired in ** — `neutrino-emit` fails closed on
  `--kind=sql|contract`. Backends render from the frozen spec, never a raw IR walk.
- `lib/Emit.cpp` is the **retained inspection-only adapter** (`events` / `symbols` for `neutrino-emit`
  + the LSP), explicitly named and scoped — it lives in `NeutrinoDialect` (core), never in a
  backend/policy module.
- **Guard:** `check_renderer_includes.py --selftest` (the `renderer-include-lock` CTest) discovers the
  leaf-only modules structurally from `lib/CMakeLists.txt` and asserts each holds ONLY migrated
  `Gen*Spec.cpp` renderers or an allowlisted support TU (`SqlEmitter.cpp`) — so a legacy/naive emitter
  cannot hide inside the new targets, and D2/D4's future modules join the gate with no edit.

## Adding a new backend

The boundary is deliberately small — adding a target is local:

1. **Header** — add `include/Neutrino/Gen<Target>.h` declaring only
   `std::vector<std::string> emit<Target>(const ProcedureView&, const Scenario&, const std::string& outDir);`
   (the uniform `EmitFn` signature).
2. **Implementation** — add `lib/targets/<Target>Target.cpp` (and to the `lib` build) consuming
   `ProcedureView` (+ shared `NeutrinoAnalysis`), writing artifacts, returning the
   written paths. Include only the focused headers it uses (`Validate.h`/`Manifest.h`
   as needed) — never a kitchen-sink header.
3. **Register** — add one `NEUTRINO_TARGET("<name>", emit<Target>, /*gated=*/…, /*scenarioFree=*/…)`
   row to the declarative source [`include/Neutrino/TargetRegistry.def`](../../include/Neutrino/TargetRegistry.def)
   (and `#include` the new header in `lib/emit/TargetRegistry.cpp`). The registry is
   **data-driven** from that `.def` via an X-macro (M5  D2, ) — dispatch stays
   type-safe (the `Emit` column is a real `EmitFn` symbol, not a string). `gated=true`
   for value-lowering/coordination/agent-facing artifacts (refused on hard security
   violations), `false` for analysis targets and the pre-render `capability-spec`;
   `scenarioFree=true` if the target renders from source/the canonical machine and takes
   no `--scenario`. **This one row is the only dispatch edit** — the CLI valid-target
   list, gating, `--list-targets`, usage strings, and emit dispatch all follow from it.
4. **Profile (executable backends only)** — a *scenario-bearing value-lowering* target
   (`gated && !scenarioFree`, e.g. `solidity`/`postgres`) MUST ship an
   `examples/target-profiles/<name>.target-profile.json`; analysis and scenario-free
   targets MUST NOT. Self-test `[97]` reconciles this correspondence against the `.def`
   metadata, so a target profile can neither orphan nor drift from the registry (without
   making the runtime profile responsible for C++ linkage).
5. **Tests** — `[62]` covers dispatch for free (it iterates `--list-targets`) and `[97]`
   pins the `.def`↔`--list-targets`↔profile reconciliation; add the target's byte-stable
   golden fixtures per [`ADDING_A_NEW_DOMAIN.md`](../domains/ADDING_A_NEW_DOMAIN.md) §4, and an
   IR/lowering FileCheck case per [`../test/ir/README.md`](../../test/ir/README.md).
6. **CLI/manifest contracts are frozen** — keep target names, manifest shape,
   diagnostics, exit codes, and file layouts stable (see Invariants above).
