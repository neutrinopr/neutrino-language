# Oracle Observation Binding (M5 oracle S5, )

The **observation binding** is the deployment-side contract that maps a *portable* oracle attestation
policy to *concrete* observers. It is the oracle analogue of the target/binding split used elsewhere in
Neutrino: the capability spec stays deployment-independent; the binding supplies what only a deployment
knows.

## The split

| Portable (capability spec, ) | Binding (this contract, ) |
|---|---|
| the observer-set **reference** an evidence input is gated by | the observer-set **membership** (concrete observers) |
| the **M** threshold (M-of-N) | the concrete **N**, and each observer's **public key** |
| declared observer-set **assurance** / **independence**, when present | matching deployment-side assurance / independence claims |
| that a canonical claim is attested | the mocked **external source** the observers read |

Only `M`, the observer-set *reference*, and optional observer-set trust declarations are portable; `N`,
the observer identities/keys, and the source descriptor are binding-level, so the same spec can be bound
to different deployments. If the portable spec declares `observerSet.assurance` or
`observerSet.independence`, the binding must repeat the same value exactly. A binding cannot silently
lower or relabel the declared observer-set trust posture.

## Shape

Schema: [`docs/schemas/observation-binding.schema.json`](../schemas/observation-binding.schema.json).
Worked example: [`examples/observation-binding/`](../../examples/observation-binding).

```json
{
  "kind": "neutrino.observation-binding",
  "schemaVersion": 1,
  "observerSets": [
    {
      "ref": "delivery_oracles",
      "assurance": "A3",
      "independence": "independent",
      "source": { "type": "mock", "id": "delivery_events", "claimField": "delivered" },
      "members": [
        { "id": "obs-alpha", "publicKey": "0xaa01" },
        { "id": "obs-beta",  "publicKey": "0xbb02" },
        { "id": "obs-gamma", "publicKey": "0xcc03" }
      ]
    }
  ]
}
```

## Validation (fail-closed)

[`scripts/validators/validate_observation_binding.py`](../../scripts/validators/validate_observation_binding.py) fully mirrors
the schema (required keys + `additionalProperties:false` + the safe-identifier / path-safety patterns)
**and** enforces the cross-references JSON Schema cannot express. Given the capability spec (`--spec`)
it also checks feasibility. It rejects, fail-closed:

- **`quorum_infeasible`** — `M > N`: the spec's threshold exceeds the bound observer count, so the
  M-of-N could never be met (a leg would never fire — or, worse, invite a lowered bar).
- **`unbound_observer_set`** — an attestation references an observer set with no binding entry.
- **`observer_assurance_mismatch`** / **`observer_independence_mismatch`** — the portable spec declares
  an observer-set trust posture, but the deployment binding supplies a different value or omits it.
- **`duplicate_observer`** — a repeated observer identity within a set (would collide generated files).
- **`missing_public_key`** — an empty key: the aggregator authorizes the quorum *by public key*, so a
  missing key would admit an unauthenticated attestation.
- **`unsupported_source`** — a source descriptor kind outside the supported set (`mock` today).

The oracle-observer backend ([](../../lib/backends/oracle/GenOracleObserverSpec.cpp)) enforces the
same shapes **before rendering**, so a malformed binding can never reach the generated observers or the
on-chain guard even if the standalone validator is skipped.

## EIP-712 guard domain + observer↔guard parity (oracle S7, )

An observer set may optionally bind the **acceptance-guard domain**, so the rendered observers sign
**exactly** the digest the on-chain guard ([`ThresholdQuorumAcceptance.sol`](../../examples/oracle-reference/threshold-quorum/src/ThresholdQuorumAcceptance.sol),
/) verifies — the *observer↔guard parity point*:

```json
"domain": { "chainId": 1, "verifyingContract": "0x00000000000000000000000000000000000000ab" }
```

The full EIP-712 domain is `(chainId, verifyingContract, capabilityHash)`. `capabilityHash` is **not**
in the binding — it is the spec's identity, bound at render. When `domain` is present, the observer
CO-SIGNS `claimDigest(claimId, canonicalClaimHash, executionClaim)` = `keccak256(0x1901 ‖ domainSeparator
‖ hashStruct)` (the domain-separated digest) over BOTH the evidence `canonicalClaimHash` and the
`executionClaim` — the coordination's recomputable payload digest — so the attested evidence is bound to
the exact execution it authorizes, and a valid quorum can never be replayed onto another chain, contract,
capability, or payload. The `executionClaim` is supplied to `observe(...)` by the invocation context; the
guard persists it as `acceptedExecutionClaim` for the coordination to bind against. When `domain` is
**absent**, the observer signs the naked `keccak256(encode(claim))` (the S4 default) — fine for a
dev/test binding with no deployed guard, but such a signature does **not** verify on chain.

**The parity gate** ([`scripts/gates/check_observer_guard_parity.py`](../../scripts/gates/check_observer_guard_parity.py))
is the off-chain analogue of the cross-backend equivalence (): it proves the rendered observers and
the guard are single-sourced, fail-closed on any mismatch of the **EIP-712 signing scheme** (the DOMAIN
/ CLAIM type strings must be byte-identical to the guard's, and the observer must sign the
`claimDigest`, not the naked hash), the **domain** (chainId / verifyingContract / capabilityHash), the
**quorum threshold** (M), the **observer-set identity**, and the **canonical claim shape**. A naked
observer, a tampered threshold, a wrong observer-set, a changed claim field, or a drifted type string
each fail the gate (see [`test/ir/oracle/observer_guard_parity.test`](../../test/ir/oracle/observer_guard_parity.test)).

## Source descriptor: the extension point

`source.type` is an enum whose only value today is **`mock`** (deterministic, injectable — the observers
take an injected hasher/signer, real at deploy). New real source kinds (an HTTP feed, a chain log, a
message queue) are added by extending the `source` enum + the descriptor's per-kind fields here and in
the validator; the portable spec is unaffected. Until then, an unsupported `source.type` is refused
rather than silently treated as a mock.
