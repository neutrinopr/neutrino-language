// S7 () — the bounded review chain as a source-neutral L2 domain-semantics
// artifact, reduced through the AUTHORITATIVE bridge (neutrino-emit
// --kind=domain-reduction --reduce-against). Both review stages are concepts that
// reduce to the REGISTERED closed-waist feature attestation:quorum; the effect and
// balance obligations are declared l1_features. The reduction SUCCEEDS — the leaf
// concepts reduce to the closed requirement set. What cannot be expressed is a
// concept->concept ordering edge (an l2.reduce target must be a declared L1
// feature, not another concept — see review_chain_recursive.l2.mlir), and the
// canonical reduction is invariant under stage permutation (review_chain_permuted).
l2.domain "coordinate.review_chain" attributes {version = "1.0.0", implements = "coordinate.review_chain"} {
  l2.l1_feature "attestation:quorum" {kind = "primitive"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "effect:credit" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.concept "assessor_review" {kind = "state", classification = "executable"}
  l2.concept "reviewer_signoff" {kind = "state", classification = "executable"}
  l2.reduce "r_assessor" "assessor_review" -> "attestation:quorum" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_reviewer" "reviewer_signoff" -> "attestation:quorum" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r_assessor" {source = "review-board-policy", status = "accepted"}
  l2.provenance "r_reviewer" {source = "review-board-policy", status = "accepted"}
}
