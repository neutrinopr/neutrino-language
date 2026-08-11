# Trust & Late-Binding Contract (T0 freeze)

**Status:** Proposed freeze v1 — the shared contract Translator, Agents, and
Network implement against. Hosted here in the translator repo (the upstream
producer of `capabilityHash`, the binding policy, and the assurance label); it
needs **Network + Agents review** before it is final. Field names, assurance
tiers, the capability-hash bridge, and the four artifact schemas are intended to be
stable: additive extension is allowed, renames require a schema version bump.

**Source debates (in `neutrino-strategy/09-debates/`):**
`verification-trust-model-runtime-compliance.md`,
`verification-trust-model-implementation-spec.md`. **Boundary:**
`neutrino-strategy/04-architecture/capability-to-slot-boundary.md`.

This is the **T0 freeze** the spec requires *before* trust/binding work fans out
across the three repos — so an implementor can open one file and know exactly which
names, hashes, and assurance labels every repo uses. JSON Schemas live in
[`schemas/`](../schemas); examples in [`schemas/examples/`](../schemas/examples).

---

## 1. Four terminology decisions (the freeze that prevents divergence)

The collisions that would otherwise be baked differently into three repos, decided
here once.

### 1.1 Assurance tier ≠ conformance level ≠ maturity level

Three **orthogonal** axes; never conflate them in one field:

| Axis | Question | Values | Lives on |
|------|----------|--------|----------|
| **Assurance tier** | How strong is the *evidence lineage* of a realization? | `A1`–`A4` | a realization / binding (`assuranceTier`) |
| **Conformance level** | How well does a backend *support a semantic feature*? | `Verified`/`Full`/`Partial`/`Emulated`/`Experimental`/`Unsupported` | a separately versioned package-owned declaration (not capability-model v1) |
| **Maturity level** | A backend's overall *ceiling* from its language-level support? | `Level 0`–`3` | a backend (derived) |

The catalog-derived capability-model v1 emits none of these three claims. Its
consumer gate instead authenticates the exact verified profile facts, model
set, and published bytes. Any future assurance/conformance/maturity declaration
must remain separately versioned and package-owned.

### 1.2 Capability vs Participant vs Slot

- **Capability** — the compiled coordination contract (operations, compensation,
  value model, declared participants). `capabilityId` + `capabilityVersion`,
  fingerprinted by `capabilityHash`.
- **Participant** — an abstract role declared in the DSL (L1); the translator's
  unit of authorization. Binding policy is authored *on a participant*.
- **Slot** — the network/runtime *realization* of a participant's coordination
  surface. The translator has no "slot" type; `slotId` names the realization of a
  participant. **Mapping:** a flexible (`to_be_bound`) participant becomes a
  late-bound **slot** at realization time; its `authorizedBinder` / `runtimes` /
  `minAssurance` are that slot's binding policy.

### 1.3 Binding policy vs binding receipt vs deployment binding

- **Binding Policy** — *agreement-time constraint* (who may bind, allowed runtime
  families, minimum assurance, evidence profile, rebinding). Authored on a
  participant, **emitted by the Translator** ([`BINDING_POLICY.md`](BINDING_POLICY.md)).
- **Binding Receipt** — *realization-time authorization*: a signed statement that a
  concrete runtime is bound to a slot, **validated against** the policy. Produced in
  the **Agents** workflow; identified by `bindingId`.
- **Deployment binding** — the pre-existing operational concept in
  `neutrino-build-tools/runtime/` (deployed release + target, operational state only).
  It is **not** a Binding Receipt — qualify it as *deployment binding* /
  `releaseDigest`, never `bindingId`.

### 1.4 Hashes & identifiers are canonical (§3), and the hash bridge is pinned (§4).

---

## 2. Assurance Tiers (A1–A4)

| Tier | Name | Meaning | Who attests |
|------|------|---------|-------------|
| **A1** | Compiler Attested | Artifact chain hash-linked to Canonical IR (`capabilityHash` + IR). | Translator (static generation). |
| **A2** | Realization Validated | A concrete realization passed equivalence/conformance vs the IR. | Agents/Network at realization. |
| **A3** | Runtime Evidenced | Live execution emits signed evidence linked to agreement, IR, binding, runtime identity. | Network/runtime. |
| **A4** | Formally Proven | Optional proof path (PCC/ZKP) for systemic-risk capabilities. | Specialized. |

**Honesty rule (frozen):** a component may only *attest* a tier it can produce
evidence for. Static generation attests **A1 only**; A2 is *attainable* but
attested at realization; A3/A4 are produced off-translator and never claimed by it.
Per-tier `status` ∈ `attested` | `attainable` | `not-claimed`; a headline
`assuranceTier` MUST equal the highest **attested** tier. Capability-model v1
does not carry or attest this field; its gate must not infer it from profile
support facts.

---

## 3. Canonical field-name registry

camelCase in JSON; the Fabric protobuf uses snake_case as noted. Renaming requires
a schema version bump.

| Name | Type | Meaning |
|------|------|---------|
| `agreementHash` | hex sha256 | hash of the signed agreement/DSL source (canonical). |
| `irHash` | hex sha256 | hash of the Canonical IR (canonical textual MLIR). |
| `capabilityId` | string | capability identity, e.g. `coordinate.<procedure>`. |
| `capabilityVersion` | string | DSL/semantic version, e.g. `1.0.0`. |
| `capabilityHash` | hex sha256 | fingerprint of the wire contract (§4). |
| `schemaHash` | 32 bytes | Fabric `EnvelopeHeader.schema_hash`; `= hexDecode(capabilityHash)` (§4). |
| `slotId` | string | identity of a slot (realization of a participant). |
| `bindingId` | string | identity of a Binding Receipt. |
| `implementationDigest` | hex sha256 | digest of the concrete realization (bytecode/image/package). |
| `runtimeIdentity` | string | stable id of the runtime holding a binding (key/cert-anchored). |
| `assuranceTier` | `A1`–`A4` | highest *attested* assurance tier of the subject. |
| `authorizedBinder` | string (org) | org permitted to bind a slot (policy). |

