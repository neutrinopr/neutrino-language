// S7 () — stage-permuted twin of review_chain.l2.mlir: the reviewer stage is
// declared BEFORE the assessor stage. If the L2 carried the assessor-before-reviewer
// dependency as a declaration-order difference, the two would reduce differently; the
// authoritative reducer normalizes both to a byte-identical canonical requirement
// graph, proving DECLARATION-ORDER invariance only. The semantic ordering loss is
// witnessed separately by the concept-target refusal in review_chain_recursive.l2.mlir
// (l2.reduce edges must target L1 features), the single-L2 overload witness (ADR §7).
l2.domain "coordinate.review_chain" attributes {version = "1.0.0", implements = "coordinate.review_chain"} {
  l2.l1_feature "attestation:quorum" {kind = "primitive"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "effect:credit" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.concept "reviewer_signoff" {kind = "state", classification = "executable"}
  l2.concept "assessor_review" {kind = "state", classification = "executable"}
  l2.reduce "r_reviewer" "reviewer_signoff" -> "attestation:quorum" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_assessor" "assessor_review" -> "attestation:quorum" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r_reviewer" {source = "review-board-policy", status = "accepted"}
  l2.provenance "r_assessor" {source = "review-board-policy", status = "accepted"}
}
