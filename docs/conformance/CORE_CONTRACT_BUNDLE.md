# Core Contract Bundle — external domain-pack conformance boundary ()

The **core contract bundle** is the published, versioned, machine-readable
boundary an **external domain pack** validates against **without importing
translator source, headers, or a sibling checkout**. It is the hourglass waist
made consumable off-tree.

## Artifacts

| Artifact | What it is |
|---|---|
| `docs/core-contract-bundle.json` | the committed, digest-pinned bundle |
| `docs/schemas/core-contract-bundle.schema.json` | the bundle's own meta-contract |
| `scripts/generators/make_core_contract_bundle.py` | the deterministic generator |
| `scripts/generators/make_domain_pack.py` | the deterministic complete-pack generator |
| `scripts/validators/verify_domain_pack.py` | the public verification CLI |
| `scripts/gates/check_core_contract_bundle.py` | completeness + integrity gate |

## What the bundle publishes

- **Identity/version:** `bundleId`, `bundleVersion`, and the translator
  compatibility surface (`versions` — sourced from `neutrino-translate
  --version-json`, i.e. `VersionInfo.h`) with a per-axis negotiation `policy`.
- **Contracts:** each authoritative core schema (capability-spec, L2/domain,
  profile, binding, scenario/result families) by `name`, `family`, `contractId`
  (`$id`), repository-root-relative `path`, and `sha256`.
- **Diagnostic taxonomy:** a digest-pinned reference + its categories.
- **Semantic-feature vocabulary:** the CLOSED  semantic-requirement feature
  set, published as `semanticVocabulary` (`semanticProfileVersion` + path +
  digest). It is emitted by `neutrino-translate --semantic-feature-vocabulary`
  from the single C++ source of truth (`knownSemanticFeatures()`), byte-matched
  by CI, and consumed by the target-profile validator and the released verifier —
  no hand-maintained parallel table. A pack's `target-profile` semantic features
  are matched against it; an unknown feature fails closed
  (`pack.unknown_semantic_feature`).
- **Canonicalization rules** and the `bundleDigest` (sha256 over the canonical
  bundle with the digest field removed).

The bundle is **generated**, never hand maintained — regenerating byte-matches
the committed file, and its digest is surfaced in the release manifest.

## Verifying a domain pack

A v2 pack manifest (`neutrino.domain-pack`, `schemaVersion: 2`) declares the
**exact** bundle it targets (`targetsBundle.bundleDigest`), the version axes it
pins, its required/optional contracts, and a complete lexicographically ordered
`payloads` inventory. Every payload carries a stable role, normalized relative
path, media type, and SHA-256; an optional `contract` adds semantic JSON-schema
validation. `packDigest` is SHA-256 over the compact canonical manifest with the
`packDigest` field removed, so it binds the complete ordered inventory.

An external consumer runs, with only the released bundle directory + the CLI
(standard library, no translator source):

```sh
verify_domain_pack.py --bundle core-contract-bundle.json --bundle-root <dir> \
                      --pack pack.json --pack-root <dir>
```

Verification is **fail-closed** with stable `pack.*` diagnostics: a bundle/pin
mismatch (`pack.bundle_mismatch`, `pack.pin_mismatch`), an unknown version axis
(`pack.unknown_version`), an unregistered/missing contract
(`pack.unknown_contract`, `pack.missing_required`), a tampered bundle/target/
schema digest (`pack.digest`), a manifest that violates the domain-pack contract
(`pack.shape`), a path escaping its root (`pack.path`), or an artifact that
violates its contract schema (`pack.schema`). V2 additionally rejects a
duplicate, unordered, missing, or extra payload (`pack.completeness`) and a stale
pack identity or payload digest (`pack.integrity`). Symlinks are not package
payloads and fail with `pack.path`, including symlink escapes. Opaque payloads
are byte-verified without JSON decoding; only entries naming a bundled
`contract` are JSON-parsed and schema-validated.

The artifact validation is a **complete** Draft 2020-12 validator over every
keyword the bundled schemas use (`$ref`/`$defs`, `oneOf`/`anyOf`/`not`/`if`/
`then`, `minimum`/`maximum`/`minItems`/`minProperties`/`uniqueItems`, `format`, union
types, …) — a **dialect-coverage** gate fails closed if a bundled schema uses a
keyword the verifier does not enforce, *or uses a supported keyword in a
form/value it only partially implements* (a `format` outside the enforced set —
currently just `date-time` — or a non-object `items`), so a newly registered
contract cannot slip an unenforced constraint past a green CI. The gate also
treats the **published diagnostic taxonomy as an integrity artifact**: because
the bundle pins its path + digest, a missing/malformed taxonomy file is a hard
failure, not a skipped check. Repository-root-relative contract paths and a
pinned bundle root are the single path authority; absolute / `..` paths are
rejected.

## Evolution + release packaging

