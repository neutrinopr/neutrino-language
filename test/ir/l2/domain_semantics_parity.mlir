// RUN: %neutrino-emit --kind=domain-semantics %s > %t.a
// RUN: %neutrino-emit --kind=domain-semantics %S/Inputs/domain_semantics_parity_b.mlir > %t.b
// RUN: diff %t.a %t.b
//
// Reordered-equivalent-input parity ( review): two provenance records may
// legitimately share a subject, so sorting by `subject` alone is not a total
// order. This module and Inputs/domain_semantics_parity_b.mlir declare the SAME
// records with the two provenance entries in OPPOSITE source order; sorting each
// array by its full canonical form is a total order, so both emit byte-identical
// sidecars (same bytes => same domainSemanticsHash).

l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "e" "x" -> "f" {relation = "expands", lossiness = "lossless"}
  l2.provenance "e" {source = "source-a", status = "accepted"}
  l2.provenance "e" {source = "source-b", status = "accepted"}
}
