// A valid l2.domain whose L1 anchors (effect:debit, invariant:balanced) are
// induced by the committed core_document_escrow coordination plan — so its emitted
// v2 sidecar both validates AND reduces. The base artifact for the re-ingest
// trust-seam drift corpus (sidecar_reingest_contract.test).
l2.domain "coordinate.core_document_escrow" attributes {version = "1.0.0", implements = "coordinate.core_document_escrow", coverage = "partial"} {
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.concept "escrow_funded" {kind = "state", classification = "executable"}
  l2.concept "settlement_balanced" {kind = "concept", classification = "descriptive"}
  l2.reduce "r_funded" "escrow_funded" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_balanced" "settlement_balanced" -> "invariant:balanced" {relation = "protects", lossiness = "lossless"}
  l2.provenance "r_funded" {source = "UCC-9", status = "accepted"}
}
