# Backend Capability Model

A backend capability model is a deterministic projection of one profile from
the verified target catalog plus the source capability witness. Core does not
author backend facts.

## Generation

```bash
neutrino-gen \
  --backend-package-dir <verified-package> \
  --target=capability \
  --scenario=<scenario.json> \
  <source.neu> -o <dir>
```

Generation emits exactly one model per verified external profile, in catalog
target order. An empty verified-profile catalog is an error. Package discovery,
profile parsing, and catalog identity computation happen once before source
processing; the capability target receives that checked catalog and performs no
rediscovery or fallback.

`solidity` and `postgres` retain `solidity.json` and `postgres.json`. Every
other admitted target uses the injective UTF-8-byte mapping
`target-<lowercase-hex>.json`; target identities are never interpreted as paths.

## Version 1.0.0

The complete nested shape is closed by
[`backend-capability-model-v1.schema.json`](../../lib/policy/capability-profile/backend-capability-model-v1.schema.json).

```json
{
  "catalogIdentity": "sha256:...",
  "kind": "neutrino.backend-capability-model",
  "modelVersion": "1.0.0",
  "package": {
    "executionMode": "simulated",
    "fallbackPolicy": "fail_closed",
    "runtimeFamily": "on_chain"
  },
  "semanticProfile": {
    "features": ["effect:credit"],
    "limits": {
      "maxAttestations": 8,
      "maxComputes": 32,
      "maxEffectGroups": 16,
      "maxEffects": 32,
      "maxExpressionDepth": 16,
      "maxOperationSteps": 64
    },
    "version": 3
  },
  "sourceCapabilityWitness": {
    "capabilityHash": "...",
    "procedure": "sample",
    "specVersion": "1.0.0"
  },
  "supportedFeatures": ["effect:credit"],
  "target": "example",
  "targetProfile": {
    "digest": "sha256:...",
    "identity": "target.example.v1",
    "version": 1
  },
  "unsupportedConstructs": ["effect:debit"]
}
```

Version 1 intentionally contains no core-invented execution environment,
conformance, cost, verification, value-model, maturity, assurance, or language
ceiling claims. Such facts require a separately versioned package-owned
declaration before they can re-enter this artifact.

The profile digest binds every package capability fact. The catalog identity
binds the complete verified target set, so profile or package changes cannot
leave an apparently identical model.
