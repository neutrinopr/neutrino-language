// The reordered-equivalent input for domain_semantics_parity.mlir: identical
// records, the two provenance entries in the OPPOSITE source order. No RUN line
// — this is a fixture referenced via %S/Inputs/, not a test.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "e" "x" -> "f" {relation = "expands", lossiness = "lossless"}
  l2.provenance "e" {source = "source-b", status = "accepted"}
  l2.provenance "e" {source = "source-a", status = "accepted"}
}
