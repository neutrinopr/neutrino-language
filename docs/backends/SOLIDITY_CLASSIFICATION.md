# Solidity-samples classification contract (translator-owned)

`neutrino-solidity-samples/classification.json` labels each reference contract across
controlled coordination dimensions and pins each to a stable `profileId` / `profileVersion`.
The translator **targets** it — matching a generated contract to the closest reference *shape*
by `profileId`, never by contract name — so it is the input to  target-profile matching and
aligns with the  failure taxonomy.

**The translator is the source of truth for validating this file's shape.** The samples repo
README states it plainly: *"Validation of this file is owned by the translator-side checker, not
this repo."* That checker is
[`scripts/corpus/validate_solidity_classification.py`](../../scripts/corpus/validate_solidity_classification.py)
(stdlib-only, like the other `validate_*.py` gates). The samples repo carries the data; the
translator carries the contract.

The **normative shape** is the JSON Schema
[`schemas/solidity-classification.schema.json`](../schemas/solidity-classification.schema.json)
(fail-closed, `additionalProperties:false` everywhere). The validator **mirrors** that schema
(CI runs the stdlib script, not a JSON-Schema library — a self-test asserts the two stay
aligned) **and** enforces the cross-references a schema cannot express (below).

## The contract (schemaVersion 2)

- **Top level:** `schemaVersion` (== 2), `description`, `dimensions`, optional `dimensionDocs`,
  `samples`. No other keys.
- **`dimensions`:** exactly the governed dimension names — the seven *scalar* axes
  `partyModel`, `timeBound`, `oracleDependency`, `accessControl`, `identityBinding`,
  `orderingModel`, `evidenceStyle`, plus the one *list* axis `characteristics` — each a
  non-empty array of unique controlled-vocabulary strings. A new dimension is a
  `schemaVersion` change, not an ad-hoc field; unknown/missing dimensions fail closed.

  > **Adding a dimension** is a coordinated change: bump `schemaVersion`, add the property to
  > `schemas/solidity-classification.schema.json`, add it to `SCALAR_DIMENSIONS` or
  > `LIST_DIMENSIONS` in the validator, and extend the self-test. The alignment self-test
  > fails closed if the schema and validator disagree, so neither can be updated alone.
- **`dimensionDocs`** (optional): keys are a subset of the dimension names; values non-empty.
- **Each `samples[i]`:** `contract`, `profileId`, `profileVersion`, `source`, one value per
  scalar dimension (drawn from that dimension's vocabulary), a `characteristics` list (drawn
  from its vocabulary, non-empty, unique), `strength`, `whenToUse`. No other keys.
  - `profileId` matches `<family>.<name>.v<major>`, is unique, and its `v<major>` **equals**
    `profileVersion` (a positive integer) — the two identity fields cannot drift apart.
  - `source` ends in `.sol` and its basename equals `contract` (also unique).

## Fail-closed diagnostics

Any unknown field, missing required field, unknown dimension value, malformed `profileId`, or
`profileId`/`profileVersion` mismatch is an **error** diagnostic. Diagnostics are
machine-readable `{code, severity, message}` under the stable `classification.*` code family
(e.g. `classification.unknown_field`, `classification.missing_field`,
`classification.bad_profile_id`, `classification.profile_version_mismatch`,
`classification.unknown_dimension_value`, `classification.missing_dimension`), sorted and
compatible with the shared failure-taxonomy direction ().

```sh
# validate a classification.json; exit 0 ok / 1 violations / 2 usage
python3 scripts/corpus/validate_solidity_classification.py path/to/classification.json --out DIR
# writes DIR/classification.report.json + DIR/diagnostics.json
```

## Where it runs

The committed fixture
[`examples/solidity-classification/classification.json`](../../examples/solidity-classification/classification.json)
(a copy of the samples-repo file) is the positive fixture; negatives live under
`examples/solidity-classification/negatives/`. Both tiers gate it:

- **fast tier** (`test/checks/fast/solidity_classification_test.py`, `ctest -R fast-solidity-classification`)
  — positive accepted, negatives fail closed; no build needed.
- **full tier** (`test/run_cpp_tests.sh`, `[75]`, part of `make test` → release gate) — the
  committed negatives are pinned to their exact codes, plus inline-derived negatives for the
  remaining codes.

The committed fixture is a **snapshot copy** of the samples-repo file; its provenance (source
commit + refresh steps) is recorded in
[`examples/solidity-classification/README.md`](../../examples/solidity-classification/README.md).
Validating the copy only half-satisfies "CI checks the committed sample classification" — the
**live** file is gated only once the samples repo's own CI invokes this checker (via the pinned
GHCR translator image). That cross-repo wiring is tracked in
`internal-tracker/neutrino-solidity-samples`.

See also [`M5_DECISIONS_ADR_ADDENDUM.md` §AD3](../process/M5_DECISIONS_ADR_ADDENDUM.md) (profile
versioning) and  (target-profile matching).
