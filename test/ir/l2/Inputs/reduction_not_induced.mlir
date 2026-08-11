// coordination plan-absent: attestation:quorum is registered but core_document_escrow does not induce it. Fixture.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "attestation:quorum" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "r" "x" -> "attestation:quorum" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r" {source = "s", status = "accepted"}
}
