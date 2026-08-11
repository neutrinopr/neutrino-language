# Target profiles & the capability-spec legality gate (M5 WP4)

A **target profile** declares which semantic primitives a rendering target (solidity, postgres,
…) supports. The canonical capability-spec's `targetRequirements` are matched against a profile **before
rendering**: an unsupported feature **fails closed** with a machine-readable legality diagnostic
that names the feature, the originating primitive, and its source line. This is the legality gate
the renderer-migration work packages (WP5/, WP6/) depend on.

Profiles key on semantic **features**, never domain/contract labels — the same feature strings
the capability-spec emits (`value_category:money`, `effect:debit`, `invariant:balanced`, `binding:flexible`,
`topology:org_coordination`, …). This is the "profiles match semantic primitives, not domain
labels" acceptance, and it is what lets the classification `profileId` shapes () and the capability-spec
requirements () meet on common ground.

> **Naming (; wire rename ):** the translator emits a compiled **capability-spec**; "spec"
> is the network/runtime concept.  hard-cut (pre-v0.4.0) the wire tokens to
> `neutrino.capability-spec`, `capability-spec.json`, `capability-spec/v1`, `--target=capability-spec`,
> `specHash`, and the `spec.*` diagnostic family (`capabilityHash` unchanged) — a bare `spec` in a
> code font is always one of those current tokens. See
> [CAPABILITY_SPEC.md § Naming](../spec/CAPABILITY_SPEC.md#naming-capability-spec-is-the-wire-identity-279).

## Pieces

| Piece | What |
| --- | --- |
| [`schemas/target-profile.schema.json`](../schemas/target-profile.schema.json) | the normative profile shape (`neutrino.target-profile`, schemaVersion 1; fail-closed). |
| [`schemas/backend-package-target-profile-v1.schema.json`](../schemas/backend-package-target-profile-v1.schema.json) | the additional closed admission contract for a verified backend package's embedded `profileSummary`; it does not narrow target-profile v1. |
| [`examples/target-profiles/*.target-profile.json`](../../examples/target-profiles) | the committed `solidity` + `postgres` profiles. |
| [`scripts/validators/validate_target_profile.py`](../../scripts/validators/validate_target_profile.py) | stdlib validator for the profile **shape** (+ AD3 versioning invariants). |
| [`scripts/validators/validate_backend_package_target_profile.py`](../../scripts/validators/validate_backend_package_target_profile.py) | stdlib validator for the stricter package-admission contract. |
| [`scripts/gates/check_spec_legality.py`](../../scripts/gates/check_spec_legality.py) | the **legality gate**: `capability-spec.json × profile → fail-closed diagnostics`. |

```sh
# validate a profile shape
python3 scripts/validators/validate_target_profile.py examples/target-profiles/solidity.target-profile.json
# gate a spec against a target profile (exit 0 legal / 1 illegal)
python3 scripts/gates/check_spec_legality.py path/to/capability-spec.json --profile examples/target-profiles/solidity.target-profile.json
```

## The profile

- `profileId` (`<family>.<name>.v<major>`) + `profileVersion` — the **stable shape identifier**
  used for matching; its `v<major>` must equal `profileVersion` (AD3).
- `target`; `runtimeFamily` (`on_chain` / `relational` / `off_chain` — *where* it runs);
  `executionMode` (`deterministic` / `simulated` / `real` — the assurance-relevant axis,
  : a `simulated` backend must not be treated as carrying real-money assurance).
  These are two **distinct** axes (runtime family vs execution mode); the committed
  solidity/postgres profiles are `simulated` today (validated in forge/psql harnesses, not
  production custody).
- `supportedFeatures` — the feature set the target can render.
- `unsupportedConstructs` — features explicitly, documentedly **denied** (a distinct diagnostic
  from a merely-absent feature); disjoint from `supportedFeatures`.
- `fallbackPolicy` — `fail_closed` or `advisory`: what to do for an **optional** unmet requirement.
  The spec's per-requirement `fallback` (reserved null forward-space from ) is not consumed
  yet; when it is, a **materialized requirement-level `fallback` overrides the profile default**
  (recorded here so the precedence is a decision, not an ad-hoc choice later).

### Verified backend-package admission

The published target-profile v1 contract remains the compatibility baseline described above:
`capabilitySpecVersion` and `semanticProfile` are optional at shape validation, and positive
contract versions are forward-compatible. A `neutrino.backend-package/1` descriptor is a narrower
trust boundary. Its embedded `profileSummary` is admitted under the separate, versioned
`backend-package-target-profile/v1` contract, which requires both version blocks, pins their
currently supported versions, requires canonical feature ordering, and freezes `profileVersion`
to unsigned 32-bit values and semantic limits to signed 64-bit JSON integers. The descriptor also
binds `profileId` and `target` to its own identities. These additional package requirements do not
change which standalone target-profile v1 documents the shape validator accepts.

## Matching (the gate)

For each spec requirement (`feature`, `primitive`, `source`, `requirement`):

- `feature ∈ supportedFeatures` → **legal**;
- `feature ∈ unsupportedConstructs` → **`legality.unsupported_feature`** (explicit denial);
- otherwise, if the requirement is **optional** and `fallbackPolicy = advisory` →
  **`legality.advisory`** (a warning, allowed); else **`legality.unsupported_feature`**.

Diagnostics are `{code, severity, message, feature, primitive, source}` under the stable
`legality.*` family ( taxonomy), **root-cause ordered** (earliest source line first, then
feature). `legality.bad_input` fails closed on a malformed spec/profile — the gate never crashes
and never silently coerces a schema-invalid piece.

**Taxonomy note ():** `legality.*` is a stable code family alongside `spec.*` () and
`classification.*` (); these must be registered in the shared failure taxonomy ().
Ordering is two-level: **precedence across families** is the taxonomy's `orderByRootCause`, while
**within** `legality.*` the gate orders by source line — the two are complementary, not competing.

## Versioning (AD3)

Recorded in the [M5 addendum §AD3](../process/M5_DECISIONS_ADR_ADDENDUM.md); enforced by the profile
validator + the  compatibility surface:

- capabilities validate against a **pinned** profile version through the  surface;
- **widening** support (adding features) is a **minor** bump; **narrowing** is a **major** bump
  that **re-gates** every capability that matched the prior profile;
- an **unknown/unsupported** profile version fails closed before renderer entry.

## Where it runs

- **fast tier** (`[fast/10]`) — profiles validate (+ negatives), every scenario-bearing sample
  capability-spec is legal against both profiles, source-only fixtures have every primitive
  explicitly accounted for as supported or unsupported, and a crippled profile fails the gate
  closed. No build. A fixture is source-only exactly when it has no committed scenario.
- **full tier** (`[77]`, `make test` → release gate) — the profile validator mirrors the schema;
  each committed profile negative hits its exact code; legality is checked for every
  scenario-bearing sample capability-spec against both profiles; source-only classification and
  explicit unsupported accounting have non-vacuous floors; a missing feature fails closed with
  feature+primitive+source; advisory vs `fail_closed` fallback; bad input fails closed.

## Scope note

The spec's `targetRequirements` (what a profile is matched against) are **derived from the typed
spec**: value categories from the / typed inputs/computes, effect kinds from the ledger
legs, `invariant:balanced` from the assert, and topology from participants/allow policy — so the
whole chain is source → spec → requirement → legality, with a source line at every step.

Scenario-bearing samples exercise the backend-admissible surface and must remain legal against
both committed profiles. Source-only samples may witness portable compiler semantics before a
backend claims realization; their primitives still belong to the closed glue vocabulary and must
be explicitly classified by every profile. `value_extension:temporal` narrowly identifies declared
temporal extension values and is supported by both profiles. Other extension types remain
`value_category:extension`, explicitly unsupported by both profiles; a genuinely unknown term still
fails glue validation.

**"Before renderer entry" — current state.** The gate is now **wired into `neutrino-gen`
in-process**, as the strategy's end state required: pass `neutrino-gen --profile=<target-profile.json>`
and a gated render matches the capability-spec's `targetRequirements` against the profile **before
renderer dispatch**, failing closed with a stable exit code (`EXIT_LEGALITY = 6`, alongside the
security gate) and a machine-readable `legality.*` diagnostic — no artifact is emitted for a
capability the target cannot legally realize. The in-process C++ gate is
[`lib/SpecLegality.cpp`](../../lib/SpecLegality.cpp); [`scripts/gates/check_spec_legality.py`](../../scripts/gates/check_spec_legality.py)
is the deterministic **parity/reference** twin (the two must agree — self-test `[84]` asserts they
accept/reject the same capability-spec × profile, so the `legality.*` codes are `DiagEmitter::Both`).
When no `--profile` is supplied the gate is skipped (nothing to gate against); CI/release supply it.
This in-`gen` implementation is the **D10 resolution**: it gives the matching semantics
(default-deny, fallback policy) a compiler owner.

`neutrino-gen --target=capability` now consumes the already verified target
catalog and projects one closed v1 model per profile. Core has no hand-authored
backend support table or fallback. Every model binds the exact profile digest,
complete catalog identity, and source capability witness; the independent
capability-claims gate checks that bijection and the published bytes.

## Contract-version pin: `capabilitySpecVersion` (R3, )

A target profile consumes the **capability-spec** contract, so it must **pin the contract version
it was authored against**. Every profile declares:

```json
"capabilitySpecVersion": "v1"
```

This pins the translator's emitted `kCapabilitySpecVersion` (VersionInfo.h / `--version-json`, the
`vN` of the [`capability-spec` schema `$id`](../schemas/capability-spec.schema.json)) — **distinct from
`profileVersion`**, which is the profile's own revision.
[`scripts/gates/check_artifact_pins.py`](../../scripts/gates/check_artifact_pins.py) **fails closed** when the pin
is missing (`compat.pin_missing`) or mismatches the emitted contract version
(`compat.capability_spec_mismatch`), and keeps the emitted version in lockstep with the schema
`$id` (`compat.contract_drift`). When the capability-spec contract version bumps, bump
`kCapabilitySpecVersion` **and** every profile's `capabilitySpecVersion` in the same change — the
gate (`[fast/17]`, full-tier `[52b]`) enforces it. This is the "which contract version did this side
artifact validate against" pin the note above anticipated (it also covers domain dialects — see
[DOMAIN_DIALECT.md](../domains/DOMAIN_DIALECT.md)).

