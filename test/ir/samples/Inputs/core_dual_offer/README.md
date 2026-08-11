# `core_dual_offer` — core-owned multi-slot late-binding fixture

The **two-`to_be_bound`-slot** companion to
[`core_flexible_binding`](../../../domain/Inputs/core_flexible_binding/README.md)
(which binds only the Sponsor slot). Both the Sponsor and the Merchant slots are
bound to a concrete runtime at realization time, each carrying its own
conservative policy (allowed runtime families + minimum assurance + authorized
binder = the participant's org).

## Why it lives here

`1f16e44a` ("Externalize curated release corpus") moved the production
`dual_bound_offer` domain out of core into the curated pack corpus, and in the
same commit renamed the whole **core-owned** artefact family that describes it
to the `core_dual_offer` identity:

- `examples/binding-manifests/core_dual_offer.binding.json` (v1),
  `core_dual_offer.l3.binding.json` (v2) and `l2/core_dual_offer.l2.json`;
- the seven L3 negatives under `examples/binding-manifests/negatives/`;
- `examples/l2-domain-semantics/core_dual_offer.l2.json` plus its five
  negatives;
- the `core_dual_offer` row of the cross-rail fixture catalog as documented in
  [`docs/backends/CROSS_RAIL_FIXTURES.md`](../../../../../docs/backends/CROSS_RAIL_FIXTURES.md);
- the `[49]` / `[59]` / `[60]` checkers.

What it did **not** do is provide the L1 domain those core-owned artefacts bind
against — so `[49]`, `[59]` and `[60]` reached back into the deleted
`examples/domains/core_dual_offer` path (). This fixture is that missing
core-owned L1, created the same way ` train2` created
`core_flexible_binding` and ` train3` created `core_promo_campaign`: the
historical committed fixture with the production identity replaced by a
core-owned one. `generated/slot/` is tool-reproduced
(`neutrino-gen --target=slot`) and byte-compared, never hand-edited.

Provenance: every file here is the `1f16e44a^` committed
`examples/domains/dual_bound_offer` payload with the single substitution
`dual_bound_offer` → `core_dual_offer`. Six of the seven slot goldens are
byte-identical to the historical bytes after that substitution; `capability.lock`
differs only in the sha256 digests, which are a function of the identity.

## Contents

```
source/    core_dual_offer.neu                   # canonical source (two to_be_bound slots)
scenario/  core_dual_offer_happy_path.json       # happy-path scenario
generated/
  slot/    capability/operations/compensation/transcript + capability.lock
           + envelope.schema + binding-topology.json    # byte-compared by [49]
```

## Pinned by

| self-test | what it pins |
|---|---|
| `[49]` `test/ir/pipeline/multi_slot_binding.test` | slot regenerates byte-stable; exactly two fully-policied `to_be_bound` slots; the v1 binding manifest binds both (multi-slot completeness); a one-slot manifest is rejected |
| `[59]` `test/ir/samples/l3_evolution.test` | the L3 (schemaVersion 2) manifest validates against this topology with `status: complete`; each L3 negative fails closed with its NEU code |
| `[60]` `test/ir/samples/l2_core_dual_offer.test` | the cross-rail catalog cites the `core_dual_offer` L2 sidecar, tied to the same capability |
| `[51]` `test/ir/compat/cross_rail_catalog.test` | the catalog's `core_dual_offer` row matches this generated topology (paths, capability identity, late-bound slot policy) |
