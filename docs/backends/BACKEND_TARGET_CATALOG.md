# Backend / Target / Artifact Catalog (M5)

The translator-owned M5 inventory of the compiler fleet: the frontend/IR surface, the generator
targets, the artifacts each emits, the sidecar validators + schema versions, the quality gates, and
each one's **maturity** and **primary entry point**. It feeds the  inventory and the
compatibility/release matrix, and is the human-readable companion to the machine-readable
[`COMPATIBILITY.json`](../../COMPATIBILITY.json) published for downstream fail-closed checks
().

The built-in target list is the declarative registry
[`include/Neutrino/TargetRegistry.def`](../../include/Neutrino/TargetRegistry.def); verified external
backend packages extend that list at runtime (surfaced
by `neutrino-gen --list-targets`); this catalog **must not drift** from it, and that is mechanically
enforced — the generator-targets table below is reconciled against the `.def` (every target's name and
its `gated`/`scenario-free` classification, plus the `oracle-observer` special case) by the
`catalog-registry` gate ([`scripts/gates/check_catalog_registry.py`](../../scripts/gates/check_catalog_registry.py),
), so a new target or a flipped flag fails CI until this table is updated. Since M4 the
backend/policy generators were split into leaf-only subprojects under `lib/backends/*` and
`lib/policy/*` (///) — the [Module map](#module-map--entry--leaf) below reconciles each
target with its ENTRY and LEAF, and the oracle attestation vertical (//) is new since M4.

Versions in this catalog (tool `0.2.0`, dialect `0.1.0`, and the artifact schema versions) are the
ones `COMPATIBILITY.json` publishes and CI pins to
[`include/Neutrino/VersionInfo.h`](../../include/Neutrino/VersionInfo.h); this doc does not restate them
as a second source of truth — see that file + `scripts/validators/validate_compatibility_manifest.py`.

## Maturity legend

| Maturity | Meaning |
|---|---|
| **production-ish** | exercised against a real external backend/runtime, not just a fixture (still pre-1.0) |
| **CI-gated** | committed goldens / self-tests enforce it on every build; fails closed on drift |
| **fixture-only** | works over committed reviewed fixtures / hash-pinned artifacts; not yet generalized |
| **simulated** | modelled deterministically; no real device/runtime/network involved |
| **planned** | designed / partially specified; not shipped |

The toolchain is **pre-1.0** (`toolVersion 0.2.0`) — surfaces are *stabilizing, not frozen* (see
[COMPATIBILITY.md](../process/COMPATIBILITY.md)). "production-ish" here means "validated against a real backend
tool," not "1.0 / GA."

## Frontend & IR surface

| Surface | Producer / entry point | Maturity | Notes |
|---|---|---|---|
| `.neu` source language (L1) | hand-authored → `neutrino-translate in.neu` (`make translate`) | CI-gated | one canonical `.neu` extension; conformance suite pins the grammar (self-test `[56]`, `test/conformance/`). See [NEU_LANGUAGE_SPEC.md](../language/NEU_LANGUAGE_SPEC.md). |
| L1 Core IR / textual `neutrino` MLIR dialect | `neutrino-translate` output; `neutrino-opt` runs the C++ verifier (`make verify`) | CI-gated | ODS/TableGen dialect (`0.1.0`); the IR is the asset. Byte-stable. |
| Event choreography (inspection) | `neutrino-emit --kind=events` (`make emit`) | CI-gated | INSPECTION only — the IR's expected fact ordering, a *view*, not a backend. The raw-MLIR `sql`/`contract` projections were retired in ; PostgreSQL/Solidity backends are the spec-derived `neutrino-gen` targets below. |

## Generator targets — `neutrino-gen --target=<T> [--scenario=s.json] <in.mlir|.neu> -o dir`

Every row is a `TargetRegistry.def` entry (in registry/CLI order), except the
descriptor-discovered `solidity` package and `oracle-observer` (see below).
**Gated** = a value-lowering / agent-facing artifact, refused for a capability with hard security
violations unless `--allow-insecure`; **analysis** targets (`security`/`capability`/`coverage`) and the
pre-render `capability-spec`/`coordination-plan`/`semantic-requirements` projections are **never** gated. **Scenario-free** = renders from
source / the canonical machine alone and takes no `--scenario`.

| `--target` | Emits | Gating · scenario | Maturity | Primary entry point |
|---|---|---|---|---|
| `solidity` | `solidity.json` + Foundry sources (`src/*.sol`, `test/*.t.sol`, `foundry.toml`) + `manifest.json` + `diagnostics.json` | gated · scenario | **production-ish** (verified external package; CI-gated golden byte-match `[43]` **+ real `forge test`** in the acceptance tier) | `make solidity-test` · `make acceptance`. `evm.v1` is the first deeply-proven backend profile. |
| `postgres` | `postgres.json` + `schema.sql` / `procedure.sql` / `reconciliation.sql` (+ `run_db_test.sh`) + `manifest.json` + `diagnostics.json` | gated · scenario | **production-ish** (CI-gated golden `[43]` **+ real docker+psql** run) | `make db-test` · `make acceptance` |
| `slot` | slot-aware subtree: `capability.json` + `capability.lock` (slot capability identity + hash), `operations.json`, `compensation.json`, `transcript.json`, `envelope.{schema,example}.json` | gated · scenario-free | CI-gated | `make slot` |
| `capability-spec` | `capability-spec.json` — the **frozen** pre-render semantic contract that is the SUBJECT of the security analysis (deliberately non-gated,  F2) and the input to every leaf renderer + `oracle-observer` | non-gated · scenario-free | CI-gated (lit `pipeline/capability_spec.test`; validator `validate_capability_spec.py`; [CAPABILITY_SPEC.md](../spec/CAPABILITY_SPEC.md)) | `neutrino-gen --target=capability-spec` (folded into `make capability` / `make capability-check`) |
| `agreement-identity` | `agreement-identity.json` — portable agreement identity envelope over the canonical semantic bytes | non-gated · scenario-free | CI-gated (lit `agreement_identity.test`; validator `validate_agreement_identity.py`; [AGREEMENT_IDENTITY.md](../spec/AGREEMENT_IDENTITY.md)) | `neutrino-gen --target=agreement-identity` |
| `coordination-plan` | `coordination-plan.json` — the target-neutral normalized semantic form the backend renderers consume (`planFromSpec`, ); a derived projection, not deployable | non-gated · scenario-free | CI-gated (lit `coordination_plan.neu`) | `neutrino-gen --target=coordination-plan` |
| `semantic-requirements` | `semantic-requirements.json` — the closed feature/primitive requirements and parameterized metrics derived by `coordinationPlanRequirements` | non-gated · scenario-free | CI-gated (lit `domain/semantic_requirements.test`; matrix selftest) | `neutrino-gen --target=semantic-requirements` |
| `coordination-trace` | `coordination-trace.json` — deterministic reference-evaluator trace for one scenario invocation | non-gated · scenario | CI-gated (lit `coordination_trace.neu`; [COORDINATION_EVALUATOR.md](../spec/COORDINATION_EVALUATOR.md)) | `neutrino-gen --target=coordination-trace --scenario=…` |
| `test-realization` | `test-realization.json` — scenario/test cases folded once, **outside** the capability hash (the home for the scenario data the spec excludes, ) | non-gated · scenario | CI-gated (`fast-test-realization`) | `neutrino-gen --target=test-realization --scenario=…` |
| `capability` | one versioned capability model per verified external target profile, named by the total target-identity mapping (with `solidity.json` / `postgres.json` preserved) | non-gated (analysis) · scenario | CI-gated | `make capability` / `make capability-check` |
| `coverage` | `coverage.json` (choreography/leg coverage) | non-gated (analysis) · scenario | CI-gated | `make coverage` |
| `security` | `security.json` (Capability Security Pass verdict) | non-gated (analysis) · scenario | CI-gated | `make security` — see [Quality gates](#quality-gates--validators) |
| `views` | per-participant narrowed views `<participant>.json` (Trust lane T5 — no obligation leakage across participants) | gated · scenario-free | CI-gated (self-test `[33]`) | `make views` |
| `oracle-observer` | serverless observer JS `observers/<set>/<observer-id>.js` + `observers/<set>/aggregate.js` — the S4 attestation observers () that sign the canonical claim the on-chain/DB quorum guard admits | **outside registry gating** · `--from-spec --binding` only | CI-gated (`oracle-observer-smoke`; observer↔guard parity `check_observer_guard_parity.py` ) | `neutrino-gen --target=oracle-observer --from-spec <capability-spec.json> --binding <observation-binding.json>` |

`oracle-observer` is deliberately **not** a `TargetRegistry.def` row (S4, ): the registry governs
`view + scenario → artifact` targets, whereas the observers render from the **frozen capability-spec's**
attestation policy + an [observation binding](#l2--l3-sidecar-validators--schemas). Because it takes the
`--from-spec --binding` branch directly in `neutrino-gen` — with no live `ProcedureView` — it has no
`TargetSpec::gated` classification and does **not** run the `hasSecurityViolations` lowering gate (nor
honour `--allow-insecure`); it validates the spec + binding JSON and renders. The security posture is
carried instead by the frozen spec's attestation policy and the observer↔guard parity check. If
observers should additionally be security-gated, that is a separate implementation gap, not a property
this catalog asserts today.

Cross-cutting run metadata: every `manifest.json` embeds the `translatorVersion` compatibility
surface ( subset) and honours `SOURCE_DATE_EPOCH` for reproducible envelopes.

## Module map — ENTRY → LEAF

Since M4 each value-lowering / policy generator is split (///, the M6 extraction path
[M6_EXTRACTION_PATH.md](../process/M6_EXTRACTION_PATH.md); structure doc
[BACKEND_GENERATORS.md](BACKEND_GENERATORS.md)) into:

- a built-in **ENTRY** in `lib/targets/<Target>Target.cpp` (the registry `EmitFn`) or
  an external package descriptor/protocol entry — consumes the finalized projection,
  produces the **frozen** `capability-spec`, and delegates; and
- a **LEAF** subproject that consumes **only** the frozen spec (never the IR), links only the approved
  bottom-of-graph shared leaves — `NeutrinoSpecContract`, plus `NeutrinoCodeText` (the language-neutral
  code-emitter substrate, /) where the renderer needs it (the Solidity / PostgreSQL / oracle
  backends do) — never core/IR or a sibling renderer, and is independently extractable (each carries an
  `EXTRACTION.md`).

Invariant: **target entry** means pre-waist compiler integration and is not an extraction unit;
**spec leaf** means post-waist renderer / policy / projection code and is extractable. Entry
implementations normally use `lib/targets/<Target>Target.cpp` names; retained public-core targets
instead keep their entry beside their typed model. Leaf renderers keep `Gen*Spec.cpp` names inside
their owning subprojects. Public `Neutrino/Gen<Target>.h` headers and `emit<Target>` function names
remain the stable C++ API surface.

| `--target` | ENTRY (`EmitFn`, consumes IR) | LEAF module (consumes frozen spec) |
|---|---|---|
| `solidity` | verified `neutrino.backend-package/1` descriptor → `neutrino.backend-protocol/1` (no core `EmitFn`) | `NeutrinoBackendSolidity` — [`lib/backends/solidity/`](../../lib/backends/solidity/EXTRACTION.md) (`GenSoliditySpec`, `GenSolidityTest`, `GenSolidityQuorumGuard`, `SolidityEmit`) |
| `postgres` | `lib/targets/PostgresTarget.cpp` (`emitPostgresProject`) | `NeutrinoBackendPostgres` — `lib/backends/postgres/` (thin `GenPostgresSpec` public entry + the split responsibility units `PostgresSpecModel` (decode) / `PostgresProcedure` (procedure+quorum schema) / `PostgresDbTest` (reconciliation/db-test), `SqlEmitter`) |
| `oracle-observer` | — (from-spec only; no IR-consuming ENTRY) | `NeutrinoBackendOracle` — `lib/backends/oracle/GenOracleObserverSpec.cpp` |
| `slot` | `lib/slots/SlotTarget.cpp` (`emitSlotProject`) | `NeutrinoSlotSpec` — `lib/slots/GenSlotSpec.cpp` |
| `views` | `lib/views/ViewsTarget.cpp` (`emitViews`) | `NeutrinoViewsSpec` — `lib/views/GenViewsSpec.cpp` |
| `capability` | checked driver-serialized catalog seam in `neutrino-gen` | `NeutrinoCapabilityProfile` — `lib/policy/capability-profile/GenCapabilityModelSpec.cpp` |
| `coverage` | `lib/coverage/CoverageTarget.cpp` (`emitCoverage`) | `NeutrinoCoverageSpec` — `lib/coverage/GenCoverageSpec.cpp` |
| `security` | `lib/security/SecurityTarget.cpp` (`emitSecurity`) | `NeutrinoSecurityPolicy` — `lib/security/GenSecuritySpec.cpp` |
| `capability-spec` | `lib/targets/CapabilitySpecTarget.cpp` (`emitCapabilitySpec`) | — (this IS the frozen spec; the contract module `NeutrinoSpecContract` every leaf links) |
| `agreement-identity` | `lib/targets/AgreementIdentityTarget.cpp` (`emitAgreementIdentity`) | — (agreement identity over canonical semantic bytes) |
| `coordination-plan` | `lib/targets/CoordinationPlanTarget.cpp` (`emitCoordinationPlan`) | — (normalization over the spec) |
| `semantic-requirements` | `lib/targets/SemanticRequirementsTarget.cpp` (`emitSemanticRequirements`) | — (compiler-owned requirement projection over normalized coordination) |
| `coordination-trace` | `lib/targets/CoordinationTraceTarget.cpp` (`emitCoordinationTrace`) | — (reference evaluator over the normalized coordination) |
| `test-realization` | `lib/targets/TestRealizationTarget.cpp` (`emitTestRealization`) | — (scenario-data companion) |

The link direction (leaf → the approved leaves `NeutrinoSpecContract` / `NeutrinoCodeText` only, never
leaf → core/IR or leaf → a sibling renderer) is enforced by `scripts/gates/check_link_direction.py`
(its `LEAVES` allowlist); the leaf-only extractability by
`scripts/gates/check_extraction_boundaries.py` + each `EXTRACTION.md`.

## Higher-level tools

| Tool | Purpose | Maturity | Entry point |
|---|---|---|---|
| `neutrino-equiv` | cross-backend equivalence harness (one source consistent across IR / events / Solidity / PostgreSQL) | CI-gated | `make equivalence` · `make equivalence-scheme` |
| `neutrino-bundle` | agent entry point: input bundle → output bundle (all targets); `--capabilities` advertises `translate.mlir` + `generate.{solidity,postgres}` (external `test.foundry`/`test.postgres`) | CI-gated | `make bundle` |
| Cross-rail dry run | `.neu` → slot bundle, checks agents/network/sim boundaries | CI-gated | `make cross-rail` (`cross_rail_dry_run.py`) |

## L2 / L3 sidecar validators & schemas

Schema-first sidecars (reviewable JSON artifacts + deterministic validators). Schema versions are
published in [`COMPATIBILITY.json`](../../COMPATIBILITY.json) `artifactSchemas` and pinned in CI.

| Artifact | Validator (entry point) | Schema | Maturity |
|---|---|---|---|
| L2 domain-semantics | `scripts/domain/validate_l2_domain_semantics.py --artifact F` | [`l2-domain-semantics.schema.json`](../schemas/l2-domain-semantics.schema.json) (v1) | CI-gated (self-tests `[58]`/`[60]`/`[65]`). **L2 source syntax is `planned`** — schema-first only for now (`languageLevels.future = [L2]`). |
| L2 branch-boundary compatibility | `scripts/domain/validate_l2_branch_compat.py --sidecar A --sidecar B` | same L2 contract (cross-sidecar `L2X-2xxx`) | CI-gated (self-test `[64]`) |
| L3 Binding Manifest | `scripts/validators/validate_binding_manifest.py` | [`binding-manifest.schema.json`](../schemas/binding-manifest.schema.json) (schemaVersion `1, 2`) | CI-gated (self-test `[42]`; `` diagnostic taxonomy) |
| Slot binding-topology | `scripts/validators/validate_binding_topology.py` | [`slot-binding-topology.schema.json`](../schemas/slot-binding-topology.schema.json) (v1) | CI-gated (self-test `[38]`) |
| Backend-profile catalog | (consumed by manifest validation) | [`examples/backend-profiles/catalog.json`](../../examples/backend-profiles/catalog.json) (schemaVersion 1) | CI-gated — `evm.v1` deeply proven; others simulation-only |
| Binding policy / receipt / runtime evidence | trust/late-binding contract | `binding-policy` / `binding-receipt` / `runtime-evidence-envelope` schemas (`v1`) | CI-gated — see [TRUST_LATE_BINDING_CONTRACT.md](../binding/TRUST_LATE_BINDING_CONTRACT.md) |

## Domain dialect / translation-map (Upper & Lower layer)

| Capability | Entry point | Schema | Maturity |
|---|---|---|---|
| Domain dialect (D1) — reviewed, hash-pinned vocabulary | `scripts/domain/validate_domain_dialect.py` | [`domain-dialect.schema.json`](../schemas/domain-dialect.schema.json) | fixture-only (reviewed + hash-pinned; self-test `[35]`) |
| Dialect expansion (D2) — sponsored-finance template → `.neu` (no parser syntax) | `scripts/domain/expand_dialect.py` | [`dialect-expansion-manifest.schema.json`](../schemas/dialect-expansion-manifest.schema.json) (v1) | fixture-only (Upper-layer; self-test `[39]`) |
| Dataset-analysis proposals (D1a) — proposal-only | `scripts/corpus/validate_domain_proposal.py` | domain-corpus / analysis-run / vocabulary-proposal schemas | fixture-only / proposal-only (self-test `[36]`) |
| Translation map (D4) — Lower-layer reviewed mappings (lossy visible, test-gated) | `scripts/rails/validate_translation_map.py` | [`translation-map.schema.json`](../schemas/translation-map.schema.json) | fixture-only (reviewed + hash-pinned; self-test `[41]`) |

## Quality gates & validators

| Gate | Entry point | Maturity | What it enforces |
|---|---|---|---|
| Capability Security Pass | `neutrino-gen --target=security` / `make security` | CI-gated | hard violations fail closed at lowering (unless `--allow`); analysis targets are never gated |
| Backend validation (real tools) | `scripts/validators/validate_backends.py` / `make validate` | production-ish | `solc --standard-json` (+ Slither / libpg_query when installed) |
| Cross-rail fixture catalog | `scripts/validators/validate_cross_rail_catalog.py` | CI-gated | paths + capability/policy/manifest + the `VersionInfo.h` compatibility surface match committed artifacts (self-test `[51]`) |
| Sample portfolio | `scripts/samples/validate_sample_portfolio.py` | CI-gated | the M3 sample portfolio + cookbook stay in sync (self-test `[71]`) |
| Compatibility checker (consumer) | `scripts/gates/check_compatibility.py --have … --require …` | CI-gated | a downstream component fails closed on a stale tool/dialect/schema combination (self-tests `[52]`/`[54]`) |
| Published compatibility manifest | `scripts/validators/validate_compatibility_manifest.py` | CI-gated | `COMPATIBILITY.json` pinned to `VersionInfo.h` + the committed schemas (self-test `[72]`, ) |
| Mutation / property / fork suites | `make mutation` / `make property` / `make fork` | CI-gated | semantic-drift, property, and capability-evolution coverage |

Test tiers: `make test-fast` (no-build validator smoke), `make test` / `make test-full` (build +
full C++/MLIR self-test suite — authoritative), `make acceptance` (full + real `forge`/`docker`
backend checks), `make native-build-gate`.

## Compatibility / release surface

- **Published compatibility manifest:** [`COMPATIBILITY.json`](../../COMPATIBILITY.json) +
  [`schemas/translator-compatibility-manifest.schema.json`](../schemas/translator-compatibility-manifest.schema.json)
  () — the machine-readable surface downstream agents/network/console fail closed
  against; the per-tool `--version-json` envelope is its runtime subset.
- **Version single source of truth:** [`VersionInfo.h`](../../include/Neutrino/VersionInfo.h) ().
- **Stability contract:** [COMPATIBILITY.md](../process/COMPATIBILITY.md).
- **Sovereign-lowering import envelope (M5):** [SOVEREIGN_LOWERING_ENVELOPE.md](SOVEREIGN_LOWERING_ENVELOPE.md)
  + [`schemas/sovereign-lowering-envelope.schema.json`](../schemas/sovereign-lowering-envelope.schema.json)
  () — the versioned, hashed manifest that lets a console/network consumer accept
  externally lowered artifacts without trusting the producing compiler; consumable by the existing
  `check_compatibility.py`.

## Gaps & deferrals

Maturity limitations are flagged per-row above. The items below are either **deliberate design
deferrals** (with a decision record) or **open tracked work**:

| Item | Kind | Where tracked |
|---|---|---|
| L2 domain-semantics **source syntax** (`domain_semantics { … }` block) | deliberate deferral — schema-first path chosen; the parser rejects the block by design until it earns its keep | decision record [L2_DOMAIN_SEMANTICS.md](../domains/L2_DOMAIN_SEMANTICS.md) (schema-first L2 delivered by the now-closed ); `languageLevels.future = [L2]` |
| Backend profiles beyond **`evm.v1`** | simulation-only today (deeper proving is future work) | backend catalog [`catalog.json`](../../examples/backend-profiles/catalog.json) (`maturity` per profile) |
| Domain dialect / translation-map **generalization** | fixture-only — reviewed + hash-pinned artifacts, not yet generalized past the sample corpus | this catalog (rows above); no open defect — advances with new reviewed domains |
| M5 domain fixtures (e.g. `CorePromoCampaign` L1/L2/L3) | open work (forward-looking) | internal-tracker |
| Sponsored-installment **released-M3 provenance** (authored reference artifacts today) | open follow-up (cross-repo, agents cookbook) | internal-tracker/neutrino- |

The version/compat surface **packaging** into releases (formerly a follow-up) landed via
 (closed) and is published as [`COMPATIBILITY.json`](../../COMPATIBILITY.json)
().

## References

- Inventory parent: internal-tracker/neutrino-.
- **Authoritative target registry:** [`TargetRegistry.def`](../../include/Neutrino/TargetRegistry.def)
  (`neutrino-gen --list-targets`) — this catalog annotates it and must not drift.
- Generator module boundaries: [BACKEND_GENERATORS.md](BACKEND_GENERATORS.md) · extraction path:
  [M6_EXTRACTION_PATH.md](../process/M6_EXTRACTION_PATH.md).
- Compatibility manifest: internal-tracker (+ [`COMPATIBILITY.json`](../../COMPATIBILITY.json)).
- Tool + make-target overview: [README.md](../../README.md) (Tools / Make targets / Backends).
