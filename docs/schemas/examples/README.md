# Trust & late-binding examples

Conforming instances of the schemas in [`../`](..). All values are consistent with
the `core_flexible_binding` reference capability
(`test/ir/domain/Inputs/core_flexible_binding/generated/slot/`): same `capabilityId`, `capabilityVersion`,
and `capabilityHash`.

| File | Schema | Shows |
|------|--------|-------|
| `unbound-flexible-slot.json` | `binding-policy.schema.json` | the binding policy the translator emits today for a `to_be_bound` slot (byte-identical to the reference capability's `Sponsor` binding). |
| `active-binding-receipt.json` | `binding-receipt.schema.json` | an active Binding Receipt authorizing an EVM runtime for the `Sponsor` slot at tier A2. |
| `revoked-binding.json` | `binding-receipt.schema.json` | the same binding after revocation (`status: revoked`), superseding a prior receipt. |
| `a3-runtime-evidence.json` | `runtime-evidence-envelope.schema.json` | an A3 runtime-evidence record for a `COMMIT` transition, in a sequence/hash chain. |
| `component-compatibility-manifest.json` | `component-compatibility-manifest.schema.json` | a full component manifest (translator/agents/network versions + digests + schema versions). |

The schemas are **fail-closed**: a manifest must carry concrete translator identity
(`toolVersion`/`imageDigest`) and all schema versions; a receipt must carry
`validity` and `capabilityHash`; runtime evidence must carry `agreementHash`,
`capabilityVersion`, and `previousEvidenceHash` (`null` for the first event).

The policy example is verified to validate against its schema **and** to match the
live translator emission (so the schema can't drift ahead of what's produced). The
receipt/evidence examples are forward specs for Agents (T2) / Network (T3).
