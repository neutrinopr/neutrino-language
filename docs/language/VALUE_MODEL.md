# Value Model (Phase 10)

The executable type vocabulary for `.neu` inputs and scenario values. It
gives backend generation and slot envelopes (Phase 9 / Phase 12) explicit enough
types **without leaking target-specific behavior into the source language**.
Money executes as integer minor units; richer decimal/currency metadata lives at
input/UI/import boundaries, not in the IR arithmetic.

## Type vocabulary

`.neu` declares an input as `input NAME : TYPE`. Recognized types and their
scenario-value rules (enforced by `validateScenario` before generation; a
violation is `scenario.invalid`, exit code 3):

| `.neu` type | scenario JSON value | rule |
| --- | --- | --- |
| `money` | integer | **minor units** (e.g. cents). Floats/strings rejected. **Non-negative** — an unsigned amount, not a signed balance; a negative money input or money-typed compute result fails closed (`scenario.invalid`) before rendering (). |
| `decimal` | integer | carried as a **scaled integer** (e.g. `10` = 10%). |
| `int` / `integer` / `number` / `uint` | integer | integer. |
| `string` | string | free text. |
| `party` | string | non-empty typed party id (used as `participant`/owner). |
| `currency` | string | 3-letter ISO-4217-shaped code, e.g. `EUR`. |
| `timestamp` / `time` | integer **or** string | opaque: epoch int or ISO-8601 string; not interpreted by the IR. |
| `evidence` | string | hashable reference `"<scheme>:<value>"`, e.g. `sha256:ab12…` or `ref:doc-7`. |

An unrecognized type falls back to numeric-vs-string, so the model stays open.

> Today the scenario loader accepts only JSON integers or strings (no floats, no
> objects). The model is built on that: money/decimal are integers; evidence is a
> reference *string*, not a nested object. Structured multi-field evidence is a
> later extension.

## `.neu` example

```hcl
procedure value_types {
    input amount      : money        // integer minor units
    input rate        : decimal      // scaled integer (percent)
    input payer       : party        // typed id
    input ccy         : currency     // "EUR"
    input occurred_at : timestamp    // epoch int or ISO-8601 string (opaque)
    input doc         : evidence     // "sha256:…" hashable ref

    compute fee = round(amount * rate / 100, 2)
    debit  out { ledger="a.x" owner="a" party=%payer amount=%fee currency=%ccy idempotency_key=%doc }
    credit inc { ledger="b.y" owner="b" party=%payer amount=%fee currency=%ccy idempotency_key=%doc }
    assert balanced
}
```

## Scenario value examples

Valid (see `test/value_types_good.json`):

```json
{ "amount": 100000, "rate": 10, "payer": "party-1", "ccy": "EUR",
  "occurred_at": "2026-01-01T00:00:00Z", "doc": "sha256:ab12cd34" }
```

Rejected (`scenario.invalid`): `amount: "100000"` (money must be integer),
`payer: 123` (party must be a string id), `ccy: "EU"` (not a 3-letter code),
`doc: "notaref"` (evidence not a hashable reference). Each has a negative-test
fixture under `test/value_types_bad_*.json` (self-test check [10]).

## Compatibility statement

- Existing sources/scenarios are unaffected: `money`/`decimal`/`string` keep their
  prior meaning, and the previously-loose numeric-vs-string rule still applies to
  any type not in the table above.
- `party`, `currency`, `timestamp`, and `evidence` are **new recognized types**;
  using them is additive. They render in backends exactly as strings do today
  (they are non-numeric operands), so no generated Solidity/SQL changes.
- The loader contract is unchanged (integers or strings only); the value model is
  a *validation* layer over it, not a new serialization.

## Backend / pipeline impact

- **Solidity / PostgreSQL:** unchanged codegen — `party`/`currency`/`evidence`
  are non-numeric, so they lower as string operands just like `string` inputs
  (`money`/`decimal` remain integer minor units). The value model tightens
  *inputs*, not *emission*.
- **Equivalence:** no change to compared semantics; type validation runs before
  equivalence so malformed scenarios fail fast.
- **Slot artifacts (Phase 9):** the typed inputs are what slot envelopes need —
  `participant`/`counterparty` ← `party`, money fields ← `money`+`currency`,
  evidence refs ← `evidence`. Phase 12 (`generate.slot`) consumes these types.
