# core_installment_fulfillment

The first implementable slice of the strategy [] sample as **current-valid** translator
artifacts (issue ) — the issuer/settlement branch only (single-branch; no two-branch
L2 boundary linking).

- **L1** [`source/core_installment_fulfillment.neu`](source/core_installment_fulfillment.neu)
  — the real procedure-oriented L1 language: the settlement legs (`issuer_funding` debit,
  `merchant_settlement` credit) balanced and replay-safe, with the `Issuer` slot
  `to_be_bound`. **No pseudo source syntax** (`capability` / `domain_semantics` /
  `lifecycle_states` are not `.neu` constructs — see [`docs/language/LANGUAGE_BOUNDARY.md`](../../../docs/language/LANGUAGE_BOUNDARY.md)).
- **L2** [`examples/l2-domain-semantics/core_installment_fulfillment.l2.json`](../../l2-domain-semantics/core_installment_fulfillment.l2.json)
  — the `neutrino.l2-domain-semantics` sidecar for the issuer/settlement branch: concepts
  trace back to the L1 anchors, structured `compare` guard/invariant (no free-form string
  expressions), and **`proof_of_delivery` declared as an evidence requirement**. A second,
  participant-specific **merchant** branch sidecar
  ([`...merchant.l2.json`](../../l2-domain-semantics/core_installment_fulfillment.merchant.l2.json))
  refines the same capability; the two are checked for branch-boundary compatibility ()
  by `scripts/domain/validate_l2_branch_compat.py` — see [`docs/domains/L2_DOMAIN_SEMANTICS.md`](../../../docs/domains/L2_DOMAIN_SEMANTICS.md).
- **L3** [`examples/binding-manifests/core_installment_fulfillment.l3.binding.json`](../../binding-manifests/core_installment_fulfillment.l3.binding.json)
  — a minimal Binding Manifest (schemaVersion 2) binding the `Issuer` slot's concrete
  parameters (`principal_cap`, `settlement_window`) and `backendProfile` `evm.v1`.

## Evidence boundary: L2 declares, M4 admits

**L2 only DECLARES `proof_of_delivery` as a required evidence input. It makes no runtime
claim — M4 owns runtime evidence admission** (verifying the actual proof at realization).
This fixture therefore validates purely as static artifacts; nothing here admits or checks
runtime evidence. See [`docs/domains/L2_DOMAIN_SEMANTICS.md`](../../../docs/domains/L2_DOMAIN_SEMANTICS.md)
("L2 declares, M4 verifies").

## Validation

Pinned by self-test `[63]`: L1 lowers; the L2 sidecar validates (with targeted negatives
for a bad evidence shape and an undeclared parameter reference); the L3 manifest validates
`complete` against the freshly generated binding-topology (with negatives for a missing
required parameter and a parameter L2 does not declare). The L2 positive + negatives also
run in the fast tier (`make test-fast`); L3 is full-tier (it needs the generated
binding-topology). See [`docs/testing/TESTING.md`](../../../docs/testing/TESTING.md).

[]: internal-tracker/neutrino-
