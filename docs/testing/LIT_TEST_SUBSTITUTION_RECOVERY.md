# `%test` lit recovery — bounded P0 follow-up

This report records the isolated `%test` substitution repair measured at
translator `5db5e826f017c64a88ef93c3a2734b22ce66a26a`. It is a recovery
inventory, not authorization to repair the residual failures.

The measured command was:

```sh
lit -q -o <result.json> out/test/ir
```

Both runs used the same clean Release build, LLVM/FileCheck 15.0.5, the pinned
seven-member domain-pack checkout at
`95d97bf2a4e64ee0493b83e8d607fdbbcbb32ebb`, and the same 196 discovered
tests. The negative control removed only the `%test` substitution:

| State | Passed | Failed | Unresolved | Non-passing |
|---|---:|---:|---:|---:|
| `%test` absent | 130 | 65 | 1 | 66 |
| `%test` defined | 166 | 29 | 1 | 30 |

The repair therefore recovers exactly 36 tests and leaves 30 independently
classified residuals. The focused `lit_test_substitution.test` passes in the
repaired run and fails in the negative control.

## Residual classes

| Class | Count | Boundary |
|---|---:|---|
| `generic-solidity-expression` | 4 | Generic Solidity lowering rejects comparison predicates; owned by , not this repair. |
| `externalized-fixture-reachback` | 15 | A migrated lit helper still expects retired production-domain/example paths, fixture counts, or their generated artifacts. |
| `stale-contract-evidence` | 10 | A committed digest, inventory, diagnostic, catalog, schema classification, or golden no longer matches the live surface. |
| `lit-local-define-collision` | 1 | A test-local `DEFINE:` duplicates an already-defined substitution. |

## Exact residual inventory

| Result | Test | Class | Observed boundary |
|---|---|---|---|
| FAIL | `backend/solidity_goldens.test` | `generic-solidity-expression` | Published token-mint render reaches “comparison predicate is not a value expression.” |
| FAIL | `canonical_plan_semantics.test` | `generic-solidity-expression` | Token-mint Solidity pair reconstruction reaches the same generic expression refusal. |
| FAIL | `legality/time_dependent.neu` | `generic-solidity-expression` | A non-token temporal fixture reaches the same comparison-expression refusal. |
| FAIL | `token/token_supply.test` | `generic-solidity-expression` | Token-mint Solidity generation reaches the same comparison-expression refusal. |
| FAIL | `domain/binding_manifest.test` | `externalized-fixture-reachback` | Reviewed binding-manifest input is absent; positive and mutation rows exit as bad input. |
| FAIL | `domain/binding_topology.test` | `externalized-fixture-reachback` | Retired `core_flexible_binding` generation yields no topology; mutation setup receives `None`. |
| FAIL | `domain/translation_map.test` | `externalized-fixture-reachback` | Legacy example-backed rail projection does not lower. |
| FAIL | `equiv/trace_equivalence.test` | `externalized-fixture-reachback` | No legacy example samples are discovered; the non-vacuity floor correctly bites at 0/5. |
| FAIL | `pipeline/capability_spec.test` | `externalized-fixture-reachback` | `examples/domains/core_sponsored_offer` capability-spec is absent. |
| FAIL | `pipeline/characterization.test` | `externalized-fixture-reachback` | `core_sponsored_offer` generated slot identity is absent. |
| FAIL | `pipeline/computed_expect.test` | `externalized-fixture-reachback` | `core_sample_installment` production example scenario is absent. |
| FAIL | `pipeline/multi_slot_binding.test` | `externalized-fixture-reachback` | `core_dual_offer` slot generation does not produce the expected legacy fixture. |
| FAIL | `pipeline/participant_views.test` | `externalized-fixture-reachback` | Only three example-backed view fixtures remain; the legacy floor expects more. |
| FAIL | `pipeline/slot_from_spec.test` | `externalized-fixture-reachback` | Retired example source does not produce the compared slot artifacts. |
| FAIL | `pipeline/target_profiles.test` | `externalized-fixture-reachback` | The legality portfolio still enumerates the retired production-example topology. |
| FAIL | `pipeline/test_realization.test` | `externalized-fixture-reachback` | `core_sample_installment` committed test-realization artifact is absent. |
| FAIL | `pipeline/views.test` | `externalized-fixture-reachback` | The helper still starts from retired `core_flexible_binding` example paths. |
| FAIL | `samples/l2_core_dual_offer.test` | `externalized-fixture-reachback` | The surviving catalog row no longer cites the expected L2 sidecar. |
| FAIL | `samples/l3_evolution.test` | `externalized-fixture-reachback` | Legacy L3 manifest inputs are absent; positive and negative rows exit as bad input. |
| FAIL | `bundle/bundle_completeness.test` | `stale-contract-evidence` | Nine live schemas are unclassified by the committed core/non-core bundle contract. |
| FAIL | `compat/target_registry_def.test` | `stale-contract-evidence` | Runtime target order contains `coordination-plan`; the checked registry order does not. |
| FAIL | `evidence/core_evidence_only_milestone.test` | `stale-contract-evidence` | The expected committed Solidity golden path is absent. |
| FAIL | `l2/l2v2_compat.test` | `stale-contract-evidence` | The frozen `domainSemanticsHash` differs from the recomputed value. |
| FAIL | `obligation_reference_vectors.test` | `stale-contract-evidence` | The complete reviewed vector payload differs from its committed digest. |
| FAIL | `oracle/neg_multi_policy.neu` | `stale-contract-evidence` | Expected prose diagnostic was replaced by the finalized-sequence diagnostic identity. |
| FAIL | `oracle/neg_quorum_guard_median.neu` | `stale-contract-evidence` | Expected prose diagnostic was replaced by `canonicalization-unsupported`. |
| FAIL | `pipeline/cpp_policy_ratchet.test` | `stale-contract-evidence` | The clean live tree does not match the committed C++ policy baseline. |
| FAIL | `pipeline/m5_scorecard.test` | `stale-contract-evidence` | Four expected render-gap diagnostic strings no longer match live diagnostics. |
| FAIL | `pipeline/target_node_registry.test` | `stale-contract-evidence` | The committed printer inventory/seals lag the 41 generated PostgreSQL handlers. |
| UNRESOLVED | `backend/solidity_from_spec.test` | `lit-local-define-collision` | `%{cer}` is defined globally before this test’s local `DEFINE:` directive. |

No residual above is fixed, suppressed, rebaselined, or reclassified by this
P0. Each remains visible for its owning follow-up.