See [`M5_DECISIONS_ADR.md`](../process/M5_DECISIONS_ADR.md) (D1/D8), the [addendum](../process/M5_DECISIONS_ADR_ADDENDUM.md)
(AD3 versioning, AD4 gates), [`CAPABILITY_SPEC.md`](../spec/CAPABILITY_SPEC.md) (the `targetRequirements`
this matches), and [`SOLIDITY_CLASSIFICATION.md`](SOLIDITY_CLASSIFICATION.md) ().

## The `semanticProfile` block — coordination-plan legality ()

The `supportedFeatures`/`targetRequirements` matching above governs the OPEN spec-feature namespace
(`value_category:*`, `topology:*`, `binding:*`, …). A profile ALSO carries an optional
**`semanticProfile`** block declaring which normalized-transition **semantic requirements** — derived
from the *verified [CoordinationPlan](../../include/Neutrino/CoordinationPlan.h)*, never from source or
spec text — the target realizes. The **coordination-plan legality gate**
([`PlanLegality.h`](../../include/Neutrino/PlanLegality.h)) matches a coordination plan's requirements
against this block **before evaluator/lowering dispatch** and fails closed with the `legality.*`
taxonomy. It is
**one requirement derivation, one matcher, many profile sources**: the rigid Solidity/PostgreSQL
lowerings match their file-backed block; the reference evaluator ([](../spec/COORDINATION_EVALUATOR.md))
matches a **built-in `reference.v3` profile** that supports the complete closed vocabulary — there is
no separate evaluator legality path.

