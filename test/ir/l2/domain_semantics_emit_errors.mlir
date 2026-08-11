// RUN: %not %neutrino-emit --kind=domain-semantics %s 2>&1 | %FileCheck %s
//
// The sidecar emitter fails closed when the module is not exactly one direct
// l2.domain. This file has TWO domains, so it is refused rather than silently
// picking one — the hash must cover the whole input.

// CHECK: more than one l2.domain
l2.domain "a" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
}
l2.domain "b" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "g" {kind = "primitive"}
  l2.concept "y" {kind = "state", classification = "descriptive"}
  l2.reduce "e2" "y" -> "g" {relation = "protects", lossiness = "lossless"}
}
