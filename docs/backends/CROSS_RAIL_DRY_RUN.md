# Cross-Rail Dry Run (Phase 13)

Proves the three rails can line up around the slot contract **without merging
their runtimes** and without modifying the sibling repos (they are read-only from
here). One scripted run moves a sample domain from `.neu` to a slot-ready
bundle and checks each boundary.

```bash
make cross-rail          # runs scripts/rails/cross_rail_dry_run.py
```

Writes `build/cross-rail-dry-run.json` and prints the stages + remaining gaps.

## What it checks

```
translator → slot-ready bundle → agents (artifact) → network (op alignment) → simulation (mapping)
```

| rail | check | gate |
| --- | --- | --- |
| **translator** | `.neu` → `neutrino-bundle` with `solidity,postgres,slot`; slot subtree has the 6 generated files (incl. `capability.lock`) and the 7 operations, and the lock's `capabilityHash` (the `EnvelopeHeader.schema_hash` bridge) is recomputed from the emitted wire contract and matches | mandatory |
| **agents** | the bundle is consumable as a task result: `bundle.json` + per-target `manifest.json`/`diagnostics.json` + slot artifact content hashes | mandatory |
| **network** | the translator's slot operation set (`OPEN … CLOSE`, reconciled to the Fabric op-set) is present in `neutrino-network`'s spec/proto/conformance | reported (read-only) |
| **simulation** | the slot capability's domain maps to a `neutrino-finance-poc` scenario (which drives `payment-network-simulation`) | reported (read-only) |

Translator-produced stages gate the exit code; cross-rail stages are reported and
anything unresolved is listed under remaining gaps. Sibling rails that are absent
are `skip`ped (and recorded as a gap), so the dry run still runs translator-only.

## Result (current)

All four rails align: the slot bundle is produced and contract-conformant, it
carries the agent artifact envelope, its 7 operations match neutrino-network's,
and `coordinate.core_sample_installment` maps to a finance scenario.

## Remaining integration gaps (before a full connection)

- **Transcript replay.** The dry run records per-artifact content hashes
  (`slotArtifactHashes`); a full cross-rail comparison of *transcript* / evidence
  hashes needs the network runtime actually replaying the operations — out of
  scope for a dry run.
- **Agent scheduling.** `neutrino-build-tools` does not yet schedule `generate.slot`
  as its own task type; today the slot bundle is produced via `neutrino-bundle`
  and consumed as a bundle artifact.
- **Envelope signing / identity.** Mock phase uses `role:id` + fixture keys; real
  key/DID identity and signature verification are deferred (owned with the
  network rail).

This is deliberately the *first* integration touchpoint, not a production pipeline.
