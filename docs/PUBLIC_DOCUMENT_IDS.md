# Public document identifiers

This historyless repository uses stable local URNs instead of links to private
repositories or issue trackers. These identifiers name bundled contracts and
evidence; they do not imply a network resolution service.

| Identifier | Bundled authority |
|---|---|
| `urn:neutrino:document:m6-curated-corpus-v2` | `docs/m6-curated-example-corpus.json` |
| `urn:neutrino:document:m6-curated-corpus-freeze-v2` | The public four-pack membership frozen in that corpus |
| `urn:neutrino:document:security-carveout-v1` | `docs/security-primitive-carveout-registry.json` |
| `urn:neutrino:document:typed-security-table-migration-v1` | The completed typed-table disposition recorded by that registry |
| `urn:neutrino:fixture:generalism-seeds-v1` | `test/generalism/seed-cells.json` |
| `urn:neutrino:evidence:obligation-reference-vectors-v1` | `test/ir/Inputs/obligation_reference_vectors.json` and its embedded source hashes |
| `urn:neutrino:gate:native-build-v1` | The native-build test gate fixture |
Each bundled domain pack has a `publication-receipt.json` whose identity is a
SHA-256 digest over its closed, sorted member inventory. Legacy custody
receipts and donor-history metadata are deliberately outside this public tree.
