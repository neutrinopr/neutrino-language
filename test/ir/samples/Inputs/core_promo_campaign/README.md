# `core_promo_campaign` — M5 Sponsored Promo Campaign ()

A translator L1/L2/L3 fixture for the multi-party **pharmacy-aggregator sponsored promo campaign**
from internal-tracker/neutrino- — turned from prose into checked-in, validated artifacts.
Forward sample (M5); see the [M3 cookbook](../../../../../docs/domains/M3_COOKBOOK.md) entry **F1**.

## Roles

| Role | In L1? | Notes |
|---|---|---|
| **Sponsor** | yes (`to_be_bound`, evm) | funds the promo pool; the on-chain commitment slot |
| **Promoter** | yes | earns the commission on an attributed redemption |
| **Fulfiller** | yes | reimbursed for fulfilling the redemption |
| **Coordinator / Aggregator** | **no — L2 role** | ingests redemption events and drives the Setup → Active → Settlement lifecycle; moves no value, so it is an L2 coordination role (a `Coordinator` participant branch), not an L1 party |

## Layering (what lives where)

- **L1** ([`source/core_promo_campaign.neu`](source/core_promo_campaign.neu)) carries only
  the **value movement** of one settled redemption: the Sponsor promo pool funds a
  `promoter_commission` and a `fulfiller_reimbursement`, balanced and replay-safe. **Reimbursement
  integrity** is `assert balanced` — the pool is debited by exactly the commission and reimbursement
  it pays out, so a mismatch fails closed at the translator (see
  [`negatives/reimbursement_mismatch.neu`](negatives/reimbursement_mismatch.neu)).
- **L2** ([`../../l2-domain-semantics/core_promo_campaign.l2.json`](../../l2-domain-semantics/core_promo_campaign.l2.json))
  declares the **Setup → Active → Settlement** lifecycle (mapped onto concepts per the L2 lifecycle
  decision, not a first-class block), the failure modes (`budget_exhausted`, `invalid_attribution`,
  `double_redemption`, `settlement_reversal`), per-participant branches (incl. the Coordinator), and
  parameters (`budget_cap`, `attribution_window`, `max_redemptions`, `reconciliation_window`). The
  core campaign semantics are **guards + invariants that consume those parameters**, not just names:
  - `total_outlay_within_budget` — the **total** Sponsor outlay (`total_sponsor_outlay` =
    commission + reimbursement) `<= budget_cap` ('s `total_discounted <= Sponsor.pool`),
    so a large reimbursement leg cannot slip under a commission-only cap;
  - `attribution_within_window` (`<= attribution_window`) + the `attribution_is_unique` invariant
    (`exactly_one_promoter_attribution`, onFailure `invalid_attribution`) — exactly-one attribution;
  - `redemption_within_limit` (`<= max_redemptions`) + the `no_double_redemption` invariant
    (`redemption_id_unique`, onFailure `double_redemption`);
  - `commission_matches_funding` / `reimbursement_matches_funding` — reimbursement integrity.

  Evidence requirements: `valid_promo_code` (required), `delivery_confirmation` (optional),
  `reconciliation_report` (required). L2 **declares**; **M4** admits/evaluates at runtime.
- **L3** ([`../../binding-manifests/core_promo_campaign.l3.binding.json`](../../binding-manifests/core_promo_campaign.l3.binding.json))
  binds the Sponsor slot to **`evm.v1`** (EVM commitment) with the budget/attribution parameters,
  the evidence refs, and `observability.emits` for redemption-event ingestion + settlement. Payment
  execution is simulated — see internal-tracker/payment-network-simulation.

## Value movement (L1)

```
sponsor.promo_pool  --commission-->     promoter.commission
sponsor.promo_pool  --reimbursement-->  fulfiller.reimbursement
assert balanced   (debits == credits, per currency)
```

## How to check it

```sh
# L1 lowers + generates the slot subtree
out/tools/neutrino-translate/neutrino-translate test/ir/samples/Inputs/core_promo_campaign/source/core_promo_campaign.neu
out/tools/neutrino-gen/neutrino-gen --target=slot \
    --scenario=test/ir/samples/Inputs/core_promo_campaign/scenario/core_promo_campaign_happy_path.json \
    test/ir/samples/Inputs/core_promo_campaign/source/core_promo_campaign.neu -o /tmp/spc_slot
# L2 validates; L3 binds against the generated topology
python3 scripts/domain/validate_l2_domain_semantics.py --artifact examples/l2-domain-semantics/core_promo_campaign.l2.json
python3 scripts/validators/validate_binding_manifest.py \
    --manifest examples/binding-manifests/core_promo_campaign.l3.binding.json \
    --binding-topology /tmp/spc_slot/binding-topology.json --json
```

Pinned by self-test `[74]` in `test/run_cpp_tests.sh` (positive + the three fail-closed negatives).

## Fail-closed negatives

| Negative | Fails at | Result |
|---|---|---|
| [`negatives/reimbursement_mismatch.neu`](negatives/reimbursement_mismatch.neu) | translator (`assert balanced`) | reimbursement integrity — pool debit ≠ payout → not balanced |
| [`../../l2-domain-semantics/negatives/core_promo_campaign/over_budget.l2.json`](../../l2-domain-semantics/negatives/core_promo_campaign/over_budget.l2.json) | `validate_l2_domain_semantics` | the total-outlay budget guard's `param:budget_cap` is undeclared → `L2-1008` |
| [`../../l2-domain-semantics/negatives/core_promo_campaign/invalid_attribution.l2.json`](../../l2-domain-semantics/negatives/core_promo_campaign/invalid_attribution.l2.json) | `validate_l2_domain_semantics` | the `attribution_is_unique` invariant's `onFailure` names an undeclared failure mode → `L2-1007` |
| [`../../l2-domain-semantics/negatives/core_promo_campaign/double_redemption.l2.json`](../../l2-domain-semantics/negatives/core_promo_campaign/double_redemption.l2.json) | `validate_l2_domain_semantics` | the redemption-limit guard's `param:max_redemptions` is undeclared → `L2-1008` |

## References

- Gap-analysis parent: internal-tracker/neutrino- · payment simulation: internal-tracker/payment-network-simulation.
- Layer contracts: [`docs/domains/L2_DOMAIN_SEMANTICS.md`](../../../docs/domains/L2_DOMAIN_SEMANTICS.md) · [`docs/binding/BINDING_MANIFEST.md`](../../../docs/binding/BINDING_MANIFEST.md) · add-a-domain: [`docs/domains/ADDING_A_NEW_DOMAIN.md`](../../../docs/domains/ADDING_A_NEW_DOMAIN.md).
