# Sovereign Lowering Envelope (M5)

The translator-side **import contract** for M5 sovereign lowering: a minimum, reviewable, versioned
manifest that wraps **externally lowered artifacts** so a console / network / agents consumer can
safely accept them **without trusting the producing compiler**. It lets a participant run their own
compiler/toolchain (or use the official translator) and have the output consumed on the strength of
a **self-describing, verifiable envelope** — not on trust in the console as the compiler.

Implements  (M5) and the reshaped M5 / ADR-018 (); the console sovereign-lowering
UX (neutrino-console) consumes this envelope directly. Aligned with the M4 versioning surface
( `COMPATIBILITY.json`, `include/Neutrino/VersionInfo.h`, `check_compatibility.py`).

- **Schema:** [`schemas/sovereign-lowering-envelope.schema.json`](../schemas/sovereign-lowering-envelope.schema.json) (kind `neutrino.sovereign-lowering-envelope`, v1)
- **Validator / reference consumer check:** [`scripts/validators/validate_sovereign_envelope.py`](../../scripts/validators/validate_sovereign_envelope.py)
- **Fixtures:** [`examples/sovereign-lowering/`](../../examples/sovereign-lowering)

## What the envelope carries

| Field | Purpose |
|---|---|
| `capability` / `capabilityVersion` | the capability the artifacts realize |
| `source.{language, sourceHash, languageVersion}` | the source DSL, its content hash, and the **language-level version** the producer targeted (required — a missing language version fails closed) |
| `producer.{identity, official, toolVersion, gitSha?, buildTarget?}` | who produced the artifacts (`official:neutrino-translator` or `participant:<org>-<compiler>`) and whether it is the official translator |
| `target.{backend, runtimeProfile?}` | the generator target (`solidity` / `postgres` / `slot`) and backend profile (`evm.v1`, …) |
| `artifacts[].{path, role, hash}` | every emitted artifact with a **content hash**, so integrity is verifiable without re-compiling |
| `diagnostics.{ok, count?, ref?}` | the producer's diagnostics summary |
| `translatorVersion` | the producer's **self-declared compatibility surface** — a `neutrino.translator-version` envelope (the same shape `--version-json` / `manifest.json` carry) |

## What a consumer MUST validate before accepting imported artifacts

A console / network / agents consumer runs, in order (all fail-closed):

1. **Shape** — the envelope is well-formed against the schema: required fields, no unknown fields at
   every object level, the type **and pattern** of every field (semver `capabilityVersion` /
   `toolVersion` / `mlirDialectVersion`; `sha256:<64 hex>` hashes), and **path safety** — every
   `artifacts[].path` (and `diagnostics.ref`) must be **relative and free of `..` traversal** — POSIX
   (`/…`) and Windows (`C:\…`) absolute paths and both `/` and `\` traversal separators are rejected,
   in the reference validator **and** the published schema pattern — so a malicious envelope cannot
   point at a host path outside the reviewed bundle, whether a consumer uses the validator or the
   schema directly. A truncated, typoed,
   missing-version, malformed-hash, or path-escaping envelope is refused. (`validate_sovereign_envelope.py`
   mirrors the schema in stdlib, since CI runs the script, not an external JSON-Schema validator.)
2. **Compatibility** — the envelope's `translatorVersion` surface **satisfies the consumer's own
   requirement** (a `neutrino.component-compatibility-manifest`), via the **existing**
   [`check_compatibility.py`](../../scripts/gates/check_compatibility.py) policy: exact `mlirDialectVersion`
   (the IR contract), exact per-contract schema versions, and a same-MAJOR `toolVersion` that is
   `>=` required. An incompatible or missing language/artifact version is refused. **The console needs
   no parallel manifest** — the envelope is a valid `--have`:

   ```sh
   scripts/gates/check_compatibility.py --have <envelope>.json --require <consumer-requirement>.json
   # or, with integrity + shape in one gate:
   scripts/validators/validate_sovereign_envelope.py --envelope <envelope>.json \
       --require <consumer-requirement>.json --verify-hashes
   ```
3. **Integrity** — each `artifacts[].hash` matches the imported file (`--verify-hashes`), so the
   consumer confirms the bytes without re-running the compiler. Paths are re-checked at hash time
   (defense-in-depth): a file that resolves outside the import root is refused even under an
   attacker-chosen `--artifact-root`.

Only after all three pass does the consumer treat the artifacts as admissible.

## Sovereignty: official and participant producers

The envelope is **self-describing**; acceptability is the **consumer's** decision, not the local
translator's. The validator therefore does **not** pin the declared versions to the local
`VersionInfo.h` — a participant-owned compiler may legitimately target a different version, and the
consumer's `--require` manifest is what decides. `producer.official` lets a consumer *additionally*
require the official translator if it wants to, but the contract works identically for a
`participant:<org>-<compiler>` producer. This is what makes lowering **sovereign**: trust flows from
the versioned, hashed, reviewable envelope + the consumer's policy, not from trusting the compiler.

## Fixtures

- **Positive** — [`examples/sovereign-lowering/core_promo_campaign.envelope.json`](../../examples/sovereign-lowering/core_promo_campaign.envelope.json)
  wraps the **official translator output** for `coordinate.core_promo_campaign` (the committed
  `test/ir/samples/Inputs/core_promo_campaign/generated/slot/` artifacts, with their real sha256 hashes) and a
  `translatorVersion` surface pinned to `VersionInfo.h`. It passes shape + compatibility (against
  [`consumer-requirement.json`](../../examples/sovereign-lowering/consumer-requirement.json)) +
  hash verification.
- **Negatives** ([`negatives/`](../../examples/sovereign-lowering/negatives)) — each fails closed:
  `incompatible-dialect` (a `participant:` producer declaring `mlirDialectVersion 9.9.9`) fails the
  consumer compatibility check; `missing-language-version` (no `source.languageVersion`),
  `malformed-source-hash` (`sha256:not-a-real-hash`), and `malformed-capability-version`
  (`capabilityVersion: dev`) fail the shape check; `absolute-artifact-path` (`/tmp/...`) and
  `traversal-artifact-path` (`../../etc/passwd`) fail the path-safety check even with
  `--verify-hashes` and an attacker-chosen `--artifact-root`.

Pinned by self-test `[73]` (positive accepted with shape+compat+hashes and consumable by
`check_compatibility.py` directly; all six negatives fail closed).

## References

- M5 milestone:  · reshaped M5 / ADR-018:  · M4 gate/versioning: .
- Console sovereign-lowering UX: neutrino-console.
- Compatibility surface: [COMPATIBILITY.md](../process/COMPATIBILITY.md) · [`COMPATIBILITY.json`](../../COMPATIBILITY.json) () · target inventory [BACKEND_TARGET_CATALOG.md](BACKEND_TARGET_CATALOG.md) ().
