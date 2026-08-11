// Two l2.domains in one module — the resolver requires EXACTLY one.
l2.domain "coordinate.a" attributes {version = "1.0.0", implements = "coordinate.a"} {
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "r" "x" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r" {source = "s", status = "accepted"}
}
l2.domain "coordinate.d" attributes {version = "1.0.0", implements = "coordinate.d"} {
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.concept "y" {kind = "state", classification = "executable"}
  l2.reduce "r2" "y" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r2" {source = "s", status = "accepted"}
}