`agreementHash`, `irHash`, and `capabilityHash` are **distinct** (agreement, IR,
and wire-contract fingerprints serve different audiences — debate open-question O1
resolved: keep all three). `schemaHash` is **not** a separate hash: it is the byte
form of `capabilityHash` (§4).

---

## 4. The `capabilityHash` ↔ `schema_hash` bridge (pinned)

The single cross-rail identity handoff. **Frozen method** — already implemented in
the translator `capability.lock` and consumed by the Fabric `EnvelopeHeader`:

```
capabilityHash = lowercase-hex( sha256(
    concat( sorted( basename + ":" + sha256(file) + "\n"
            for file in wire-contract files ) ) ) )

wire-contract files = capability.json, operations.json,
                      compensation.json, transcript.json
                      (envelope.schema.json EXCLUDED — console/docs artifact)
```

| Translator (`capability.lock`) | Fabric (`EnvelopeHeader`, `proto/neutrino/envelope/v1`) |
|--------------------------------|---------------------------------------------------------|
| `capability` (= `capabilityId`) | `capability_name` (field 12) |
| `capabilityVersion` | `capability_version` (field 13) |
| `capabilityHash` (hex) | `schema_hash` (field 14) **= the 32 bytes of `hexDecode(capabilityHash)`** |

**Conformance pin.** The network golden vector
`conformance/vectors/envelope-v1/04-signed-capability-bridge.json` carries a signed
Fabric `EnvelopeHeader` whose `schema_hash_hex` (and `capability_version`) are the
M1 reference capability's (`coordinate.core_sponsored_offer@0.1.0`)
`capabilityHash` / `capabilityVersion`. Enforcement is **layered**:

- **Translator half** — `capability.lock.capabilityHash` is byte-pinned by the
  slot-fixture self-test (`[13]`), which runs in `build-and-test.yml`. The
  translator cannot silently change the value the network depends on.
- **Network half** — the vector is validated by the network conformance suite.
- **Cross-repo equality** — the cross-rail "bridge" rail
  (`scripts/rails/cross_rail_dry_run.py`) asserts the vector's `schema_hash_hex` +
  `capability_version` equal the translator `capability.lock`, and **fails** on
  mismatch or a missing required vector. It runs in `make acceptance`, i.e. in any
  environment where **both** repos are checked out side by side.

> **Not yet guaranteed by per-repo GitHub CI.** `build-and-test.yml` runs only
> `make build` + `make test` (no sibling network checkout), so the *cross-repo
> equality* is enforced today only in the integration/acceptance environment, not
> in the translator's standalone CI. Closing that needs a CI job that checks out
> the (private) `neutrino-network` repo — pending a read token / repo-visibility
> decision (tracked).

---

## 5. Artifact contracts

Each has a JSON Schema in [`schemas/`](../schemas) + an example in
[`schemas/examples/`](../schemas/examples). "Status" marks what already exists.

- **5.1 Binding Policy** — `schemas/binding-policy.schema.json`. Agreement-time
  constraint on a flexible slot. **Status: partially implemented** — the translator
  emits `{ mode, runtimes, minAssurance, authorizedBinder }` in slot
  `capability.json` (covered by `capabilityHash`). `evidenceProfile`, `rebinding`,
  `compliance` are reserved and not yet emitted.
- **5.2 Binding Receipt** — `schemas/binding-receipt.schema.json`. Realization-time
  authorization, signed by `authorizedBinder`; links `agreementHash`, `irHash`,
  `capabilityId`/`Version`, `slotId`, `bindingId`, `implementationDigest`,
  `runtimeIdentity`, `assuranceTier`, validity window, signer. **Status: schema only**
  (Agents/T2).
- **5.3 Runtime Evidence Envelope** — `schemas/runtime-evidence-envelope.schema.json`.
  A3 record linking runtime behavior to `bindingId`, `irHash`, `capabilityId`,
  `runtimeIdentity`, a `sequence` + `previousEvidenceHash`→`evidenceHash` chain, and
  a `verificationResult`. **Status: schema only** (Network/T3; SHOULD reference the
  existing Fabric transcript, not re-invent it).
- **5.4 Component Compatibility Manifest** —
  `schemas/component-compatibility-manifest.schema.json`. Versions/digests of every
  component that affects interpretation/verification. **Status: schema only.**

---

## 6. Implementation status by repo (today)

- **Translator** — binding-policy DSL and static evidence inputs; capability-model
  v1 carries no `assuranceTier`
  (`binding="to_be_bound"`, `bind_runtimes`, `bind_min_assurance`) + slot emission +
  IR verifier; `capability.lock.capabilityHash`. (translator –.)
- **Network** — Fabric `EnvelopeHeader{capability_name,capability_version,
  schema_hash}`; conformance runner + vectors.
- **Agents** — stateless capabilities (`generate.*`, `validate.equivalence`,
  `test.foundry`); no binding-receipt workflow yet (consumes §5.2).

---

## 7. Ownership & change control

This file + `schemas/` are the source of truth for the contract; repo-local DTOs
(Kotlin/TS/C++) are generated or hand-written **to match**. Changes are additive by
default; any rename/semantic change bumps the relevant schema's `$id` version and is
recorded here. The contract is hosted in the translator repo for now; if a neutral
home is preferred, move the directory wholesale (the names/hashes do not change).