`BUNDLE_VERSION` may not change silently: the gate compares the working bundle's
**public surface** against the **prior** bundle read from an immutable git ref
(`origin/main` by default, `NEUTRINO_BUNDLE_BASE` to override) — a value a PR
cannot fake by editing the tree. The public surface is the whole bundle **minus
only genuinely build-derived values** (the current translator version numbers in
`versions` and `translatorCompatibility.toolVersion`, and the self-referential
`bundleDigest`): identity (`bundleId`/`kind`/`schemaVersion`), the
canonicalization + hash rules, the compatibility **policy**, the complete
contract records (name/`contractId`/`family`/`path`/`sha256`), and the taxonomy
metadata (categories/path/digest) are all versioned. Any surface change without a
`bundleVersion` bump fails closed; a removed or re-versioned contract requires a
**major** bump. A build-only translator-version refresh is *not* a surface change
and does not force a bump. The base lookup itself **fails closed**: an
unresolvable/unreadable base ref is a gate failure, not a pass — first-release
leniency applies **only** when the base commit exists and specifically lacks the
bundle path. CI fetches the base before the gate runs (no `|| true`). `make release` packages the bundle, its pinned schemas,
the taxonomy, and this verifier under `conformance/` in the release tarball,
surfaces their digests in the release manifest, and **self-tests** the boundary
by validating the committed synthetic multi-format v2 pack from the *extracted*
package (no source checkout in scope).

Bundle 1.10.0 adds `domain-pack-v2` as a new `/v2` contract and leaves
`domain-pack` `/v1` byte-unchanged, so this is a same-major additive bundle
evolution. The released verifier selects v2 only for `schemaVersion: 2`; an
unversioned v1 manifest retains its historical `artifacts[{contract,path}]`
behavior against an exactly pinned supported bundle. V1 does not claim closed
payload completeness. Producers requiring the complete package boundary must
generate v2.

Bundle 1.12.0 adds the separate `backend-package-target-profile-v1` contract.
The public `target-profile/v1` contract remains byte-identical; verified backend
packages opt into the additional closed admission rules without narrowing the
standalone v1 compatibility baseline. Bundle 1.11.0 is retained byte-identically
in the registry as a historical target.

## Current vs. prior compatibility

The repo commits the **complete, self-contained frozen supported v1.0 boundary** —
`test/ir/bundle/Inputs/compat/v1.0/` (the bundle **plus every pinned artifact**:
all 15 contract schemas AND the taxonomy blob that matches its pin) — alongside a
v1.0 consumer pack. It also freezes the exact pre-v2 v1.9 boundary under
`test/ir/bundle/Inputs/compat/v1.9/`, including every contract schema, taxonomy,
semantic vocabulary, semantic capability registry, and its legacy v1 consumer
pack. `test/ir/bundle/check_bundle_compat.py` (via `bundle_compat.test`) proves
the compatibility contract across current and both witnesses:

- all three are valid consumer targets — the current released verifier validates
  the legacy v1 packs against their **frozen roots** (never mutable current files)
  and the current pack against the current bundle; both frozen roots are
  self-consistent and every pinned artifact matches;
- **The current bundle is a backward-compatible evolution of v1.0 and v1.9 across the WHOLE normative
  surface**, evaluated by one `compat_findings()`: no prior contract removed or
  re-versioned; bundle identity + canonicalization unchanged; the complete
  compatibility **policy** map unchanged; every published version axis governed by
  the verifier's rule (`toolVersion` same-major/monotonic, every other axis —
  including `semanticLanguageVersion` and nested `schemas.*` — exact); and the
  diagnostic taxonomy compatible **by content** (envelope identity stable,
  published categories append-only, every prior code surviving with its
  `category`/`precedence`/`status`). The only additions are the
  `semantic-feature-vocabulary` contract, the `semanticVocabulary` surface, and
  additive diagnostic codes;
- the **exact `bundleDigest` pin keeps the boundaries distinct** — the v1.9 pack
  does not silently validate against current, and the current pack does not
  validate against v1.9, so crossing the boundary is an explicit re-target;
- **breaking evolution is non-vacuously detected** — the *same* evaluator flags a
  removed/re-versioned contract, a removed/renumbered prior diagnostic code, a
  relaxed policy rule, and an exact-axis drift.

## Structural domain-content exclusion

The boundary is **synthetic and self-contained by construction**:
`scripts/gates/check_conformance_domain_exclusion.py` fails closed if the
conformance surface — the generator/verifier/gates, the published bundle +
artifacts, the release packaging, and every bundle test + fixture — references the
committed production-domain tree, embeds a production-domain identifier (the tell
of a domain artifact copied into a core fixture), or the bundle publishes any path
outside `docs/`. So the translator's own conformance self-tests stay on
synthetic/core fixtures and external domain ownership is never pulled back into
core. (The gate excludes only its own source, which necessarily names the policy
tokens.)

## Non-goals

No dynamic code/plugin loading, remote registry client, package manager, or
domain renderer; no automatic core promotion. The bundle is a boundary, not a
runtime.
