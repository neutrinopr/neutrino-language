// Unregistered feature: not in knownSemanticFeatures. Fixture, no RUN.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "totally:madeup" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "r" "x" -> "totally:madeup" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r" {source = "s", status = "accepted"}
}
