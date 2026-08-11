# Late-Binding Policy (Trust lane — T1)

**Status:** T1 slice 2 (translator emission). Source:
`neutrino-strategy/09-debates/verification-trust-model-runtime-compliance.md`
(agreement-centric trust model, late slot binding).

A participant whose concrete runtime is decided **at realization time** (not fixed
by the agreement) is marked `binding = "to_be_bound"` and carries a small,
conservative policy. This is the translator's half of late binding: it declares
*who may bind*, *to what kind of runtime*, and *at what minimum assurance* — the
fabric (network) and the agents then enforce/record the actual binding.

Design note: binding policy is a **derived annotation on the existing participant**
(the translator's unit of authorization), not a new first-class construct — it
reuses the `participant` / `org` machinery rather than forking it.

## DSL

```
participant Sponsor {
    role               = "sponsor"
    org                = "sponsorco"
    binding            = "to_be_bound"     // default (absent) = "fixed"
    bind_runtimes      = ["evm", "jvm"]    // allowed runtime/backend families
    bind_min_assurance = "A2"              // minimum assurance tier (A1-A4), optional
}
```

Rules — enforced **both** in the frontend (clear, line-numbered errors) **and in
the `ParticipantOp` IR verifier**, so direct `.mlir` fed to `neutrino-opt` /
`neutrino-gen` cannot bypass them and fail open:

- `binding` must be `"to_be_bound"` or `"fixed"`; `"fixed"` is the default and
  carries no policy (in the IR, a fixed participant simply has no `binding` attr).
- the `bind_*` fields are only valid on a `to_be_bound` participant.
- a `to_be_bound` participant **must** declare an `org` — it is the authorized
  binder; without it the slot would name no actor permitted to bind it.
- a `to_be_bound` participant **must** declare `bind_runtimes`, a non-empty list
  of **non-empty** runtime families (no open-ended binding surface, and no `""`
  entry — this is the allow-list a binding is later checked against). The runtime
  family *vocabulary* is not yet closed (a T0 contract decision); only empties are
  rejected today.
- `bind_min_assurance`, if set, must be one of `A1`/`A2`/`A3`/`A4` (see
  [`CAPABILITY_MODEL.md`](../backends/CAPABILITY_MODEL.md) for the assurance vocabulary).

## Emitted artifact

A `to_be_bound` participant gains a `binding` object in the slot
`capability.json` (a wire-contract file, so it is covered by `capabilityHash` and
the `EnvelopeHeader.schema_hash` bridge). The `authorizedBinder` defaults to the
participant's own org (conservative):

```json
{ "name": "Sponsor", "role": "sponsor", "org": "sponsorco", "capabilities": [],
  "binding": { "mode": "to_be_bound", "runtimes": ["evm", "jvm"],
               "minAssurance": "A2", "authorizedBinder": "sponsorco" } }
```

A source with no `to_be_bound` participant produces **byte-identical** artifacts
to before this feature.

## Reference capability

`test/ir/domain/Inputs/core_flexible_binding/source/core_flexible_binding.neu` (+
scenario, + the byte-stable golden slot subtree under
`test/ir/domain/Inputs/core_flexible_binding/generated/slot/`, fixture-tested by
self-test `[32]`) is the canonical late-binding capability — the artifact the
agent (T2) and network (T3) rails develop against.

## Assurance honesty (Capability Security Pass)

Static generation can provide the inputs used by an A1 attestation, but
catalog-derived capability-model v1 does not itself carry or claim an assurance
tier (see [`CAPABILITY_MODEL.md`](../backends/CAPABILITY_MODEL.md)).
A binding that requires a higher tier (`bind_min_assurance` = `A2`/`A3`/`A4`)
cannot have that satisfied by the translator — A2 is established at realization,
A3 is runtime evidence, A4 is proof, all fabric/agent-owned. The security pass
reports this as a **`trustBoundary` advisory** (not a gate, `ok` stays true, and
never silently claimed satisfied):

> participant 'Sponsor' binding requires assurance A2, above the A1 that static
> generation attests; satisfied at realization/runtime (fabric/agent-owned), not
> by the translator

## Downstream / follow-up (not in this slice)

- **Agents (T2):** a Binding Receipt authorizes a concrete realization, validated
  against this policy (`authorizedBinder`, `runtimes`, `minAssurance`).
- **Network (T3):** runtime evidence (A3) is produced against the bound runtime.
- **Translator (follow-up):** required evidence profile, rebinding rule, and a
  closed runtime-family vocabulary (a T0 contract decision).
