# Binding Manifest (T0/T2)

The **Binding Manifest** is the realized-translation input: it binds a capability's
late-bound (`to_be_bound`) slots to concrete runtimes at realization time. It is the third,
distinct artifact in the trust chain:

- **Binding Policy** — declared *in* the capability (`participant … binding = "to_be_bound"`,
  `bind_runtimes`, `bind_min_assurance`); surfaced in `capability.json` (covered by
  `capabilityHash`) and in the slot [binding-topology](../spec/SLOT_ARTIFACT_CONTRACT.md) (D1b);
- **Binding Manifest** — *this* artifact; the realized choice of runtime/assurance/binder for
  each late-bound slot, validated against the binding-topology before use;
- **Binding Receipt** — the agent-side record that a binding happened (owned by
  `neutrino-build-tools`); not part of the signed business agreement.

## The artifact

`neutrino.binding-manifest` ([schema](../schemas/binding-manifest.schema.json), reviewed example
`examples/binding-manifests/core_flexible_binding.binding.json`): a `capability` plus
`bindings[]`, each naming an `(organizationId, participantId, slotId)` triple from the
binding-topology and the realized `runtime` / `assurance` / `binder`.

## Validation

`scripts/validators/validate_binding_manifest.py --manifest M --binding-topology BT` checks each binding
against the slot binding-topology and is fail-closed:

