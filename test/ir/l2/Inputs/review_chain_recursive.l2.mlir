// S7 () — the UNBOUNDED/recursive review-chain relation as an actual CYCLE:
// stage_a escalates to stage_b, which escalates back to stage_a. A review chain that
// recurses without bound. The authoritative reducer refuses it before any dispatch:
// an l2.reduce edge must target a declared L1 feature, so a concept->concept stage
// relation (acyclic or cyclic) cannot be expressed at all — recursive staging has no
// representation. The refusal is pinned as a stable tuple (op + obligation + anchor).
l2.domain "coordinate.review_chain" attributes {version = "1.0.0", implements = "coordinate.review_chain"} {
  l2.l1_feature "attestation:quorum" {kind = "primitive"}
  l2.concept "stage_a" {kind = "state", classification = "executable"}
  l2.concept "stage_b" {kind = "state", classification = "executable"}
  l2.reduce "r_ab" "stage_a" -> "stage_b" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_ba" "stage_b" -> "stage_a" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r_ab" {source = "review-board-policy", status = "accepted"}
  l2.provenance "r_ba" {source = "review-board-policy", status = "accepted"}
}
