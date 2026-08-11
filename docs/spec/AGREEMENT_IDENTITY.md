# Portable agreement identity (`--target=agreement-identity`, )

The **agreement identity** is the portable, domain-separated hash of a verified semantic agreement —
model 1 of [](../process/). It binds the frozen [capability-spec](CAPABILITY_SPEC.md) (the external
semantic contract) to the identity-level semantics that live *outside* the spec, **without** turning
the internal [CoordinationPlan](../../include/Neutrino/CoordinationPlan.h) into a wire contract.

## The hash

```
agreementHash = sha256(
      frame( DOMAIN )                            // "neutrino.agreement.v1"
    ‖ frame( semanticLanguageVersion )           // e.g. "0.1.0"
    ‖ frame( canonicalCapabilitySpecBytes )      // = compactOf(semanticCore) — the capabilityHash preimage
    ‖ frame( canonicalAgreementEnvelopeBytes ) ) // = compactOf(envelope)
```

- **`frame(x) = BE64(byteLength(x)) ‖ x`** — each field is prefixed with its byte length as an unsigned
  64-bit **big-endian** integer, so the concatenation is unambiguous: no field boundary can shift to
  forge a colliding preimage. The **raw component bytes** are concatenated (not their digests).
- **Domain separation** — the `neutrino.agreement.v1` tag means an agreement digest can never collide
  with any other neutrino hash (`capabilityHash`, an oracle claim digest, …), even over identical bytes.
- **`canonicalCapabilitySpecBytes`** is the *exact* preimage of `capabilityHash`
  ([`canonicalSemanticBytes`](../../include/Neutrino/GenSpec.h)) — the compact, sorted-key canonical JSON
  of the capability-spec **semantic core** (no envelope discriminators, no `sourceMap` /
  `targetRequirements` / `identity`). Reusing it means the agreement identity **can never drift** from
  the capability-spec contract, and inherits its whitespace- and realization-invariance.

## The agreement envelope (versioned)

The envelope carries the identity-level semantics the capability-spec deliberately omits:

```json
"envelope": { "schemaVersion": 1, "consentPolicy": null, "amendmentPolicy": null, "clauseSemanticIds": [] }
```

Greenfield in S1 — the policies default to `null` and `clauseSemanticIds` is empty; later slices author
them. Because the envelope's compact bytes are a hash component, populating any field is an explicit,
hash-moving change. Schema: [`agreement-identity.schema.json`](../schemas/agreement-identity.schema.json);
validator: [`validate_agreement_identity.py`](../../scripts/validators/validate_agreement_identity.py).

## The artifact

`--target=agreement-identity` emits `agreement-identity.json` (from source, or `--from-spec` from a
canonical capability-spec):

```json
{
  "kind": "neutrino.agreement-identity",
  "domain": "neutrino.agreement.v1",
  "semanticLanguageVersion": "0.1.0",
  "capabilityHash": "…",
  "envelope": { … },
  "identity": { "agreementHash": "…" }
}
```

`capabilityHash` is present for traceability (the preimage binds the *bytes*, not this digest).

## Identity properties (what the gate proves)

- **Cross-path identity** — from-MLIR ingestion and `--from-spec` ingestion produce a **byte-identical**
  artifact (both normalize to the same canonical semantic bytes).
- **Determinism** — field-order / whitespace variation in the source cannot move `agreementHash` (the
  canonical bytes are whitespace-invariant).
- **Semantic sensitivity** — changing any semantic spec field, or any envelope field, moves the hash.
- **Realization invariance** — changing realization-only data (`sourceMap`, `targetRequirements`,
  scenario/test-realization) does **not** move `agreementHash`.
- **Fail-closed** — a tampered capability-spec (its `capabilityHash` does not recompute) is refused
  **before** an artifact is written; an unknown domain / `semanticLanguageVersion` / envelope
  `schemaVersion` is rejected by `verifyAgreementIdentity` / the validator.
- **Golden vector** — [`agreement_hash_vector.json`](../../test/ir/agreement/agreement_hash_vector.json)
  pins the exact preimage bytes + expected digest for the primary sample; the gate recomputes it (a
  bypassed hash would fail).

## Separation of concerns

`agreementHash` is the **semantic-agreement** layer of the three-layer identity — distinct from the
**realization manifest** and the **runtime instance** identities. It carries no signatures / admission
evidence and no realization or runtime binding data; those are owned by the network rails. Tests:
[`test/ir/agreement/agreement_identity.test`](../../test/ir/agreement/agreement_identity.test) (gate +
golden vector + fail-closed) and `unittests/AgreementEnvelopeTest.cpp` (framing / determinism / verify).
