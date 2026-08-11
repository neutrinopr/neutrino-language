# Test Realization (M5 WP2, )

Separates **capability semantics** from **scenario/test realization**. A
capability — its [spec](../spec/CAPABILITY_SPEC.md) and `capabilityHash` — is derived
from source alone and is scenario-independent. The concrete test cases a scenario
produces are folded **once** into a companion artifact that lives **outside** the
capability hash scope.

## The problem it fixes

Each backend renderer used to re-derive its test cases from the raw `Scenario`
independently (the Foundry test and the PostgreSQL harness each read
`scenario.inputs` / `.computed` / `.ledger` / `.events`). That is duplicated
folding, and it blurs the line between *what the capability is* (semantics) and
*how a particular scenario exercises it* (a test case).

## The artifact — `test-realization.json`

`neutrino-gen --target=test-realization --scenario=<s>` folds `(spec, scenario)`
into the concrete cases the backends need, once:

| field | meaning |
| --- | --- |
| `capabilityHash` | the capability these cases realize — a **reference**, not this file's identity |
| `scenario` / `procedure` | which scenario / procedure |
| `inputs` | concrete input values |
| `computed` | expected value of each compute |
| `eventChain` | expected coordination event order (validated against the IR choreography at fold time) |
| `ledgerDeltas` | expected net movement per ledger |
| `invariants` | invariants the case proves |

Deterministic and canonical (sorted keys, no timestamps). Schema:
[`schemas/test-realization.schema.json`](../schemas/test-realization.schema.json).

## Hash-scope separation

`capabilityHash = capabilityHashOf(view)` — a pure function of the source-derived
`ProcedureView`, computed in one place (`GenSpec`) and shared by the spec and the
realization. It **never** sees scenario data, so:

- **changing only a scenario/test never changes `capabilityHash`** (self-test
  `[79]`: a variant scenario with different input values realizes to the same
  `capabilityHash`);
- the realization **references** `capabilityHash` rather than being hashed into
  it — the companion points at the capability, never the reverse.

## Fold once, consume everywhere

`realize(view, scenario)` (in `TestRealizationTarget.cpp`) is the single place scenario
data is folded and validated (the event-chain-vs-choreography check moved here
out of the Solidity renderer). Both migrated renderers now consume the
`TestRealization`:

- **Solidity / Foundry** (`generateSolidityTest(view, TestRealization)`)
- **PostgreSQL** (`generatePostgresDbTestFromSpec(spec, TestRealization)` — the harness's
  structural shape comes from the canonical spec; the `TestRealization` supplies only the
  concrete values/ledger, WP5/)

Their emitted output is **byte-identical** to before the split (the committed
Foundry/SQL goldens are unchanged — self-test `[43]`), so this is a
structure-only separation: same tests, one fold, an explicit companion artifact,
and a capability hash that is provably scenario-independent.

## Scope (v1): realized facts, not the case catalogue

v1 carries the realized **facts** a scenario produces — the concrete inputs,
computed values, event chain, and ledger deltas. It does **not** yet carry the
**case catalogue** (which negative paths to generate: happy-path, replay,
missing-attestation, isolation-per-key); those cases are still derived inside
each renderer from these facts, which is why the Foundry/SQL goldens stay
byte-identical. Making the spec own the case list (the strategy's "the spec owns
the test spec") is a candidate for a later schema version; this WP splits the
scenario *facts* out of the capability hash, which is the load-bearing separation.

## Validation

`scripts/validators/validate_test_realization.py` mirrors the schema (stdlib only) and
enforces the one **beyond-schema** invariant a JSON-Schema cannot: `capabilityHash`
is well-formed **and**, given a capability-spec (`--spec`), matches that spec's
`identity.capabilityHash` — so a stale or hand-edited reference (a realization
pointing at no real capability) fails closed. Its codes come from the shared
[diagnostic taxonomy](../language/DIAGNOSTIC_TAXONOMY.md) (`realization.*`, ). Every
committed realization fixture is validated + cross-checked in the fast tier
(`[fast/11]`) and the self-test (`[79]`).

## Manifest / hash behavior

The realization is an ordinary emitted artifact (its own per-file `sha256` in
`manifest.json`), non-gated and scenario-bearing. It is **not** part of the spec,
the slot capability, or `capabilityHash`. The spec stays the only frozen external
contract (ADR D1); the realization is a derived test companion beside it.
