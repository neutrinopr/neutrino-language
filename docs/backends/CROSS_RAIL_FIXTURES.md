# Cross-Rail Fixture Catalog

**Catalog:** [`examples/cross-rail-fixtures.json`](../../examples/cross-rail-fixtures.json)
**Validator:** `scripts/validators/validate_cross_rail_catalog.py` · pinned by self-test `[51]`
**Issue:** internal-tracker · Strategy parent: internal-tracker/neutrino-

---

## What this is

The M2 example domains are now **cross-rail acceptance assets**, not just documentation:
network, agents, console, and the release notes all consume the same translator-produced
artifacts. This catalog is the translator-owned, machine-readable contract that says **which
fixtures are intended for cross-rail use and which artifact files are normative** — so
downstream repos don't hand-maintain artifact path lists or guess at the runtime/assurance
policy.

The translator owns the catalog; downstream rails **consume** it. It does not move any
evidence/admission semantics into the translator (those stay network/agents work).

## Per-fixture metadata

For each cross-rail fixture the catalog records:

- `fixtureId` / `capabilityId` / `capabilityVersion`;
- `source` and `scenario` paths;
- `generated` normative artifacts, grouped by target (`slot`, `security`, `postgres`);
- `bindingTopology` and `bindingManifest` paths;
- `selfTest` — the self-test id that pins it (`[49]`, `[50]`);
- `targets` — the supported target outputs;
- `lateBoundSlots[]` — each `to_be_bound` slot with its required policy
  (`allowedRuntimes`, `minAssurance`, `authorizedBinder`, org/participant).

A single **top-level** `compatibility` block (not per fixture) carries the toolchain-wide
version/compatibility surface () — see [Compatibility surface](#compatibility-surface-164) below.

## How downstream consumers should use it

Treat `capabilityId` + `lateBoundSlots[].{allowedRuntimes, minAssurance, authorizedBinder}`
as the **contract** for fail-closed admission. A consumer can reject:

- the **wrong capability** — `capabilityId` mismatch;
- a **missing Binding Manifest** — `bindingManifest` absent / not the one bound;
- a **wrong runtime family** — a realization runtime not in the slot's `allowedRuntimes`
  (and, at realization, not the one the Binding Manifest actually bound);
- an **assurance below the minimum** — below the slot's `minAssurance`.

This is exactly what the network realization conformance does
(`neutrino-network/conformance/realization/`, `multi-realization/`), grounded in these
fixtures.

## Fixtures

| fixtureId | capability | late-bound slots | targets | self-test |
|-----------|-----------|------------------|---------|-----------|
| `core_dual_offer` | `coordinate.core_dual_offer` | `#Sponsor` (evm/jvm, A2), `#Merchant` (evm, A2) | slot | `[49]` |
| `core_scheme_settlement` | `coordinate.core_scheme_settlement` | `#SettlementBank` (swift/jvm, A2) | slot, security, postgres | `[50]` |

## Compatibility surface ()

The catalog carries a **top-level `compatibility` block** — the toolchain-wide
language/artifact version surface (`toolVersion`, `mlirDialectVersion`,
`schemaBundleVersion`, `conformanceVectorVersion`, `compatibilityManifestVersion`, and the
`schemas` bundle), aligned with `docs/schemas/component-compatibility-manifest.schema.json`
([VERSIONING.md](../process/VERSIONING.md), [COMPATIBILITY.md](../process/COMPATIBILITY.md)). It is **pinned to
`include/Neutrino/VersionInfo.h`** (the single source of truth, also exposed by every tool
via `--version-json`): `validate_cross_rail_catalog.py` / `[51]` fail closed if the catalog's
compatibility values drift from `VersionInfo.h`.

Downstream consumers read this to reject artifacts produced by an **incompatible translator
surface** before trusting them — `mlirDialectVersion` and the `schemas` versions must match
exactly; `toolVersion` must be the same major and `>=` (SemVer), per the policy in
`scripts/gates/check_compatibility.py`.

## Integrity (fail-closed)

`scripts/validators/validate_cross_rail_catalog.py` (self-test `[51]`, run by `make test`) checks that
every referenced path is committed and present, that each fixture's capability identity and
late-bound slot policy **match the generated `binding-topology.json`** (no stale copy), that
the Binding Manifest binds exactly those slots within policy, and that the top-level
`compatibility` block is **pinned to `VersionInfo.h`**. A stale path, drifted policy, or
drifted compatibility surface fails CI.