```json
"semanticProfile": {
  "version": 3,
  "features": ["authorization:explicit", "effect:debit", "effect:credit",
               "guard:conditional", "invariant:balanced", "attestation:quorum",
               "terminal:success", "terminal:aborted", "terminal:contested",
               "replay:idempotent", "time:explicit_input",
               "identity:explicit_instance_key"],
  "limits": { "maxExpressionDepth": 16, "maxEffects": 32, "maxEffectGroups": 16,
              "maxAttestations": 8, "maxComputes": 32, "maxOperationSteps": 64 }
}
```

- **`version`** pins the **distinct** semantic-profile contract (`VersionInfo.h`
  `kSemanticProfileVersion`, now **v3** — the registry gained `identity:explicit_instance_key` and
  `coordination:evidence_acceptance`) — NOT `schemaVersion`, `profileVersion`, or the tool version. A
  **missing or unknown** version fails closed (`legality.unknown_profile_version`) before dispatch.
- **`features`** are the supported members of the **CLOSED** semantic-requirement registry
  ([`SemanticRequirements.h`](../../include/Neutrino/SemanticRequirements.h) `knownSemanticFeatures`):
  authorization mode, ledger-effect forms, guards, the balance invariant, attestation gating,
  lifecycle/terminal **shapes**, replay, `time:explicit_input`, an **`identity:explicit_instance_key`**
  (a coordination that declares its instance key independently of any effect), and
  **`coordination:evidence_acceptance`** (an effectless evidence-only coordination — realized by the
  reference evaluator AND, as of , by the rigid Solidity/PostgreSQL lowerings, which advertise it
  and render a zero-ledger acceptance keyed by the instance key; a profile that does NOT advertise it
  still refuses a zero-value coordination before dispatch). A required feature absent here is refused (`legality.unsupported_feature`);
  a coordination-plan requirement OUTSIDE the registry — a future/unregistered coordination-plan node —
  is refused (`legality.unknown_requirement`) **even by the reference evaluator**, so an unsupported
  node can never be silently realized.
