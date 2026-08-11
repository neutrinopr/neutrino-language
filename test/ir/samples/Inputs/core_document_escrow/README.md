# core_document_escrow

The second strategy [] sample as **current-valid** translator artifacts (issue ) —
a different shape from `core_installment_fulfillment`: **document-as-evidence**,
**conditional release/refund** with mutually exclusive terminal outcomes, and
**verification / auto-refund timeouts**.

- **L1** [`source/core_document_escrow.neu`](source/core_document_escrow.neu) — real
  procedure-oriented `.neu`: the balanced escrow movement (Buyer funds `buyer.escrow`, the
  EscrowAgent holds `escrow.holding`), participants Buyer / Seller / EscrowAgent, the
  `EscrowAgent` slot `to_be_bound`. No pseudo `capability`/`domain_semantics`/`lifecycle_states`
  source syntax.
- **L2** two participant-specific sidecars refining `coordinate.core_document_escrow`:
  - [`core_document_escrow.release.l2.json`](../../l2-domain-semantics/core_document_escrow.release.l2.json) — the Seller-release branch.
  - [`core_document_escrow.refund.l2.json`](../../l2-domain-semantics/core_document_escrow.refund.l2.json) — the Buyer-refund branch.
  Both declare the document evidence requirements **`bill_of_lading` / `inspection_certificate`
  / `quality_report`**, the **`verification_timeout` / `auto_refund_timeout`** parameters,
  and represent release/refund success/failure as concepts + `failureModes` + structured
  `compare` guards/invariants (no free-form strings). They are checked for branch-boundary
  compatibility () by `validate_l2_branch_compat.py`.
- **L3** [`core_document_escrow.l3.binding.json`](../../binding-manifests/core_document_escrow.l3.binding.json)
  — binds the `EscrowAgent` slot with concrete timeout values + `backendProfile` `evm.v1`.

## Evidence boundary: L2 declares, M4 admits

**L2 only DECLARES the document evidence requirements (`bill_of_lading`,
`inspection_certificate`, `quality_report`) and the timeout parameters. It makes no runtime
claim — M4 owns runtime document verification and evidence admission**, and there is no real
HTTP/document-verification backend here. See
[`docs/domains/L2_DOMAIN_SEMANTICS.md`](../../../docs/domains/L2_DOMAIN_SEMANTICS.md).

## Validation

Pinned by self-test `[66]`: L1 lowers; both L2 sidecars validate and compose; document
evidence is distinct from `core_installment_fulfillment`'s `proof_of_delivery`; and
targeted negatives fail closed — malformed document evidence (`L2-1001`), undeclared timeout
parameter (`L2-1008`), free-form guard (`L2-1006`), L3 missing required timeout (`NEU-4002`),
L3 parameter type mismatch (`NEU-4003`), and an incompatible release/refund terminal outcome
(`L2X-2003`). The L2 positives/negatives and the branch-compat pair also run in the fast tier
(`make test-fast`); L3 is full-tier (it needs the generated binding-topology). See
[`docs/testing/TESTING.md`](../../../docs/testing/TESTING.md).

[]: internal-tracker/neutrino-