- the `(organizationId, participantId, slotId)` triple must exist (an unknown name is rejected
  — this is the D1b/T2 guarantee "Binding Manifest rejected when it names an unknown
  organization/participant/slot");
- the slot must be `to_be_bound` (a `fixed` slot is not bindable);
- `runtime` must be in the slot's `allowedRuntimes`;
- `assurance` must be `>=` the slot's `minAssurance` (A1 < A2 < A3 < A4);
- `binder` must equal the slot's `authorizedBinder`;
- completeness: every `to_be_bound` slot is bound exactly once (no duplicates, no binding for a
  fixed/unknown slot), and the manifest `capability` matches the topology.

`run_cpp_tests.sh` `[42]` gates the reviewed (v1) manifest plus a negative per diagnostic
family, asserting each produces the expected `NEU-…` code (below); `[59]` does the same for the
L3 (schemaVersion 2) layer (see [L3 evolution](#l3-evolution-174)).

## Diagnostic taxonomy ()

Validation failures are normalized into a stable, machine-readable taxonomy so downstream
consumers (CI, agents, network admission, console) act on **codes**, not prose. This table is
the source of truth; `scripts/validators/validate_binding_manifest.py` keeps `TAXONOMY` in lockstep.

`--json` prints the report; the default prints a text summary derived from the same
diagnostics. Report shape:

```json
{ "schemaVersion": 1, "kind": "neutrino.binding-manifest-validation", "ok": false,
  "capability": "coordinate.…",
  "diagnostics": [
    { "code": "NEU-2001", "symbol": "ERR_NEU_ASSURANCE_BELOW_MINIMUM",
      "category": "security", "severity": "error", "message": "…",
      "capability": "…", "organizationId": "…", "participantId": "…",
      "slotId": "…", "bindingIndex": 0 } ] }
```

Target fields (`capability`, `organizationId`, `participantId`, `slotId`, `bindingIndex`) are
present where known. Exit `0` ok / `1` validation failures / `2` usage or I/O.

| Code | Symbol | Category | Meaning |
|------|--------|----------|---------|
| `NEU-1001` | `ERR_NEU_MANIFEST_MALFORMED` | topology | not a JSON object, wrong `kind`/`schemaVersion`, an unknown field (top-level or per binding), `bindings` not a non-empty array, a binding not an object, or an invalid binding-topology `kind` |
| `NEU-1002` | `ERR_NEU_CAPABILITY_MISMATCH` | topology | the manifest or topology `capability` is missing, or they do not match |
| `NEU-1003` | `ERR_NEU_SLOT_OWNERSHIP` | topology | a binding names a `slotId` not in the binding-topology, or its `(organizationId, participantId)` does not match the slot's |
| `NEU-1004` | `ERR_NEU_COVERAGE` | topology | completeness: a `to_be_bound` slot is bound more than once, or a `to_be_bound` slot is left unbound |
| `NEU-2001` | `ERR_NEU_ASSURANCE_BELOW_MINIMUM` | security | binding `assurance` is below the slot's `minAssurance` |
| `NEU-2002` | `ERR_NEU_BINDER_UNAUTHORIZED` | security | binding `binder` is not the slot's `authorizedBinder` |
| `NEU-2003` | `ERR_NEU_ASSURANCE_INVALID` | security | binding `assurance` is not one of `A1`..`A4` (or missing) |
| `NEU-3000` | `ERR_NEU_RUNTIME_NOT_ALLOWED` | runtime | binding `runtime` is not in the slot's `allowedRuntimes` (or missing) |
| `NEU-3001` | `ERR_NEU_SLOT_NOT_BINDABLE` | runtime | a binding targets a `fixed` slot (nothing to bind) |
| `NEU-3002` | `ERR_NEU_PROFILE_UNSUPPORTED` | runtime | (L3) the backend-profile catalog could not be loaded for a v2 manifest, `backendProfile` is not in the catalog, a **concrete** (non-`deferred`) binding's `runtime` does not match the profile's `runtimeFamily`, or a binding uses a hook field the profile does not support |
| `NEU-4001` | `ERR_NEU_PARAM_NOT_DECLARED` | l2-binding | (L3) a `parameterBindings` key is not a parameter the L2 interface declares |
| `NEU-4002` | `ERR_NEU_PARAM_REQUIRED_MISSING` | l2-binding | (L3) a required L2 parameter is not bound by any binding in the manifest |
| `NEU-4003` | `ERR_NEU_PARAM_TYPE_MISMATCH` | l2-binding | (L3) a `parameterBindings` value's `type` differs from the L2-declared type |
| `NEU-4004` | `ERR_NEU_UNTRACEABLE_SEMANTICS` | l2-binding | (L3) a `derivedConcepts` entry does not trace to any L2 parameter or concept, or the L2 interface could not be resolved |
| `NEU-4005` | `ERR_NEU_L2_CAPABILITY_MISMATCH` | l2-binding | (L3) `l2Ref.capability` is missing, or `l2Ref.capability` / the loaded L2 interface's `capability` does not equal the manifest capability (so traceability would come from another capability's L2) |

`NEU-3002` is the L3 backend-profile diagnostic (); `NEU-3003` stays **reserved** for a
future runtime-viability diagnostic (e.g. runtime version compatibility once the DSL models it).

### Precedence, multi-error, and ordering

- The validator emits **all** applicable diagnostics, not just the first — e.g. a viable slot
  bound with both a disallowed runtime and a wrong binder yields `NEU-3000` *and* `NEU-2002`.
- Two failures **suppress** the dependent per-slot policy checks for that binding, because the
  policy cannot be evaluated without a valid late-bound slot: an orphan slot (`NEU-1003`,
  `slotId` not in the topology) and a `fixed` slot (`NEU-3001`). The corresponding coverage
  gap still surfaces as `NEU-1004`.
- `NEU-1001` "not a JSON object" is **fatal** (nothing further can be evaluated); all other
  diagnostics accumulate.
- Diagnostics are sorted deterministically (manifest-level first, then by `bindingIndex`,
  `code`, `slotId`) so CI output is byte-stable.

### Guarantee boundary

Validation proves only that the manifest is a **structurally complete and policy-admissible
realization input** for the binding-topology — it does **not** guarantee real-world business
execution. Downstream evidence/admission semantics (agents/network) are separate; the
machine-readable report above is the translator-owned diagnostic surface those consumers read.

## L3 evolution ()

`schemaVersion: 2` evolves the Binding Manifest into the **executable L3 binding** contract —
JSON-first, no inline `binding_manifest {}` source syntax. It binds *validated L2*
states/actions/parameters to concrete runtime profiles **without redefining business
semantics**. All L3 fields are **additive and optional**: a `schemaVersion: 1` manifest is
byte-for-byte unchanged and existing consumers (network catalog-check, cross-rail `[51]`,
admission) are unaffected. The validator also enforces that a v1 manifest carries no L3 field.

Added surface (reviewed example `examples/binding-manifests/core_dual_offer.l3.binding.json`):

- **`l2Ref`** — `{capability, artifact}` linking the L2 interface whose declared
  parameters/concepts the bindings must trace to. Required for v2, and **capability-bound**:
  `l2Ref.capability` (and the loaded L2 interface's own `capability`, when it declares one) must
  equal the manifest capability, else `NEU-4005` — so traceability cannot be satisfied by a
  different capability's L2.
- **`backendProfile`** — an id from the **backend-profile catalog**
  (`examples/backend-profiles/catalog.json`, `kind: neutrino.backend-profile-catalog`). The
  first deeply-proven profile is `evm.v1`. A profile's `supportedFields` constrains which
  optional hook fields a binding may use; `jvm.v1` is `simulation-only`. A **concrete**
  (non-`deferred`) binding's `runtime` must match the profile's `runtimeFamily`, and a v2
  manifest whose profile catalog cannot be loaded fails closed — both `NEU-3002`, so `status`
  never describes an unresolved/mismatched runtime. A **`deferred: true`** binding is exempt
  from the runtime-family check: it has not pinned its concrete runtime/profile yet, so it may
  name a future/other runtime family (e.g. a hybrid `evm.v1` core manifest that defers
  conventional `jvm` adapter slots) while the manifest `status` stays `deferred`.
- Per binding: **`parameterBindings`** (`l2-param-name -> {type, value}`), **`derivedConcepts`**
  (must trace to L2), **`evidenceRefs`** (evidence requirement *declarations*),
  **`compensation` / `observability` / `retryTimeout`** (profile-gated hooks), and
  **`deferred`** (intentionally not-yet-realized).

**Machine-readable status.** The validation report adds a top-level `status` for L3 manifests
(absent for v1, so the v1 report shape is unchanged) — one of `complete`, `simulation-only`
(the chosen profile is simulation-only), `deferred` (a binding is `deferred: true`), or
`invalid` (any error diagnostic). Downstream rails read `status` directly instead of parsing
prose. The new diagnostics are `NEU-3002` (profile) and `NEU-4001..4004` (L2 parameter binding
/ traceability) in the table above.

**L2 interface — forward-compatible with .** L3 validates parameter bindings *against L2*.
The full L2 contract ([](internal-tracker),
`neutrino.l2-domain-semantics`) is now on `main`, but no per-capability L2 artifact exists for
`core_dual_offer` yet (that fixture is
[](internal-tracker), Implementor B). So the L3
validator consumes a **minimal L2 binding interface** — only the `parameters`
(name/type/required) and concept names it must trace — modeled in
`examples/binding-manifests/l2/*.l2.json` (`kind: neutrino.l2-binding-interface`). The loader
reads `parameters`/`concepts` **identically from either shape** — 's `parameters` are the
same `{name, type, required}`, and its object `concepts` are read by `name` — so once a real
per-capability L2 artifact lands, pointing `l2Ref.artifact` at it needs no code change.

**Guarantee boundary.** L3 `evidenceRefs` are **declarations** of what evidence a binding will
require — L3 does not verify any actual evidence. Runtime/admission verification of real
evidence is **M4** (network/agents), deliberately out of the translator. As with v1, validation
proves only a structurally complete, policy-admissible, L2-traceable realization *input*.

## Note

This is the static, translator-side validation of a realized environment. Exposing it as an
agent capability (`validate.binding-manifest`) and persisting the report as an agent artifact
is D5, owned by `neutrino-build-tools`; the realized-translation CLI/API shape
(`neutrino-gen --binding-manifest … --target=evm|http`) is a separate follow-up.
