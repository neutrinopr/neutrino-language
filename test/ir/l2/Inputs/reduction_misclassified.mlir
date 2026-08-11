// Misclassified: invariant:balanced is an obligation, declared primitive. Fixture.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "invariant:balanced" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "r" "x" -> "invariant:balanced" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r" {source = "s", status = "accepted"}
}