- **`limits`** bound parameterized coordination-plan **metrics** — expression depth, effect/group/
  attestation/compute counts, and () **`maxOperationSteps`** (a genuine bounded-step / compute-cost
  measure — the total number of operations across all computes + guards, distinct from the structural
  counts) — as numeric caps, not feature flags. A coordination plan exceeding a cap is refused
  (`legality.limit_exceeded`).

**Mandatory gating.** The coordination-plan legality gate ALWAYS runs for a plan-realizing target
(`coordination-trace`, `solidity`, `postgres`), on both the from-source and `--from-spec` paths. When
no `--profile` is supplied, a rigid lowering matches its **built-in default** profile
(`builtinSemanticProfile` — the authoritative C++ source of truth, dumpable via
`neutrino-gen --dump-semantic-profile=<target>`); a no-profile render therefore never means
"unbounded/all semantics". An explicit `--profile` overrides the default. The committed file profiles'
`semanticProfile` blocks are pinned to the builtin (a drift self-test diffs them) and to the published
contract version: `kSemanticProfileVersion` is emitted on the compatibility surface
(`neutrino-gen --version-json` → `semanticProfileVersion`), so a downstream author can discover which
contract the installed translator accepts.

**Independent evaluator support.** The reference evaluator declares its supported set independently of
the registry (`evaluatorSupportedFeatures`), so a registry addition the evaluator has not yet
implemented is caught by the drift self-test (and, until claimed, a coordination plan needing it is
refused) rather than auto-aliased into "supported".

**Scope ( + ).** The registry covers the normalized-transition semantics the coordination plan
carries: authorization, ledger-effect forms, guards, balance, attestation, terminal shapes, replay,
and () **explicit time** via a declared temporal-input inventory. The metrics add a genuine
bounded-**step** measure (`maxOperationSteps`) beyond the structural counts. Note a temporal type remains
`Extension` in the governed value model (ADR D5), while its narrow `value_extension:temporal`
realizability stays in the OPEN  spec-feature namespace, gated by `SpecLegality`; arbitrary
extensions remain fail-closed — nothing falls between the two gates.

Profiles advertise only what they truly realize. Both rigid renderers realize caller-supplied time via
`time:explicit_input`; neither substitutes ambient time. Their remaining asymmetry is structural:
**Solidity** realizes the on-chain `terminal:contested` dispute shape but carries **gas-bounded** numeric
limits (e.g. `maxExpressionDepth: 16`, `maxOperationSteps: 64`), while **PostgreSQL** omits
`terminal:contested` (relational settlement has no on-chain dispute machine) and permits deeper/larger/
more-step coordination plans. A contested coordination plan is a PostgreSQL-only refusal, while a
deep/wide one can be a Solidity-only refusal — each deterministic and diagnosed.
The
`semanticProfile` block is optional in the SHAPE validator (schema stays `schemaVersion: 1`); its
presence + version is enforced at the runtime gate, exercised by
[`test/ir/legality/plan_legality_deep.neu`](../../test/ir/legality/plan_legality_deep.neu) and
`unittests/PlanLegalityTest.cpp`.
