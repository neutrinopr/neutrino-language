// RUN: %not %neutrino-emit --kind=domain-semantics %s 2>&1 | %FileCheck %s
//
// A sibling operation alongside the l2.domain is refused: otherwise the extra
// op would ride along uncommitted, absent from the bytes the hash covers.

// CHECK: exactly one l2.domain and no other operations
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
}
module { }
