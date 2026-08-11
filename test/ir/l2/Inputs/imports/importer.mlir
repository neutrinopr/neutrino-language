// An l2.domain that imports coordinate.b @ 1.0.0 — the fixture the import
// resolver runs against the registries in this directory.
l2.domain "coordinate.a" attributes {version = "1.0.0", implements = "coordinate.a"} {
  l2.import "coordinate.b" {version = "1.0.0"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "r" "x" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r" {source = "s", status = "accepted"}
}
